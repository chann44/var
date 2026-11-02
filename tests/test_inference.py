"""Real MLX integration tests; no model download, skipped when dependencies are absent."""

import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

from model_fixture import make_tokenizer


ROOT = Path(__file__).resolve().parents[1]
HAS_MLX = importlib.util.find_spec("mlx") is not None and importlib.util.find_spec("mlx_lm") is not None


@unittest.skipUnless(HAS_MLX, "Install requirements.txt on an Apple silicon Mac for inference tests.")
class InferenceTests(unittest.TestCase):
    def test_two_and_three_ranks_match_a_single_model(self):
        try:
            import mlx.core as mx
        except ImportError as error:
            if "No Metal device available" in str(error):
                self.skipTest("This session cannot access a Metal GPU.")
            raise
        from mlx.utils import tree_flatten
        from mlx_lm.models.qwen2 import Model, ModelArgs

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            tokenizer = make_tokenizer()
            config = dict(model_type="qwen2", hidden_size=32, num_hidden_layers=7,
                          intermediate_size=64, num_attention_heads=4, num_key_value_heads=2,
                          rms_norm_eps=1e-6, vocab_size=len(tokenizer), tie_word_embeddings=False)
            mx.random.seed(0)
            model = Model(ModelArgs.from_dict(config))
            model.lm_head.weight = model.lm_head.weight.at[tokenizer.eos_token_id].multiply(0)
            mx.save_safetensors(str(path / "model.safetensors"), dict(tree_flatten(model.parameters())))
            (path / "config.json").write_text(json.dumps(config))
            tokenizer.save_pretrained(path)
            base = [sys.executable, str(ROOT / "engine.py"), "--timeout", "90"]
            prompt = ["--model", str(path), "--prompt", "hello world", "--max-tokens", "4"]
            baseline_path = path / "baseline.json"
            baseline = subprocess.run(base + prompt + ["--report", str(baseline_path)],
                                      capture_output=True, text=True, timeout=100)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            expected = json.loads(baseline_path.read_text())
            self.assertGreater(len(expected["generated_token_ids"]), 1)

            for size in (2, 3):
                with self.subTest(size=size):
                    sockets = [socket.socket() for _ in range(size)]
                    try:
                        for sock in sockets:
                            sock.bind(("127.0.0.1", 0))
                        hosts = [[f"127.0.0.1:{sock.getsockname()[1]}"] for sock in sockets]
                    finally:
                        for sock in sockets:
                            sock.close()
                    hostfile = path / "hosts.json"
                    hostfile.write_text(json.dumps(hosts))
                    processes = []
                    try:
                        for rank in range(size):
                            command = base + ["--hosts", str(hostfile), "--rank", str(rank),
                                              "--report", str(path / f"rank{rank}.json")]
                            if rank == 0:
                                command += prompt
                            processes.append(subprocess.Popen(command, stdout=subprocess.PIPE,
                                                              stderr=subprocess.PIPE, text=True,
                                                              start_new_session=True))
                        for process in processes:
                            _, stderr = process.communicate(timeout=100)
                            self.assertEqual(process.returncode, 0, stderr)
                    finally:
                        for process in processes:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.communicate()
                    shards = [json.loads((path / f"rank{r}.json").read_text()) for r in range(size)]
                    self.assertEqual(sorted(i for shard in shards for i in shard["layers"]), list(range(7)))
                    for shard in shards:
                        self.assertEqual(shard["world_size"], size)
                        self.assertLess(shard["weight_bytes"], expected["weight_bytes"])
                        self.assertEqual(shard["generated_token_ids"], expected["generated_token_ids"])


if __name__ == "__main__":
    unittest.main()
