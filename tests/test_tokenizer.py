import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from model_fixture import make_tokenizer


@unittest.skipUnless(importlib.util.find_spec("transformers") is not None,
                     "Install requirements.txt for tokenizer tests.")
class TokenizerTests(unittest.TestCase):
    def test_saved_qwen_fixture_preserves_prompt_tokens(self):
        from transformers import AutoTokenizer

        tokenizer = make_tokenizer()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "config.json").write_text(json.dumps({"model_type": "qwen2"}))
            tokenizer.save_pretrained(path)
            reloaded = AutoTokenizer.from_pretrained(path, local_files_only=True)
            tokens = reloaded.apply_chat_template(
                [{"role": "user", "content": "hello world"}],
                tokenize=True, add_generation_prompt=True, return_dict=False,
            )
            self.assertEqual(tokens, tokenizer.encode("hello world"))
            self.assertTrue(tokens)
            self.assertEqual(reloaded.decode(tokens), "hello world")


if __name__ == "__main__":
    unittest.main()
