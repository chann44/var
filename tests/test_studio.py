import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
import zlib

import studio


def png_bytes(color=(40, 100, 180)):
    width, height = 64, 96

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    pixels = b"".join(b"\0" + bytes(color) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def write_wav(path, seconds):
    import math

    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 24000)))
                                   for i in range(round(seconds * 24000))))


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "project's scenes"
        self.directory.mkdir()
        self.project = json.loads((studio.ROOT / "examples" / "story.json").read_text())
        self.project.update(width=160, height=96, speech_rate=1.0)
        self.project["scenes"] = self.project["scenes"][:2]
        self.save()

    def save(self):
        (self.directory / "project.json").write_text(json.dumps(self.project))

    def test_script_initialization_preserves_existing_projects(self):
        script = Path(self.temporary.name) / "my script.txt"
        script.write_text("First scene.\n\nSecond scene.")
        destination = Path(self.temporary.name) / "new"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(["init", str(destination), "--script", str(script)]), 0)
        project = studio.load_project(destination)
        self.assertEqual([scene["narration"] for scene in project["scenes"]], ["First scene.", "Second scene."])
        previous = (destination / "project.json").read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(studio.main(["init", str(destination)]), 1)
        self.assertEqual((destination / "project.json").read_bytes(), previous)
        script.write_text("  ")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(studio.main(["init", str(destination / "empty"), "--script", str(script)]), 1)
        self.assertFalse((destination / "empty").exists())

    def test_invalid_manifests_and_escaping_reference_paths(self):
        for change in (
            {"width": True}, {"height": 99}, {"scenes": []}, {"voice": ""},
            {"scenes": ["not an object"]}, {"scenes": [self.project["scenes"][0]] * 2},
            {"speech_rate": True}, {"speech_rate": 0}, {"speech_rate": float("nan")},
            {"target_duration": True}, {"target_duration": 0}, {"target_duration": float("inf")},
            {"speech_model": "unknown"}, {"voice_direction": "Read excitedly"},
            {"speech_model": studio.CHATTERBOX_MODEL, "language": "Hindi"},
            {"reference_audio": "reference.wav"},
        ):
            with self.subTest(change=change):
                invalid = self.project | change
                (self.directory / "project.json").write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    studio.load_project(self.directory)
        for reference in ("../outside.png", str(self.directory / "absolute.png"), "missing.png"):
            project = copy.deepcopy(self.project)
            project["scenes"][0]["references"] = [reference]
            (self.directory / "project.json").write_text(json.dumps(project))
            with self.assertRaises(ValueError):
                studio.load_project(self.directory)
        for identifier in ("../escape", "a/b", "unsafe'", ""):
            project = copy.deepcopy(self.project)
            project["scenes"][0]["id"] = identifier
            (self.directory / "project.json").write_text(json.dumps(project))
            with self.assertRaises(ValueError):
                studio.load_project(self.directory)

    def test_dry_run_targets_one_scene_and_passes_references_without_a_shell(self):
        reference = self.directory / "reference ' photo.png"
        reference.write_bytes(png_bytes())
        self.project["scenes"][1]["references"] = [reference.name]
        self.project["scenes"][1]["image_prompt"] = "A scene; $(this is only text)"
        commands = []
        with patch.object(studio, "run_command", side_effect=lambda command, **_: commands.append(command)):
            studio.generate(self.project, self.directory, "images", "02", dry_run=True)
            studio.generate(self.project, self.directory, "narrate", "02", dry_run=True)
        self.assertEqual(len(commands), 2)
        image, speech = commands
        self.assertTrue(image[0].endswith("mflux-generate-flux2-edit"))
        self.assertIn(str(reference.resolve()), image)
        self.assertIn("--prompt=" + self.project["style"] + "\n" + self.project["scenes"][1]["image_prompt"], image)
        self.assertIn("--join_audio", speech)
        self.assertIn("--text=" + self.project["scenes"][1]["narration"], speech)
        self.assertFalse((self.directory / "images").exists())
        with self.assertRaises(ValueError):
            studio.generate(self.project, self.directory, "images", "missing", dry_run=True)

    def test_expressive_voice_uses_supported_direction_and_invalidates_only_audio(self):
        self.project.update(speech_model=studio.EXPRESSIVE_SPEECH_MODEL,
                            voice_direction="Conversational, brisk, natural emphasis.")
        self.save()
        project = studio.load_project(self.directory)
        commands = []
        settings = []
        with patch.object(studio, "generate_asset", side_effect=lambda output, config, refs, command, *args:
                          (commands.append(command(output)), settings.append(config))):
            studio.generate(project, self.directory, "narrate", "01", dry_run=True)
        self.assertIn(studio.EXPRESSIVE_SPEECH_MODEL, commands[0])
        self.assertIn("--instruct=" + project["voice_direction"], commands[0])
        self.assertNotIn("--speed", commands[0], "Qwen3's speed argument is ignored; use post-processing")
        self.assertEqual(settings[0]["instruct"], project["voice_direction"])
        self.assertNotIn("speech_rate", settings[0], "Pacing changes should reuse raw narration")

    def test_chatterbox_reference_voice_routing_and_cache_inputs(self):
        reference = self.directory / "reference voice.wav"
        write_wav(reference, 0.2)
        self.project.update(speech_model=studio.CHATTERBOX_MODEL, reference_audio=reference.name)
        self.save()
        project = studio.load_project(self.directory)
        captures = []

        def capture(output, settings, references, command, *args):
            captures.append((command(output), settings, studio.asset_signature(settings, references)))

        with patch.object(studio, "generate_asset", side_effect=capture):
            studio.generate(project, self.directory, "narrate", "01", dry_run=True)
            write_wav(reference, 0.3)
            studio.generate(project, self.directory, "narrate", "01", dry_run=True)
        command, settings, signature = captures[0]
        self.assertIn(studio.CHATTERBOX_MODEL, command)
        self.assertIn(str(reference.resolve()), command)
        self.assertNotIn("--voice", command)
        self.assertNotIn("--instruct", command)
        self.assertNotIn("voice", settings)
        self.assertEqual(command[command.index("--exaggeration") + 1], "0")
        self.assertNotEqual(signature, captures[1][2], "Replacing a voice reference must invalidate cached speech")
        with self.assertRaisesRegex(ValueError, "longer than 5"):
            studio.generate(project, self.directory, "narrate", "01")

    def test_chatterbox_can_audition_the_checkpoint_voice_without_a_reference(self):
        self.project["speech_model"] = studio.CHATTERBOX_MODEL
        self.save()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(studio.main(["audition", str(self.directory), "--dry-run"]), 0)
        self.assertIn(studio.CHATTERBOX_MODEL, output.getvalue())
        self.assertNotIn("--ref_audio", output.getvalue())
        self.assertFalse((self.directory / "auditions").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_auditions_are_normalized_and_keep_approved_audio_intact(self):
        (self.directory / "audio").mkdir()
        approved = self.directory / "audio" / "01.wav"
        approved.write_bytes(b"approved audio must survive auditions")

        def synthesize(project, directory, stage, scene_id, output_directory):
            self.assertEqual(stage, "narrate")
            target = output_directory / "audio"
            target.mkdir()
            write_wav(target / (scene_id + ".wav"), 0.8)

        with patch.object(studio, "generate", side_effect=synthesize), contextlib.redirect_stdout(io.StringIO()):
            studio.audition(self.project, self.directory)
            studio.audition(self.project, self.directory)
        takes = list((self.directory / "auditions").iterdir())
        self.assertEqual(len(takes), 2)
        self.assertEqual(approved.read_bytes(), b"approved audio must survive auditions")
        for take in takes:
            self.assertGreater(studio.audio_duration(take / "preview.wav"), 0.5)
            report = json.loads((take / "audition.json").read_text())
            self.assertEqual(report["scene"], "01")
            self.assertFalse((take / "paced.wav").exists())

    def test_reference_content_invalidates_the_signature(self):
        reference = self.directory / "reference.png"
        reference.write_bytes(png_bytes())
        previous = studio.asset_signature({"seed": 42}, [reference])
        reference.write_bytes(png_bytes((220, 10, 10)))
        self.assertNotEqual(previous, studio.asset_signature({"seed": 42}, [reference]))

    def test_target_duration_keeps_frame_boundaries_and_rejects_extreme_stretching(self):
        durations = studio.fit_scene_durations([3, 4, 2], 10, 1.08)
        self.assertEqual(sum(durations), 10)
        self.assertTrue(all(abs(duration * studio.FPS - round(duration * studio.FPS)) < 0.001 for duration in durations))
        with self.assertRaisesRegex(ValueError, "distort"):
            studio.fit_scene_durations([1, 1], 60, 1.08)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_cached_assets_and_failed_regeneration_preserve_previous_output(self):
        output = self.directory / "image.png"

        def command(path):
            return [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))",
                    str(path), png_bytes().hex()]

        with contextlib.redirect_stdout(io.StringIO()):
            studio.generate_asset(output, {"seed": 42}, (), command)
            original = output.read_bytes()
            metadata = output.with_suffix(".png.json").read_bytes()
            with patch.object(studio, "run_command", side_effect=AssertionError("Unchanged assets must be reused")):
                studio.generate_asset(output, {"seed": 42}, (), command)
            with self.assertRaises(subprocess.CalledProcessError):
                studio.generate_asset(output, {"seed": 43}, (),
                                      lambda path: [sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(output.with_suffix(".png.json").read_bytes(), metadata)
            with self.assertRaises(RuntimeError):
                studio.generate_asset(output, {"seed": 43}, (), lambda path: [sys.executable, "-c", "pass"])
            self.assertEqual(output.read_bytes(), original)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_scene_edge_silence_is_removed_without_changing_source_audio(self):
        (self.directory / "images").mkdir()
        (self.directory / "audio").mkdir()
        original_hashes = []
        for scene in self.project["scenes"]:
            (self.directory / "images" / (scene["id"] + ".png")).write_bytes(png_bytes())
            path = self.directory / "audio" / (scene["id"] + ".wav")
            write_wav(path, 0.5)
            with wave.open(str(path), "rb") as source:
                samples = source.readframes(source.getnframes())
            with wave.open(str(path), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(24000)
                target.writeframes(b"\0\0" * 12000 + samples + b"\0\0" * 9600)
            original_hashes.append(studio.file_hash(path))
        self.project["speech_rate"] = 1.12
        with contextlib.redirect_stdout(io.StringIO()):
            studio.assemble(self.project, self.directory)
        duration = studio.audio_duration(self.directory / "narration.wav")
        self.assertLess(duration, 1.5, "Scene joins must not retain a second of dead air each")
        self.assertGreater(duration, 0.85, "Spoken content must be retained")
        with wave.open(str(self.directory / "narration.wav"), "rb") as source:
            source.setpos(round(0.15 * source.getframerate()))
            frames = source.readframes(round(0.2 * source.getframerate()))
            samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)[::source.getnchannels()]
            crossings = sum((left >= 0) != (right >= 0) for left, right in zip(samples, samples[1:]))
            self.assertAlmostEqual(crossings / 0.4, 440, delta=15, msg="Tempo changes must preserve pitch")
        for scene, previous in zip(self.project["scenes"], original_hashes):
            self.assertEqual(studio.file_hash(self.directory / "audio" / (scene["id"] + ".wav")), previous)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_processing_preserves_internal_pauses_and_rejects_silent_audio(self):
        source = self.directory / "speech.wav"
        output = self.directory / "processed.wav"
        write_wav(source, 0.3)
        with wave.open(str(source), "rb") as wave_file:
            samples = wave_file.readframes(wave_file.getnframes())
        with wave.open(str(source), "wb") as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(24000)
            wave_file.writeframes(samples + b"\0\0" * 9600 + samples)
        with contextlib.redirect_stdout(io.StringIO()):
            duration = studio.prepare_audio(source, output, 1.0)
        self.assertAlmostEqual(duration, 1.0, delta=0.01)
        with wave.open(str(output), "rb") as wave_file:
            wave_file.setpos(round(0.4 * wave_file.getframerate()))
            self.assertEqual(set(wave_file.readframes(round(0.2 * wave_file.getframerate()))), {0})
        with wave.open(str(source), "wb") as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(24000)
            wave_file.writeframes(b"\0\0" * 24000)
        with self.assertRaisesRegex(ValueError, "No audible speech"):
            studio.prepare_audio(source, output, 1.0)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_real_video_has_ordered_scenes_audio_and_captions(self):
        (self.directory / "images").mkdir()
        (self.directory / "audio").mkdir()
        for scene, color, seconds in zip(self.project["scenes"], ((220, 20, 20), (20, 20, 220)), (0.4, 0.6)):
            (self.directory / "images" / (scene["id"] + ".png")).write_bytes(png_bytes(color))
            write_wav(self.directory / "audio" / (scene["id"] + ".wav"), seconds)
        with contextlib.redirect_stdout(io.StringIO()):
            studio.assemble(self.project, self.directory)
        info = studio.probe(self.directory / "final.mp4")
        streams = {stream["codec_type"]: stream for stream in info["streams"]}
        self.assertEqual(streams["video"]["width"], 160)
        self.assertEqual(streams["video"]["height"], 96)
        self.assertEqual(streams["audio"]["codec_name"], "aac")
        self.assertEqual(streams["subtitle"]["codec_name"], "mov_text")
        self.assertAlmostEqual(float(info["format"]["duration"]), 1.05, delta=0.15)
        self.assertIn("00:00:00,417 --> 00:00:01,042", (self.directory / "captions.srt").read_text())
        report = json.loads((self.directory / "render.json").read_text())
        self.assertEqual([scene["id"] for scene in report["scenes"]], ["01", "02"])
        for moment, color in ((0.34, 0), (0.75, 2)):
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(moment), "-i", str(self.directory / "final.mp4"),
                                     "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                    check=True, capture_output=True, timeout=30)
            self.assertGreater(result.stdout[color], result.stdout[2 - color] + 50)
            self.assertGreater(result.stdout[color], 150, "Middle scene boundaries should not fade to black")
        self.assertGreater(studio.audio_duration(self.directory / "narration.wav"), 1)
        self.project["target_duration"] = 1.125
        with contextlib.redirect_stdout(io.StringIO()):
            studio.assemble(self.project, self.directory)
        info = studio.probe(self.directory / "final.mp4")
        self.assertAlmostEqual(float(info["format"]["duration"]), 1.125, delta=1 / studio.FPS)
        self.assertIn("00:00:01,125", (self.directory / "captions.srt").read_text())
        previous = (self.directory / "final.mp4").read_bytes()
        (self.directory / "images" / "02.png").write_bytes(b"broken image")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises((ValueError, subprocess.CalledProcessError)):
            studio.assemble(self.project, self.directory)
        self.assertEqual((self.directory / "final.mp4").read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
