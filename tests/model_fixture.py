def make_tokenizer():
    from tokenizers.pre_tokenizers import ByteLevel
    from transformers import Qwen2Tokenizer

    # AutoTokenizer selects Qwen2 from config.json, so save its native BPE format.
    vocab = {token: index for index, token in enumerate(sorted(ByteLevel.alphabet()))}
    vocab["[EOS]"] = len(vocab)
    tokenizer = Qwen2Tokenizer(vocab=vocab, merges=[], unk_token="[EOS]",
                               eos_token="[EOS]", pad_token="[EOS]")
    tokenizer.chat_template = "{{ messages[0]['content'] }}"
    return tokenizer
