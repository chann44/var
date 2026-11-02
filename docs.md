# var documentation

[Back to the overview](README.md).

## Why

With several Macs available, there are a few questions worth testing:

- Can one model generate correctly with its layers on different machines?
- How much model memory does each Mac actually need?
- What does Wi-Fi add to first-token latency and generation time?
- Could the same approach eventually run a model too large for one Mac?

`var` makes the first experiment small: fixed addresses, one prompt, and reports
that let you compare distributed execution with a local baseline. More machines
can provide room for weights; whether they improve speed needs measurement.

## How it works

One process runs on each Mac. **Rank 0** is the coordinator: it shares the prompt
with the workers, selects each next token, and prints the response.

For three Macs, transformer layers run in this order:

```text
Mac 3 · rank 2       Mac 2 · rank 1       Mac 1 · rank 0
 first layers   →    middle layers   →    final layers   →   next token
```

The process repeats until the model finishes or reaches the output limit.
Attention caches stay with the layers that own them.

Execution uses [MLX-LM's pipeline support](https://github.com/ml-explore/mlx-lm/pull/1862)
with [MLX's TCP ring backend](https://ml-explore.github.io/mlx/build/html/usage/distributed.html).
Every Mac currently downloads the **full checkpoint to disk**, then retains only
its assigned transformer layers in memory. Embeddings, final normalization, and
output weights are replicated, so memory does not divide into exact thirds.

## Getting started

You need two or three Apple silicon Macs, a macOS version supported by MLX 0.32.4,
internet access for setup, and a trusted local network.

### 1. Set up each Mac

Copy the project, including `setup.sh` and `tests/`, to every Mac. Create each
machine's environment locally rather than copying `.venv`. From the project folder:

```sh
./setup.sh
source .venv/bin/activate
```

Setup installs uv if needed, creates a Python 3.12 environment, installs
dependencies, runs tests, and downloads the default model by generating a short
response. Existing environments and `hosts.json` are preserved. An existing
environment must use native arm64 Python 3.12.

If Git is missing, setup opens Apple's command line tools installer. Finish the
installer and rerun `./setup.sh`. From another directory, use
`bash /path/to/var/setup.sh`.

Dependencies are defined in [requirements.txt](requirements.txt). The MLX-LM
commit is pinned to include Qwen2 pipeline support; use the same requirements
and checkpoint on every Mac.

### 2. Connect the Macs

Find each Wi-Fi IPv4 address in **System Settings → Wi-Fi → Details → TCP/IP**.
Replace the example addresses in the `hosts.json` created by setup:

```json
[
  ["192.168.1.10:5500"],
  ["192.168.1.11:5500"],
  ["192.168.1.12:5500"]
]
```

Use the **same file in the same order** on every Mac. The first entry is rank 0.
For two Macs, remove the third entry. If configuring manually, start with
[hosts.example.json](hosts.example.json).

Keep the Macs awake and allow incoming Python connections if macOS asks. Guest
Wi-Fi with client isolation can block communication. SSH is not required.

### 3. Start the workers

On Mac 2:

```sh
python engine.py --hosts hosts.json --rank 1 --report rank1-report.json
```

On Mac 3, if using three Macs:

```sh
python engine.py --hosts hosts.json --rank 2 --report rank2-report.json
```

### 4. Send a prompt

On Mac 1, start rank 0 within ten minutes of starting the workers:

```sh
python engine.py --hosts hosts.json --rank 0 \
  --prompt "Explain why the sky is blue in two sentences." \
  --report distributed-report.json
```

The response streams to this terminal. Each process exits after one answer;
restart all ranks for another prompt or after a failure.

## Compare with one Mac

Run the same prompt without the hostfile:

```sh
python engine.py \
  --prompt "Explain why the sky is blue in two sentences." \
  --report baseline-report.json
```

Sampling is greedy. Compare `generated_token_ids` between the baseline and
cluster reports; differences need investigation. Across the worker reports,
layer lists should cover every layer exactly once.

Each rank can write a JSON report with:

| Field | What it measures |
| --- | --- |
| `layers` | Transformer layers retained by this rank |
| `weight_bytes` | Retained model weight storage |
| `first_token_seconds` | Time from generation start to the first token |
| `decode_tokens_per_second` | Decode rate, including network and terminal overhead |
| `peak_memory_bytes` | Peak MLX allocation, rather than total system RAM |

Model loading is excluded from generation timings; decode rate excludes prefill.
The response goes to stdout, and diagnostics go to stderr.

## Options

```sh
python engine.py --help
```

- `--model`: a Qwen2/Qwen2.5 MLX repository or local checkpoint path, set on rank 0.
  Local paths must exist on every Mac.
- `--max-tokens`: output limit, set on rank 0; defaults to `64`.
- `--timeout`: whole-run deadline in seconds; defaults to `600`. Set it on every
  Mac when allowing longer runs. Exit code `124` means the deadline expired.
- `--report`: optional JSON report path, local to each rank.

## Tests

```sh
python -m unittest discover -s tests -v
```

The suite checks configuration validation, process deadlines, and setup behavior.
With MLX and a Metal GPU available, an integration test creates a tiny seven-layer
model and compares two- and three-process generation with a single process. It
also checks layer ownership and per-rank weight storage. No model download is
needed for this test; it is skipped when MLX or Metal is unavailable.

## Current limits

- One request per run, with fixed worker addresses and no automatic recovery.
- At most 2048 prompt tokens, 16 KiB of prompt text, and 1024 output tokens.
- Full checkpoint downloads on every Mac; partial downloads are deferred.
- TCP traffic has no authentication or encryption. Use a trusted private network
  and keep the port off the public internet.
- The default model fits on one Mac. Larger-model capacity and three-Mac Wi-Fi
  performance still need hardware validation.

The runner lives in [engine.py](engine.py), setup in [setup.sh](setup.sh), and
checks in [tests/](tests/).
