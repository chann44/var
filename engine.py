"""One prompt, one Qwen2 model, optionally split across a TCP ring of Macs."""

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

DEFAULT_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"


def read_hosts(path):
    hosts = json.loads(Path(path).read_text())
    if not isinstance(hosts, list) or not 2 <= len(hosts) <= 3:
        raise ValueError("Hostfile must contain two or three ranks.")
    endpoints = set()
    for entry in hosts:
        if not isinstance(entry, list) or len(entry) != 1 or not isinstance(entry[0], str):
            raise ValueError('Each rank needs one endpoint, e.g. ["192.168.1.10:5500"].')
        address, port = entry[0].rsplit(":", 1)
        ip = ipaddress.IPv4Address(address)
        if ip.is_unspecified or ip.is_multicast or not 1024 <= int(port) <= 65535:
            raise ValueError("Use a reachable IPv4 address and port 1024–65535.")
        endpoint = (str(ip), int(port))
        if endpoint in endpoints:
            raise ValueError("Each rank must have a distinct IP/port endpoint.")
        endpoints.add(endpoint)
    return hosts


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", type=Path, help="MLX TCP ring hostfile")
    parser.add_argument("--rank", type=int, help="Zero-based position in the hostfile")
    parser.add_argument("--prompt", help="Prompt supplied on rank 0 only")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Qwen2 MLX repo or local path")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=600, help="Whole-run deadline in seconds")
    parser.add_argument("--report", type=Path, help="Save this rank's measurements and token IDs")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if (args.hosts is None) != (args.rank is None):
            raise ValueError("Supply --hosts and --rank together, or neither for a baseline.")
        if args.hosts is not None:
            hosts = read_hosts(args.hosts)
            if not 0 <= args.rank < len(hosts):
                raise ValueError("Rank must be an index in the hostfile.")
        if args.rank in (None, 0):
            if not args.prompt or not args.prompt.strip():
                raise ValueError("Supply a nonempty --prompt on rank 0 or for a baseline.")
            if len(args.prompt.encode("utf-8")) > 16384:
                raise ValueError("Keep the prompt below 16 KiB for this experiment.")
        elif args.prompt is not None:
            raise ValueError("Supply the prompt only on rank 0; workers receive it automatically.")
        if not 1 <= args.max_tokens <= 1024:
            raise ValueError("--max-tokens must be between 1 and 1024.")
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be a positive, finite number.")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def run(args):
    try:
        import mlx.core as mx
        from mlx.utils import tree_flatten
        from mlx_lm import load
        from mlx_lm.models.cache import make_prompt_cache
    except ImportError as error:
        raise RuntimeError("Activate .venv and run: uv pip install -r requirements.txt") from error

    rank = args.rank or 0
    world = None
    if args.hosts:
        os.environ["MLX_HOSTFILE"] = str(args.hosts.resolve())
        os.environ["MLX_RANK"] = str(rank)
        print(f"[rank {rank}] Waiting for all Macs…", file=sys.stderr, flush=True)
        world = mx.distributed.init(backend="ring", strict=True)
        if world.size() != len(read_hosts(args.hosts)) or world.rank() != rank:
            raise RuntimeError("MLX initialized an unexpected group; refusing single-node fallback.")

    def share(values):
        if world is None:
            return values
        return mx.distributed.all_sum(
            mx.array(values, dtype=mx.int32), group=world, stream=mx.cpu
        ).tolist()

    request = json.dumps({"model": args.model, "prompt": args.prompt,
                          "max_tokens": args.max_tokens}).encode() if rank == 0 else b""
    length = share([len(request)])[0]
    if not 0 < length <= 131072:
        raise ValueError("Invalid request length received from coordinator.")
    request = json.loads(bytes(share(list(request) if rank == 0 else [0] * length)))
    print(f"[rank {rank}] Loading {request['model']}…", file=sys.stderr, flush=True)
    # shortcut: download a complete checkpoint per Mac; shard disk files for larger-model experiments.
    model, tokenizer = load(request["model"], lazy=True,
                            tokenizer_config={"trust_remote_code": False})
    if model.model_type != "qwen2":
        raise ValueError("This MVP supports Qwen2/Qwen2.5 text models only.")
    if world is not None:
        if not hasattr(model.model, "pipeline"):
            raise RuntimeError("Qwen2 pipeline support is missing; install requirements.txt.")
        model.model.pipeline(world)
    mx.eval(model.parameters())
    layers = [i for i, layer in enumerate(model.model.layers) if layer is not None]
    weight_bytes = sum(value.nbytes for _, value in tree_flatten(model.parameters()))
    print(f"[rank {rank}] Layers {layers}; weights {weight_bytes / 1e6:.1f} MB",
          file=sys.stderr, flush=True)

    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": request["prompt"]}],
        tokenize=True, add_generation_prompt=True,
    )
    if len(prompt) > 2048:
        raise ValueError("This MVP accepts at most 2048 prompt tokens.")
    cache = make_prompt_cache(model)
    detokenizer = tokenizer.detokenizer
    detokenizer.reset()
    tokens = []
    inputs = mx.array([prompt], dtype=mx.int32)
    share([0])  # All shards must finish loading before timing generation.
    started = time.perf_counter()
    first_token_seconds = None
    decode_started = None
    decode_tokens = 0
    for _ in range(request["max_tokens"]):
        logits = model(inputs, cache=cache)
        mx.eval(logits)  # Every rank must execute its pipeline, even though rank 0 samples.
        token = int(mx.argmax(logits[0, -1]).item()) if rank == 0 else 0
        token = share([token])[0]
        now = time.perf_counter()
        if first_token_seconds is None:
            first_token_seconds = now - started
            decode_started = now
        else:
            decode_tokens += 1
        if token in tokenizer.eos_token_ids:
            break
        tokens.append(token)
        if rank == 0:
            detokenizer.add_token(token)
            print(detokenizer.last_segment, end="", flush=True)
        inputs = mx.array([[token]], dtype=mx.int32)
    finished = time.perf_counter()
    if rank == 0:
        detokenizer.finalize()
        print(detokenizer.last_segment, flush=True)
    report = {
        "rank": rank, "world_size": world.size() if world else 1,
        "model": request["model"], "layers": layers, "weight_bytes": weight_bytes,
        "prompt_tokens": len(prompt), "generated_token_ids": tokens,
        "first_token_seconds": first_token_seconds,
        "generation_seconds": finished - started,
        "decode_tokens_per_second": decode_tokens / (finished - decode_started) if decode_tokens else 0,
        "peak_memory_bytes": mx.get_peak_memory(),
    }
    print(f"[rank {rank}] {json.dumps(report)}", file=sys.stderr, flush=True)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    if not args._worker:
        # A separate process enforces the deadline even if native communication hangs.
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), *argv, "--_worker"],
                timeout=args.timeout,
            )
            return result.returncode if result.returncode >= 0 else 1
        except subprocess.TimeoutExpired:
            print("Run timed out. Check worker terminals, IPs, firewall, and model downloads; "
                  "restart every rank together.", file=sys.stderr)
            return 124
        except KeyboardInterrupt:
            return 130
    try:
        run(args)
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        print(f"Inference failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
