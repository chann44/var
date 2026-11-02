# var documentation

[Back to the overview](README.md).

## Narrated videos

The first media workflow produces videos from still images with gentle zooms,
clean scene cuts, narration, and scene-level captions. It starts with an
approximately 15-second example. Video duration follows the generated speech;
add scenes and edit the script to make a minute-long project.

### Install

On the Mac doing generation:

```sh
./setup.sh media
source .venv-media/bin/activate
```

Setup uses an isolated `.venv-media` environment and
[requirements-media.txt](requirements-media.txt), leaving the text runner's
environment alone. It installs FFmpeg through Homebrew if FFmpeg is missing and
Homebrew is available. Otherwise install FFmpeg first (`brew install ffmpeg`).
Models download on first generation, not during setup.

Starting candidates, not a quality ranking:

- **Speech:** `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit` through
  [MLX Audio](https://github.com/Blaizzy/mlx-audio). The example uses Vivian and
  English; change `voice` and `language` in the project for supported presets.
- **Images:** FLUX.2 Klein 4B through
  [MFLUX](https://github.com/mflux-community/mflux/blob/main/src/mflux/models/flux2/README.md),
  using four steps and 4-bit quantization at 512 × 896. Reference images use the
  image-editing route. These settings still need quality and memory checks on
  your specific 16 GB Macs. Initial checkpoints can require substantial disk
  space even when inference is quantized.

### Create a project

Start with the included three-scene example:

```sh
python studio.py init projects/my-video
```

Or turn your own script into a project. Put a blank line between scenes:

```sh
python studio.py init projects/my-video --script my-script.txt
```

Each paragraph becomes a narration segment and an initial image prompt. Edit
`project.json` to describe what should appear visually instead of leaving the
narration as the image prompt. `init` refuses to overwrite an existing project.

A scene looks like this:

```json
{
  "id": "01",
  "narration": "Every story begins with a small idea.",
  "image_prompt": "Use the reference character, sitting beside a sunlit window with a notebook.",
  "seed": 42,
  "references": ["references/character.png"]
}
```

Copy references into the project folder and use relative paths. Each scene accepts
up to four reference images; an empty list generates from text alone. The global
`style` is added to every image prompt. Seeds are recorded for reproducibility;
reference guidance does not guarantee identical characters across scenes.

### Generate and assemble

Preview the model commands without downloading or loading weights:

```sh
python studio.py build projects/my-video --dry-run
```

Generate narration and images, then assemble the video:

```sh
python studio.py build projects/my-video
```

Or run stages individually:

```sh
python studio.py narrate projects/my-video
python studio.py images projects/my-video
python studio.py assemble projects/my-video
```

The first two stages require the media environment and Metal GPU access. Assembly
needs only Python and FFmpeg and also accepts your own supplied PNG/WAV assets.
Each external command has a one-hour deadline. Generator processes restart per
scene to release memory between models; persistent workers are deferred.

### Review and revise

Edit a scene's text, prompt, references, or seed, then regenerate that stage:

```sh
python studio.py images projects/my-video --scene 02
python studio.py narrate projects/my-video --scene 02
python studio.py assemble projects/my-video
```

Unchanged generated assets are reused. Input signatures include reference file
contents, so replacing a reference under the same filename triggers regeneration.
Use `--force` to regenerate an unchanged asset or replace a supplied file.
A failed generation or render preserves its previous output. Successful
regeneration replaces the selected asset; copy approved versions before trying
alternatives you may want to keep.

### Improve narration and pacing

Assembly trims silence at the edges of scene recordings, keeping 40 ms before
speech and 80 ms after it. Pauses inside sentences are retained. It normalizes
the finished narration to -16 LUFS and uses clean scene cuts, with fades only at
the beginning and end of the video.

The default `speech_rate` is `1.08`: a modest pitch-preserving speed increase.
Set it between `0.75` and `1.35` in `project.json`; `1.0` keeps the recorded speaking
rate. This is applied with FFmpeg because Qwen3-TTS's native speed argument is
not implemented. To try a different pace with existing audio and images, rerun:

```sh
python studio.py assemble projects/my-video
```

Raw files in `audio/` remain untouched; captions and scene lengths follow the
processed recordings. `render.json` records both original and edited durations.

For an exact output length, set `"target_duration": 60` in `project.json`.
Assembly fits scene boundaries to whole frames and adjusts audio tempo to match.
It rejects a target that would need excessive stretching; change the script
length or remove the target in that case. With a fixed duration, the script's
length determines the final speaking pace.

For more control over delivery, audition the larger
[1.7B CustomVoice model](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit).
Set these top-level fields in `project.json`:

```json
{
  "speech_model": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
  "voice_direction": "Warm, conversational narration for a short video. Brisk pace, natural emphasis, brief pauses between ideas.",
  "speech_rate": 1.08
}
```

Then run `narrate` and `assemble` again. The 0.6B model remains the default and
does not support delivery instructions; specifying `voice_direction` with it is
rejected instead of silently ignored. The larger model needs another download
and may generate more slowly. Its quality still needs a listening comparison.
Narration is still synthesized per scene; a single full-script performance with
aligned scene timings is a separate next step for stronger continuity.

### Audition Chatterbox

Chatterbox Turbo FP16 is an alternative for English narration. To test it, set
`"speech_model": "mlx-community/chatterbox-turbo-fp16"` in `project.json`.
Remove `voice_direction` if present; Turbo does not accept Qwen's instruction
control. Its voice comes from the checkpoint's default conditioning or your
recording, so the Qwen `voice` preset does not apply.

For your own reference voice, copy a clean recording into the project and add
`"reference_audio": "references/voice.wav"`. This integration accepts recordings
longer than 5 and at most 30 seconds; 6–15 seconds of clean speech is a useful
starting point. No transcript or additional speech-recognition model is needed.
Reference file contents participate in the speech cache signature.

```sh
python studio.py audition projects/my-video --scene 01
```

The command writes a fresh take under `auditions/01-*/`: raw audio, a paced and
loudness-normalized `preview.wav`, and its settings. It leaves approved `audio/`
and video outputs intact. Omit `--scene` to audition the first scene, or use
`--dry-run` to inspect the model command without generating audio. The same command
works with either supported Qwen model for a comparison.

After selecting a voice, run `narrate` and `assemble` to use it in the video.
The existing default remains Qwen 0.6B until a listening comparison establishes
which voice to use. See [the evaluation](#chatterbox-evaluation) for model variants,
controls, and the remaining hardware uncertainties.

### Lisp origin short

The repository includes an original, code-led short about Lisp's origins, with
14 supplied portrait graphics, a spoken script, a storyboard, and historical
sources. Create its project with:

```sh
python examples/lisp_origin.py
python studio.py narrate projects/lisp-origin
python studio.py assemble projects/lisp-origin
```

Run these in the media environment on a Mac with Metal access. The first command
uses Pillow to draw readable code and titles instead of asking an image model
to spell them. It refuses to overwrite an existing project. The narrated export
targets 60 seconds and uses Chatterbox Turbo. `storyboard.md` contains planned
cut timings; actual timings are derived from the generated speech.

### Outputs

```text
projects/my-video/
├── project.json       # editable narration, image prompts, seeds, voice, references
├── references/        # your reference images
├── audio/01.wav       # narration per scene, plus generation records
├── images/01.png      # image per scene, plus generation records
├── narration.wav      # combined narration, padded to scene boundaries
├── captions.srt       # captions timed per scene
├── render.json        # settings, source hashes, and measured durations
└── final.mp4          # H.264 video, AAC audio, selectable captions
```

Captions are a selectable MP4 subtitle track, not burned into the image. Enable
captions in your player; exporting burned-in captions for social platforms is
future work. Audio timing is preserved by rounding each scene up to the next
video frame, adding less than one frame of silence where necessary.

### Use multiple Macs

For now, copy the same project to two Macs. Run `narrate` on one and `images` on the
other, then copy `audio/` and `images/` into one project and run `assemble` there.
Keep matching generation-record JSON files when copying assets. Keep the same
project settings and dependency versions on each Mac.

This distributes independent stages. Media weight sharding, automatic scheduling,
video diffusion, voice cloning, music, and automatic script writing are deferred.
The existing distributed Qwen experiment remains available below.

### Verify the workflow

```sh
python -m unittest discover -s tests -p test_studio.py -v
```

Tests cover project validation, reference handling, caching, failure preservation,
and actual FFmpeg assembly with synthetic images/audio. They verify scene order,
audio/video/subtitle tracks, duration, and previous-output preservation. These
checks do not establish AI generation quality or two-to-three-video daily throughput.

## Distributed text inference

The following sections describe the original `engine.py` experiment.

### Why

With several Macs available, there are a few questions worth testing:

- Can one model generate correctly with its layers on different machines?
- How much model memory does each Mac actually need?
- What does Wi-Fi add to first-token latency and generation time?
- Could the same approach eventually run a model too large for one Mac?

`var` makes the first experiment small: fixed addresses, one prompt, and reports
that let you compare distributed execution with a local baseline. More machines
can provide room for weights; whether they improve speed needs measurement.

### How it works

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

### Getting started

You need two or three Apple silicon Macs, a macOS version supported by MLX 0.32.4,
internet access for setup, and a trusted local network.

#### 1. Set up each Mac

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

#### 2. Connect the Macs

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

#### 3. Start the workers

On Mac 2:

```sh
python engine.py --hosts hosts.json --rank 1 --report rank1-report.json
```

On Mac 3, if using three Macs:

```sh
python engine.py --hosts hosts.json --rank 2 --report rank2-report.json
```

#### 4. Send a prompt

On Mac 1, start rank 0 within ten minutes of starting the workers:

```sh
python engine.py --hosts hosts.json --rank 0 \
  --prompt "Explain why the sky is blue in two sentences." \
  --report distributed-report.json
```

The response streams to this terminal. Each process exits after one answer;
restart all ranks for another prompt or after a failure.

### Compare with one Mac

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

### Options

```sh
python engine.py --help
```

- `--model`: a Qwen2/Qwen2.5 MLX repository or local checkpoint path, set on rank 0.
  Local paths must exist on every Mac.
- `--max-tokens`: output limit, set on rank 0; defaults to `64`.
- `--timeout`: whole-run deadline in seconds; defaults to `600`. Set it on every
  Mac when allowing longer runs. Exit code `124` means the deadline expired.
- `--report`: optional JSON report path, local to each rank.

### Tests

```sh
python -m unittest discover -s tests -v
```

The suite checks configuration validation, process deadlines, and setup behavior.
With MLX and a Metal GPU available, an integration test creates a tiny seven-layer
model and compares two- and three-process generation with a single process. It
also checks layer ownership and per-rank weight storage. No model download is
needed for this test; it is skipped when MLX or Metal is unavailable.

### Current limits

- One request per run, with fixed worker addresses and no automatic recovery.
- At most 2048 prompt tokens, 16 KiB of prompt text, and 1024 output tokens.
- Full checkpoint downloads on every Mac; partial downloads are deferred.
- TCP traffic has no authentication or encryption. Use a trusted private network
  and keep the port off the public internet.
- The default model fits on one Mac. Larger-model capacity and three-Mac Wi-Fi
  performance still need hardware validation.

The runner lives in [engine.py](engine.py), setup in [setup.sh](setup.sh), and
checks in [tests/](tests/).

## Chatterbox evaluation

Research checked 2026-11-02. **For English narration, audition Chatterbox Turbo
fp16 alongside Qwen3-TTS 1.7B before changing the default.** Turbo is a credible
alternative, especially when a particular reference voice matters; available
sources do not establish that it sounds better than Qwen on this project's
scripts. Keep the existing 0.6B setup until a listening comparison justifies the
change. This is a research recommendation, not an implemented backend.

| Candidate | What it adds | Main tradeoff |
| --- | --- | --- |
| Original Chatterbox | 500M English model; CFG and emotion exaggeration controls | More decoder work than Turbo; expressive settings also change pacing |
| Chatterbox Turbo | 350M English model; distilled single-step decoder; vocal-event tags such as `[chuckle]` and `[sigh]` | No original-style CFG/exaggeration controls |
| Chatterbox Multilingual | Separate 500M family supporting 23 languages, including Hindi | Use a multilingual checkpoint explicitly; Turbo is English-only |

These sizes and capabilities are Resemble's descriptions, not a quality ranking.
The decoder's reduction from ten steps to one does **not** imply tenfold total
speed. [Official model comparison](https://github.com/resemble-ai/chatterbox#-model-zoo),
[Turbo model card](https://huggingface.co/ResembleAI/chatterbox-turbo).

### MLX checkpoints and controls

MLX Audio implements both families. Its current documentation identifies
`mlx-community/chatterbox-fp16` as **multilingual V2**, despite its generic name;
`mlx-community/chatterbox-multilingual-v3` is the newer multilingual option.
Do not confuse either with original English Chatterbox. Both need the separately
downloaded S3TokenizerV2 weights on first use.
[MLX model documentation](https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/chatterbox.md).

Turbo's MLX cards provide a built-in default voice: a reference is needed for
cloning a chosen voice, not for every generation. The implementation loads
`conds.safetensors`; supplied reference audio must be **longer than five seconds**.
Use a clean roughly ten-second clip in the desired delivery, from a voice you
have permission to use. No reference transcript is required by Turbo's API.
Its `cfg_weight`, `exaggeration`, and `min_p` arguments are ignored with a warning;
it offers no native speed parameter or free-form delivery-instruction interface.
Its long-text path splits at sentence boundaries, so a full-minute input still
needs listening for continuity. [Turbo implementation](https://github.com/Blaizzy/mlx-audio/blob/main/mlx_audio/tts/models/chatterbox_turbo/chatterbox_turbo.py),
[default-voice example](https://huggingface.co/mlx-community/chatterbox-turbo-fp16).

Original Chatterbox's CFG/exaggeration controls can shape expression and pacing:
Resemble suggests lower CFG around 0.3 for more deliberate delivery and warns
that higher exaggeration tends to accelerate speech. These are coupled controls,
not an exact words-per-minute setting. The MLX original-family implementation
explicitly ignores `speed`; retain FFmpeg rate adjustment when exact duration
matters. [Official tuning advice](https://github.com/resemble-ai/chatterbox#original-chatterbox-tips),
[MLX original-family implementation](https://github.com/Blaizzy/mlx-audio/blob/main/mlx_audio/tts/models/chatterbox/chatterbox.py).

### Turbo fp16 versus 4-bit on 16 GB Macs

The listed downloads are approximately **2.99 GB fp16** versus **417 MB 4-bit**;
these are repository sizes, not peak unified-memory measurements. The 4-bit
checkpoint uses affine quantization with group size 64. Both are the same Turbo
family and expose the same delivery capabilities. [fp16 files](https://huggingface.co/mlx-community/chatterbox-turbo-fp16/tree/main),
[4-bit files](https://huggingface.co/mlx-community/chatterbox-turbo-4bit/tree/main),
[4-bit configuration](https://huggingface.co/mlx-community/chatterbox-turbo-4bit/blob/main/config.json).

For quality-first, minute-long offline narration, start the audition with fp16
on one otherwise idle 16 GB Mac; its weight size makes that a reasonable trial,
not a verified memory guarantee. Try 4-bit if actual memory pressure or measured
render time calls for it. No controlled fp16-versus-4-bit listening or Mac speed
comparison was found in the checked official repository, MLX implementation,
or checkpoint cards. Quantization saves storage but does not prove equal voice
quality or faster generation. Neither checkpoint currently earns an automatic
recommendation over Qwen3-TTS 1.7B on evidence alone.

The checked primary sources do not give a reproducible benchmark for these
specific 16 GB Macs. Resemble's lower-compute claim and CUDA examples cannot
predict Mac wall time; its advertised sub-200-ms service latency describes the
hosted service. Measure cold load, warm generation, total peak memory, pronunciation,
voice consistency, unwanted repetitions, and usable takes on the same one-minute
script and reference. Use the other Macs for independent image jobs or alternate
takes; there is no evaluated multi-Mac Chatterbox inference path here.
[Official Turbo description and usage](https://huggingface.co/ResembleAI/chatterbox-turbo).

### License

The upstream repository and Turbo card specify **MIT**, while the MLX converted
checkpoint cards label themselves **Apache-2.0**. Record this metadata mismatch
and preserve applicable upstream/conversion notices when distributing weights
or code; do not describe the converted artifacts as uniformly MIT.
[Upstream license](https://github.com/resemble-ai/chatterbox/blob/master/LICENSE),
[upstream card](https://huggingface.co/ResembleAI/chatterbox-turbo),
[converted card](https://huggingface.co/mlx-community/chatterbox-turbo-4bit).
