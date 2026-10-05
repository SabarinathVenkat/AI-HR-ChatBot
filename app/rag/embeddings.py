"""Text embedding. A small local model, so no extra API key or network call at query time."""
from pathlib import Path
from typing import Protocol

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """BGE-small via fastembed (ONNX, no torch). The model is loaded on first use."""

    def __init__(self, cache_dir: str | Path = "models_cache") -> None:
        self._cache_dir = str(cache_dir)
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(MODEL_NAME, cache_dir=self._cache_dir)
        return [[float(x) for x in vector] for vector in self._model.embed(texts)]
