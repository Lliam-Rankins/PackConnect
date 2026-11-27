"""Deterministic offline embedder for tests (implements matching.embedder.Embedder)."""

import hashlib
import math
import re

DIMENSIONS = 384
_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


class FakeEmbedder:
    model_name = "fake-hash-384"
    dimensions = DIMENSIONS

    def __init__(self, aliases=None, fail=False):
        self.aliases = {k.lower(): v.lower() for k, v in (aliases or {}).items()}
        self.fail = fail
        self.passage_calls = 0
        self.query_calls = 0

    @property
    def calls(self) -> int:
        return self.passage_calls + self.query_calls

    @staticmethod
    def _bucket(feature: str):
        digest = hashlib.md5(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return index, sign

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * DIMENSIONS
        for raw in _TOKEN.findall(text.lower()):
            canonical = self.aliases.get(raw, raw)
            for feature, weight in ((canonical, 1.0), (_stem(canonical), 0.5)):
                index, sign = self._bucket(feature)
                vec[index] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm else vec

    def _embed(self, texts):
        if self.fail:
            raise RuntimeError("FakeEmbedder configured to fail")
        return [self._embed_one(t) for t in texts]

    def embed_passages(self, texts):
        self.passage_calls += 1
        return self._embed(texts)

    def embed_queries(self, texts):
        self.query_calls += 1
        return self._embed(texts)
