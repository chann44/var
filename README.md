<img src="assets/var.svg" alt="var" width="280" />

# var

Distributed model inference across a few Macs.

`var` splits a model's layers across two or three Apple silicon Macs over Wi-Fi.
Send a prompt to one Mac and stream the answer back in its terminal.

Built with **Python and MLX**, starting with a small **Qwen2.5 0.5B** model.
The goal is to explore shared model capacity and measure the cost of communicating
between machines.

## Get started

Copy the project to each Mac, then run:

```sh
./setup.sh
source .venv/bin/activate
```

Setup installs dependencies, runs checks, downloads the model, and creates
`hosts.json`. Add your Macs' Wi-Fi IPs, then follow the
[cluster setup instructions](docs.md#2-connect-the-macs).

## Status

Experimental: one prompt per run. Every Mac downloads the full model to disk;
transformer layers are split in memory. Use a trusted private network.
Faster generation and larger-model capacity still need hardware validation.

See [docs.md](docs.md) for architecture, worker commands, benchmarks, options,
and tests.
