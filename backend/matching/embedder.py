"""Text embedding interface and the local fastembed implementation."""

import math
import os
import threading
from typing import Protocol, Sequence

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIMENSIONS = 384


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """fastembed-backed embedder; the model loads lazily on first use."""

    def __init__(self, model_name=DEFAULT_MODEL, cache_dir=None, dimensions=DEFAULT_DIMENSIONS):
        self.model_name = model_name
        self.dimensions = dimensions
        self.cache_dir = cache_dir or os.environ.get("FASTEMBED_CACHE_PATH") or None
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    kwargs = {"cache_dir": self.cache_dir} if self.cache_dir else {}
                    self._model = TextEmbedding(model_name=self.model_name, **kwargs)
        return self._model

    @staticmethod
    def _as_lists(vectors) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in vectors]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._as_lists(self._get_model().passage_embed(list(texts)))

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._as_lists(self._get_model().query_embed(list(texts)))


def vector_literal(vec: Sequence[float], dimensions: int = DEFAULT_DIMENSIONS) -> str:
    """Format a vector for a pgvector `::vector` cast, e.g. '[0.1,0.2]'."""
    values = [float(x) for x in vec]
    if len(values) != dimensions:
        raise ValueError(f"expected {dimensions} dimensions, got {len(values)}")
    if not all(math.isfinite(x) for x in values):
        raise ValueError("vector contains non-finite values")
    return "[" + ",".join(repr(x) for x in values) + "]"
