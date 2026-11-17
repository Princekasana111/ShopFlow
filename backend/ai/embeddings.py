"""Text embeddings.

* `FastEmbedEmbedder` runs BAAI/bge-small-en-v1.5 (384-d) locally through ONNX Runtime.
  Free, no API key, ~130 MB model download on first use (cached on disk).
* `HashEmbedder` is a deterministic hashing-trick embedder (word unigrams + character
  trigrams). It needs no download, so the test suite and CI use it.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from functools import lru_cache
from typing import Protocol

from django.conf import settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: str, dim: int, query_prefix: str = ""):
        from fastembed import TextEmbedding

        self.name = model_name
        self.dim = dim
        self.query_prefix = query_prefix
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._lock = threading.Lock()  # ONNX sessions are shared across request threads

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            vectors = [v.tolist() for v in self._model.embed(texts, batch_size=64)]
        self._check_dim(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            vector = next(iter(self._model.query_embed(self.query_prefix + text))).tolist()
        self._check_dim([vector])
        return vector

    def _check_dim(self, vectors: list[list[float]]) -> None:
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"Embedding model {self.name} returned {len(vectors[0])} dimensions; "
                f"the database column expects {self.dim}."
            )


_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    name = "hash-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        tokens = _TOKEN_RE.findall(text.lower())
        features = [f"w:{t}" for t in tokens]
        for token in tokens:
            padded = f"#{token}#"
            features.extend(f"c:{padded[i:i + 3]}" for i in range(len(padded) - 2))
        return features

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature in self._features(text):
            digest = hashlib.md5(feature.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            weight = 1.0 if feature.startswith("w:") else 0.5
            vector[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    cfg = settings.AI
    if cfg["EMBEDDING_PROVIDER"] == "hash":
        return HashEmbedder(dim=cfg["EMBEDDING_DIM"])
    if cfg["EMBEDDING_PROVIDER"] == "fastembed":
        return FastEmbedEmbedder(
            model_name=cfg["EMBEDDING_MODEL"],
            cache_dir=cfg["FASTEMBED_CACHE_DIR"],
            dim=cfg["EMBEDDING_DIM"],
            query_prefix=cfg["EMBEDDING_QUERY_PREFIX"],
        )
    raise ValueError(f"Unknown EMBEDDING_PROVIDER {cfg['EMBEDDING_PROVIDER']!r}")


@lru_cache(maxsize=2048)
def _cached_query_embedding(embedder_name: str, text: str) -> tuple[float, ...]:
    return tuple(get_embedder().embed_query(text))


def embed_query(text: str) -> list[float]:
    """Query embeddings are cached in-process: repeated searches skip the model entirely."""
    embedder = get_embedder()
    return list(_cached_query_embedding(embedder.name, text.strip().lower()))


def content_hash(text: str, model_name: str) -> str:
    return hashlib.sha256(f"{model_name}\n{text}".encode()).hexdigest()
