"""Turn a scene script into narration, images, and a video with scene-level captions."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time

ROOT = Path(__file__).resolve().parent
SPEECH_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
EXPRESSIVE_SPEECH_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
CHATTERBOX_MODEL = "mlx-community/chatterbox-turbo-fp16"
IMAGE_MODEL = "flux2-klein-4b"
FPS = 24
LOUDNESS_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=9"


def nonempty(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be nonempty text of at most {limit} characters.")


def reference_path(directory, reference):
    nonempty(reference, "reference path", 1000)
    path = (directory / reference).resolve()
    if Path(reference).is_absolute() or not path.is_relative_to(directory.resolve()):
        raise ValueError("References must be inside the project folder.")
    if not path.is_file():
        raise ValueError(f"Missing reference: {reference}")
    return path


def load_project(directory):
    project = json.loads((directory / "project.json").read_text())
    if not isinstance(project, dict):
        raise ValueError("project.json must be an object.")
    for key, limit in (("title", 200), ("voice", 100), ("language", 100), ("style", 2000)):
        nonempty(project.get(key), key, limit)
    rate = project.get("speech_rate", 1.08)
    if type(rate) not in (int, float) or not 0.75 <= rate <= 1.35:
        raise ValueError("speech_rate must be a number between 0.75 and 1.35; 1.08 is a mild speed-up.")
    if "target_duration" in project:
        target = project["target_duration"]
        if type(target) not in (int, float) or not 1 <= target <= 600:
            raise ValueError("target_duration must be between 1 and 600 seconds.")
    model = project.get("speech_model", SPEECH_MODEL)
    if model not in (SPEECH_MODEL, EXPRESSIVE_SPEECH_MODEL, CHATTERBOX_MODEL):
        raise ValueError("Choose a supported Qwen3-TTS CustomVoice checkpoint or mlx-community/chatterbox-turbo-fp16.")
    if model == CHATTERBOX_MODEL and project["language"].lower() not in ("en", "english"):
        raise ValueError("Chatterbox Turbo supports English; select Qwen for other languages.")
    if "reference_audio" in project:
        if model != CHATTERBOX_MODEL:
            raise ValueError("reference_audio is supported with Chatterbox Turbo; Qwen CustomVoice uses preset voices.")
        reference_path(directory, project["reference_audio"])
    if "voice_direction" in project:
        nonempty(project["voice_direction"], "voice_direction", 1000)
        if model != EXPRESSIVE_SPEECH_MODEL:
            raise ValueError("voice_direction requires Qwen3-TTS 1.7B; the other models ignore it.")
    for key in ("width", "height"):
        value = project.get(key)
        if type(value) is not int or not 64 <= value <= 1920 or value % 2:
            raise ValueError(f"{key} must be an even integer between 64 and 1920.")
    scenes = project.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 60:
        raise ValueError("Provide between 1 and 60 scenes.")
    identifiers = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Each scene must be an object.")
        identifier = scene.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", identifier):
            raise ValueError("Scene IDs must use 1–40 letters, numbers, underscores, or hyphens.")
        if identifier in identifiers:
            raise ValueError(f"Duplicate scene ID: {identifier}")
        identifiers.add(identifier)
        nonempty(scene.get("narration"), "narration", 5000)
        nonempty(scene.get("image_prompt"), "image_prompt", 4000)
        seed = scene.get("seed")
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise ValueError("Scene seeds must be integers between 0 and 2147483647.")
        references = scene.get("references", [])
        if not isinstance(references, list) or len(references) > 4:
            raise ValueError("Provide at most four reference image paths per scene.")
        for reference in references:
            reference_path(directory, reference)
    return project


def run_command(command, dry_run=False, **kwargs):
    print("$ " + shlex.join(map(str, command)), flush=True)
    if not dry_run:
        subprocess.run(command, check=True, timeout=3600, **kwargs)


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def audio_duration(path):
    info = probe(path)
    if not any(stream["codec_type"] == "audio" for stream in info["streams"]):
        raise ValueError(f"No audio in {path}")
    duration = float(info["format"].get("duration", 0))
    if not math.isfinite(duration) or not 0 < duration <= 600:
        raise ValueError(f"Audio duration must be between 0 and 600 seconds: {path}")
    return duration


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def asset_signature(settings, references=()):
    return hashlib.sha256(json.dumps({
        "settings": settings,
        "requirements": (ROOT / "requirements-media.txt").read_text(),
        "references": [file_hash(path) for path in references],
    }, sort_keys=True).encode()).hexdigest()


def generate_asset(output, settings, references, command, force=False, dry_run=False):
    signature = asset_signature(settings, references)
    metadata_path = output.with_suffix(output.suffix + ".json")
    if output.exists() and metadata_path.exists() and not force:
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("signature") == signature and metadata.get("sha256") == file_hash(output):
            print(f"Unchanged: {output}", flush=True)
            return
    elif output.exists() and not force:
        raise ValueError(f"{output} has no generation record. Use --force to replace it, or assemble it as supplied.")
    if dry_run:
        run_command(command(output), dry_run=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        pending = Path(temporary) / output.name
        started = time.perf_counter()
        run_command(command(pending))
        if not pending.is_file() or pending.stat().st_size == 0:
            raise RuntimeError(f"Generator produced no {output.suffix} file; inspect its output above.")
        if output.suffix == ".wav":
            audio_duration(pending)
        elif not any(stream["codec_type"] == "video" for stream in probe(pending)["streams"]):
            raise ValueError("Image generator produced an invalid image.")
        metadata = {"signature": signature, "sha256": file_hash(pending), "settings": settings,
                    "generation_seconds": time.perf_counter() - started}
        pending_metadata = pending.with_suffix(".json")
        pending_metadata.write_text(json.dumps(metadata, indent=2) + "\n")
        pending.replace(output)
        pending_metadata.replace(metadata_path)


def generate(project, directory, stage, scene_id=None, force=False, dry_run=False, output_directory=None):
    output_directory = output_directory or directory
    selected = [scene for scene in project["scenes"] if scene_id is None or scene["id"] == scene_id]
    if not selected:
        raise ValueError(f"Unknown scene: {scene_id}")
    # shortcut: restart model processes per scene; keep workers alive when loading dominates render time.
    for scene in selected:
        if stage == "narrate":
            model = project.get("speech_model", SPEECH_MODEL)
            references = []
            settings = {"model": model, "text": scene["narration"], "language": project["language"]}
            if model == CHATTERBOX_MODEL:
                if project.get("reference_audio"):
                    references = [reference_path(directory, project["reference_audio"])]
                    settings["reference_audio"] = project["reference_audio"]
                    if not dry_run and not 5 < audio_duration(references[0]) <= 30:
                        raise ValueError("Use a clean reference recording longer than 5 and at most 30 seconds.")
                else:
                    print("Chatterbox: using the checkpoint's default voice; set reference_audio for your own voice.")
            else:
                settings["voice"] = project["voice"]
            if project.get("voice_direction"):
                settings["instruct"] = project["voice_direction"]

            def command(output):
                arguments = [sys.executable, "-m", "mlx_audio.tts.generate", "--model", model,
                        "--text=" + scene["narration"], "--join_audio", "--audio_format", "wav",
                        "--file_prefix", str(output.with_suffix(""))]
                if model == CHATTERBOX_MODEL:
                    arguments += ["--exaggeration", "0", "--lang_code", "en"]
                    if references:
                        arguments += ["--ref_audio", str(references[0])]
                else:
                    arguments += ["--voice", project["voice"], "--lang_code", project["language"]]
                if project.get("voice_direction"):
                    arguments += ["--instruct=" + project["voice_direction"]]
                return arguments

            generate_asset(output_directory / "audio" / (scene["id"] + ".wav"), settings, references, command, force, dry_run)
        else:
            references = [(directory / path).resolve() for path in scene.get("references", [])]
            prompt = project["style"] + "\n" + scene["image_prompt"]
            settings = {"model": IMAGE_MODEL, "prompt": prompt, "seed": scene["seed"],
                        "quantization": 4, "steps": 4, "width": 512, "height": 896}

            def command(output):
                executable = "mflux-generate-flux2-edit" if references else "mflux-generate-flux2"
                arguments = [str(Path(sys.executable).with_name(executable)), "--model", IMAGE_MODEL,
                             "--prompt=" + prompt, "--seed", str(scene["seed"]), "--steps", "4",
                             "-q", "4", "--width", "512", "--height", "896", "--output", str(output)]
                if references:
                    arguments += ["--image-paths", *map(str, references)]
                return arguments

            generate_asset(output_directory / "images" / (scene["id"] + ".png"), settings, references,
                           command, force, dry_run)


def srt_time(milliseconds):
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def ffmpeg(arguments, **kwargs):
    run_command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror", "-y", *arguments], **kwargs)


def prepare_audio(source, output, rate):
    duration = audio_duration(source)
    scan = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(source), "-af",
         "silencedetect=noise=-45dB:d=0.08", "-f", "null", "-"],
        check=True, capture_output=True, text=True, timeout=120,
    )
    events = [(kind, float(value)) for kind, value in
              re.findall(r"silence_(start|end): ([0-9.]+)", scan.stderr)]
    start, end = 0, duration
    # Trim only silence touching a file boundary; retain 40/80 ms around speech.
    if len(events) >= 2 and events[0][0] == "start" and events[0][1] < 0.001:
        start = max(0, events[1][1] - 0.04)
    if len(events) >= 2 and events[-1][0] == "end" and abs(events[-1][1] - duration) < 0.01:
        end = min(duration, events[-2][1] + 0.08)
    if end <= start:
        raise ValueError(f"No audible speech found in {source}")
    filters = f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS"
    if rate != 1:
        filters += f",atempo={rate}"
    ffmpeg(["-i", str(source), "-af", filters, "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output)])
    return audio_duration(output)


def audition(project, directory, scene_id=None, dry_run=False):
    scene_id = scene_id or project["scenes"][0]["id"]
    if not any(scene["id"] == scene_id for scene in project["scenes"]):
        raise ValueError(f"Unknown scene: {scene_id}")
    if dry_run:
        generate(project, directory, "narrate", scene_id, dry_run=True,
                 output_directory=directory / "auditions" / "preview")
        return
    (directory / "auditions").mkdir(exist_ok=True)
    take = Path(tempfile.mkdtemp(prefix=scene_id + "-", dir=directory / "auditions"))
    generate(project, directory, "narrate", scene_id, output_directory=take)
    prepare_audio(take / "audio" / (scene_id + ".wav"), take / "paced.wav", project.get("speech_rate", 1.08))
    ffmpeg(["-i", str(take / "paced.wav"), "-af", LOUDNESS_FILTER,
            "-ar", "48000", "-c:a", "pcm_s16le", str(take / "preview.wav")])
    audio_duration(take / "preview.wav")
    (take / "paced.wav").unlink()
    (take / "audition.json").write_text(json.dumps({"project": project, "scene": scene_id,
        "speech_model": project.get("speech_model", SPEECH_MODEL),
        "speech_rate": project.get("speech_rate", 1.08)}, indent=2) + "\n")
    print(f"Listen to: {take / 'preview.wav'}")


def fit_scene_durations(durations, target, rate):
    if target is None:
        return durations
    total = sum(durations)
    if not 0.75 <= rate * total / target <= 1.35:
        raise ValueError("Fitting target_duration would distort the narration. Adjust the script length or remove the target.")
    total_frames = round(target * FPS)
    elapsed, previous_frame, fitted = 0, 0, []
    for duration in durations:
        elapsed += duration
        end_frame = round(elapsed / total * total_frames)
        if end_frame <= previous_frame:
            raise ValueError("Target duration leaves less than one frame for a scene.")
        fitted.append((end_frame - previous_frame) / FPS)
        previous_frame = end_frame
    return fitted


def assemble(project, directory):
    scenes = project["scenes"]
    raw_durations = []
    for scene in scenes:
        for folder, extension in (("audio", ".wav"), ("images", ".png")):
            path = directory / folder / (scene["id"] + extension)
            if not path.is_file():
                raise ValueError(f"Missing {path}; generate it or supply your own asset first.")
        image = probe(directory / "images" / (scene["id"] + ".png"))
        if not any(stream.get("width", 0) > 0 and stream.get("height", 0) > 0 for stream in image["streams"]):
            raise ValueError(f"Invalid image for scene {scene['id']}")
        raw_durations.append(audio_duration(directory / "audio" / (scene["id"] + ".wav")))
    width, height = project["width"], project["height"]
    with tempfile.TemporaryDirectory(dir=directory, prefix=".render-") as temporary:
        work = Path(temporary)
        rate = project.get("speech_rate", 1.08)
        durations, processed_durations = [], []
        for scene in scenes:
            duration = prepare_audio(directory / "audio" / (scene["id"] + ".wav"),
                                     work / (scene["id"] + ".wav"), rate)
            processed_durations.append(duration)
            durations.append(math.ceil(duration * FPS) / FPS)
        target = project.get("target_duration")
        durations = fit_scene_durations(durations, target, rate)
        captions, elapsed, concat = [], 0, []
        for index, (scene, duration) in enumerate(zip(scenes, durations), 1):
            frames = round(duration * FPS)
            fade = min(0.2, duration / 4)
            filters = (
                f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2},"
                f"zoompan=z='1+0.04*on/{max(frames - 1, 1)}':x='iw/2-iw/zoom/2':"
                f"y='ih/2-ih/zoom/2':d={frames}:s={width}x{height}:fps={FPS}"
            )
            if index == 1:
                filters += f",fade=t=in:d={fade}"
            if index == len(scenes):
                filters += f",fade=t=out:st={duration - fade}:d={fade}"
            filters += ",format=yuv420p"
            audio_filter = "apad"
            if target is not None:
                audio_filter = f"atempo={processed_durations[index - 1] / duration},apad"
            ffmpeg(["-loop", "1", "-i", str(directory / "images" / (scene["id"] + ".png")),
                    "-i", str(work / (scene["id"] + ".wav")),
                    "-vf", filters, "-af", audio_filter, "-t", str(duration), "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "pcm_s16le",
                    "-ar", "48000", "-ac", "2", str(work / (scene["id"] + ".mov"))])
            concat.append(f"file '{scene['id']}.mov'")
            end = elapsed + duration
            text = textwrap.fill(" ".join(scene["narration"].split()), width=42)
            captions.append(f"{index}\n{srt_time(round(elapsed * 1000))} --> {srt_time(round(end * 1000))}\n{text}\n")
            elapsed = end
        (work / "concat.txt").write_text("\n".join(concat) + "\n")
        (work / "captions.srt").write_text("\n".join(captions))
        ffmpeg(["-f", "concat", "-safe", "1", "-i", "concat.txt", "-i", "captions.srt",
                "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0", "-c:v", "copy", "-c:a", "aac",
                "-af", LOUDNESS_FILTER, "-ar", "48000", "-c:s", "mov_text",
                "-disposition:s:0", "default", "-movflags", "+faststart", "final.mp4"], cwd=work)
        ffmpeg(["-f", "concat", "-safe", "1", "-i", "concat.txt", "-vn", "-af", LOUDNESS_FILTER,
                "-ar", "48000", "-c:a", "pcm_s16le", "narration.wav"], cwd=work)
        info = probe(work / "final.mp4")
        report = {"duration_seconds": float(info["format"]["duration"]), "width": width,
                  "height": height, "fps": FPS, "project": project, "speech_rate": rate,
                  "scenes": [{"id": scene["id"], "duration_seconds": duration,
                              "source_audio_seconds": raw_duration,
                              "audio_sha256": file_hash(directory / "audio" / (scene["id"] + ".wav")),
                              "image_sha256": file_hash(directory / "images" / (scene["id"] + ".png"))}
                             for scene, duration, raw_duration in zip(scenes, durations, raw_durations)]}
        (work / "render.json").write_text(json.dumps(report, indent=2) + "\n")
        for name in ("final.mp4", "narration.wav", "captions.srt", "render.json"):
            (work / name).replace(directory / name)
    print(f"Video ready: {directory / 'final.mp4'} ({report['duration_seconds']:.1f}s)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "audition", "narrate", "images", "assemble", "build"))
    parser.add_argument("project", type=Path, help="Project directory")
    parser.add_argument("--script", type=Path, help="For init: split a script into scenes at blank lines")
    parser.add_argument("--scene", help="Select one scene (audition/narrate/images)")
    parser.add_argument("--force", action="store_true", help="Regenerate selected assets, including supplied files")
    parser.add_argument("--dry-run", action="store_true", help="Print generation commands without loading models")
    args = parser.parse_args(argv)
    directory = args.project.resolve()
    try:
        if args.script and args.command != "init":
            raise ValueError("Use --script with init only.")
        if args.scene and args.command not in ("audition", "narrate", "images"):
            raise ValueError("Use --scene with audition, narrate, or images.")
        if args.dry_run and args.command not in ("audition", "narrate", "images", "build"):
            raise ValueError("Use --dry-run with audition, narrate, images, or build.")
        if args.command == "init":
            project = json.loads((ROOT / "examples" / "story.json").read_text())
            if args.script:
                paragraphs = [part.strip() for part in re.split(r"\n\s*\n", args.script.read_text()) if part.strip()]
                if not 1 <= len(paragraphs) <= 60:
                    raise ValueError("Provide between 1 and 60 paragraphs, one per scene.")
                for paragraph in paragraphs:
                    nonempty(paragraph, "script paragraph", 4000)
                project["title"] = args.script.stem
                project["scenes"] = [{"id": f"{i:02}", "narration": text, "image_prompt": text,
                                      "seed": 41 + i, "references": []}
                                     for i, text in enumerate(paragraphs, 1)]
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "project.json").open("x") as target:
                target.write(json.dumps(project, indent=2) + "\n")
            print(f"Created {directory / 'project.json'}. Edit the narration, image prompts, and references.")
            return 0
        project = load_project(directory)
        if not args.dry_run and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            raise ValueError("Install FFmpeg first: brew install ffmpeg")
        if args.command == "audition":
            audition(project, directory, args.scene, args.dry_run)
            return 0
        if args.command in ("narrate", "images", "build"):
            stages = ("narrate", "images") if args.command == "build" else (args.command,)
            for stage in stages:
                generate(project, directory, stage, args.scene, args.force, args.dry_run)
        if args.command in ("assemble", "build") and not args.dry_run:
            assemble(project, directory)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Studio failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
