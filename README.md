# Distributed Mac inference experiment

Run one Qwen2/Qwen2.5 text model across two or three Apple silicon Macs over Wi-Fi.
Each Mac retains a different group of transformer layers. Rank 0 accepts a prompt
and streams the answer in its terminal. Start with the default small 4-bit
Qwen2.5 0.5B model so we can compare against a single-Mac baseline.

This is an experimental runner around [MLX-LM's pipeline support](https://github.com/ml-explore/mlx-lm/pull/1862)
and [MLX's TCP ring backend](https://ml-explore.github.io/mlx/build/html/usage/distributed.html).
It is not a new tensor runtime. More Macs provide room for weights; faster generation
is an experimental question, especially over Wi-Fi.

## Setup on each Mac

Requirements: Apple silicon, a current macOS supported by MLX 0.32.4, and internet
access. Copy these project files, including `setup.sh` and `tests/`, to each Mac,
then run:

```sh
./setup.sh
source .venv/bin/activate
```

The script installs [uv](https://docs.astral.sh/uv/getting-started/installation/)
if needed, creates a Python 3.12 environment, installs dependencies, runs tests,
and downloads the default model by generating a short response. If Git is missing,
it opens Apple's command line tools installer; finish that installer and rerun
`./setup.sh`. Existing environments and `hosts.json` are preserved. An existing
environment must use native arm64 Python 3.12. Setup can also be invoked from
another directory as `bash /path/to/var/setup.sh`.

Setup creates `hosts.json` from the example when missing. Replace its example
addresses with your actual Wi-Fi IPs and use the same file on every Mac.

The MLX-LM commit is pinned because the released 0.31.3 package lacks Qwen2
pipeline support. Use the same requirements on every Mac. The first model load
needs internet access and stores a checkpoint in the Hugging Face cache.

## First: baseline and download

Run this on each Mac before connecting the cluster, to download the model and
verify that local inference works. Downloads are excluded from generation timings.

```sh
python engine.py --prompt "Explain why the sky is blue in two sentences." --report baseline-report.json
```

Only the response goes to stdout. Layer assignments and measurements go to stderr
and, when requested, the JSON report. Reports include generated token IDs for
comparing single-Mac and distributed results. Sampling is greedy.

## Run across three Macs

1. Find each Mac's Wi-Fi IPv4 address in System Settings → Wi-Fi → Details → TCP/IP.
2. Edit the `hosts.json` created by setup, replacing the example addresses.
   If you skipped setup, copy `hosts.example.json` to `hosts.json` first.
   Give **every Mac the identical file in the identical order**. For two Macs,
   remove the third entry. Each entry is one rank; the port can remain `5500`.
3. Connect to the same trusted network, keep all Macs awake, and allow incoming
   connections to Python if macOS asks. Guest Wi-Fi/client isolation can prevent
   Macs from communicating. Remote Login/SSH is not needed.
4. Activate the environment and start one command on each Mac, within ten minutes:

Mac 2:

```sh
python engine.py --hosts hosts.json --rank 1 --report rank1-report.json
```

Mac 3:

```sh
python engine.py --hosts hosts.json --rank 2 --report rank2-report.json
```

Mac 1 (the only machine receiving the prompt):

```sh
python engine.py --hosts hosts.json --rank 0 --prompt "Explain why the sky is blue in two sentences." --report distributed-report.json
```

Each process exits after this answer. Start all ranks again for another prompt.
Use `--max-tokens 128` on rank 0 to change the output limit, or `--model` for
another Qwen2/Qwen2.5 MLX checkpoint. Model names/paths are sent to workers;
local paths must exist on every Mac. All ranks must use the same checkpoint.
Use `--timeout 1200` on **each** Mac if a run needs a longer deadline.

## What to measure

- Compare `generated_token_ids` in the baseline and distributed reports. They
  should normally match for this greedy run; differences require investigation.
- Check that layer lists across ranks cover every layer exactly once. MLX puts
  the first layers on the highest rank and the final layers on rank 0.
- Compare `first_token_seconds`, `decode_tokens_per_second`, `weight_bytes`,
  and `peak_memory_bytes`. Peak memory is MLX allocation, not total system RAM;
  decode speed excludes prefill and includes network and terminal overhead.
- Disconnect a worker during a longer run: an error or the deadline should end
  each process. Restart every rank together after an error. Exit code `124`
  means the local deadline expired.

## Tests

```sh
python -m unittest discover -s tests -v
```

Configuration and deadline tests use only the standard library. With MLX installed,
the integration test creates a tiny random seven-layer model locally and checks
two- and three-process inference against the single-process token sequence. It
also checks complete, non-overlapping layer ownership and reduced per-rank weight
storage. It requires no model download. Without MLX, it is explicitly skipped.

## Limits of this first experiment

- One request per run, fixed addresses, at most 2048 prompt tokens and 1024 output
  tokens. No automatic worker discovery, batching, or recovery.
- Every Mac downloads the complete checkpoint to disk. Loading is lazy and layers
  are removed before materializing weights, but embeddings, final normalization,
  and the output head are replicated. Memory will not divide into exact thirds.
- The small model intentionally fits on one Mac. A larger-than-one-Mac model is
  the next experiment after real three-Mac correctness and memory checks pass.
- TCP traffic has no authentication or encryption: use only a trusted private
  network and keep the port off the public internet.
- Tests on one Mac do not establish three-Mac Wi-Fi performance or reliability.

Source is in `engine.py`; tests are in `tests/`. `AGENTS.md` is preserved unchanged.
