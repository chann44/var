#!/bin/bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
trap 'printf "\nSetup failed. Fix the error above, then rerun ./setup.sh.\n" >&2' ERR

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != media ) ]]; then
    printf 'Usage: ./setup.sh [media]\n' >&2
    exit 2
fi

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf 'Setup requires an Apple silicon Mac running a native arm64 terminal.\n' >&2
    exit 1
fi

if ! git --version >/dev/null 2>&1; then
    printf 'Installing Apple command line tools. Finish the installer, then rerun ./setup.sh.\n' >&2
    xcode-select --install
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    printf 'Installing uv…\n'
    curl -LsSf https://astral.sh/uv/install.sh | \
        env UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh
    export PATH="$HOME/.local/bin:$PATH"
fi

environment=.venv
requirements=requirements.txt
if [[ "${1:-}" == media ]]; then
    environment=.venv-media
    requirements=requirements-media.txt
    if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
        if ! command -v brew >/dev/null 2>&1; then
            printf 'Install FFmpeg (brew install ffmpeg), then rerun ./setup.sh media.\n' >&2
            exit 1
        fi
        brew install ffmpeg
    fi
fi

if [[ ! -e "$environment" ]]; then
    uv venv --python 3.12 "$environment"
fi

"$environment/bin/python" -c 'import platform, sys; assert sys.version_info[:2] == (3, 12), "Use a Python 3.12 environment"; assert platform.machine() == "arm64", "Use an arm64 Python environment"'
uv pip install --python "$environment/bin/python" -r "$requirements"

if [[ "${1:-}" == media ]]; then
    printf '\nChecking the media workflow…\n'
    "$environment/bin/python" -m unittest discover -s tests -p test_studio.py -v
    printf '\nMedia setup complete. Models download on first generation.\n'
    printf 'Activate with: source .venv-media/bin/activate\n'
    printf 'Start with: python studio.py init projects/my-video\n'
    printf 'See docs.md for scene scripts, references, and rendering.\n'
    exit 0
fi

printf '\nRunning tests…\n'
.venv/bin/python -m unittest discover -s tests -v

printf '\nDownloading the model and checking local inference…\n'
.venv/bin/python engine.py --prompt 'Say hello in one sentence.' --max-tokens 16

if [[ ! -e hosts.json ]]; then
    cp hosts.example.json hosts.json
fi

printf '\nSetup complete.\n'
printf 'Next: edit hosts.json with your Macs’ Wi-Fi IP addresses and copy it to every Mac.\n'
printf 'Activate this environment with: source .venv/bin/activate\n'
printf 'See docs.md for the rank 0 and worker commands.\n'
