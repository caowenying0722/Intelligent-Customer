from __future__ import annotations

import re
from itertools import pairwise


def cjk_bm25_tokenizer(text: str) -> list[str]:
    tokens: list[str] = []
    normalized = re.sub(r"\s+", "", text.lower())

    ascii_words = re.findall(r"[a-z0-9]+", normalized)
    tokens.extend(ascii_words)

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    tokens.extend(cjk_chars)
    tokens.extend("".join(pair) for pair in pairwise(cjk_chars))

    return tokens
