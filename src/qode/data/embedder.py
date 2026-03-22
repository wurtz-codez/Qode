"""all-MiniLM-L6-v2 embedding engine (local, CPU inference).

Ported from GitNexus ``embeddings/`` (~500 lines → Python).
Produces 384-dimensional vectors stored in KuzuDB's native HNSW index.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from contextlib import suppress
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL_ID = "all-MiniLM-L6-v2"
EMBEDDING_DIMS = 384
DEFAULT_BATCH_SIZE = 32

_embedder_instance: Optional[Any] = None
_embedder_lock = threading.Lock()


def _create_model(model_id: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id)


def _iter_batches(items: Sequence[str], batch_size: int) -> Iterable[list[str]]:
    if batch_size <= 0:
        batch_size = DEFAULT_BATCH_SIZE
    for start in range(0, len(items), batch_size):
        yield list(items[start : start + batch_size])


def _normalize_vectors(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    try:
        import numpy as np
    except ModuleNotFoundError:
        normalized: list[list[float]] = []
        for vector in vectors:
            norm = sum(v * v for v in vector) ** 0.5
            if norm == 0:
                normalized.append([float(v) for v in vector])
            else:
                normalized.append([float(v) / norm for v in vector])
        return normalized

    if not vectors:
        return []
    array = np.asarray(vectors, dtype=float)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    array = array / norms
    return array.tolist()


def _coerce_vectors(raw: Any) -> list[list[float]]:
    if raw is None:
        return []
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if isinstance(raw, list) and raw and isinstance(raw[0], (int, float)):
        return [[float(v) for v in raw]]
    return [[float(v) for v in row] for row in list(raw)]


def _ensure_vector_dims(vectors: Sequence[Sequence[float]]) -> None:
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMS:
            raise ValueError(
                f"Expected {EMBEDDING_DIMS}-dim embeddings, got {len(vector)}"
            )


def init_embedder(model_id: str = MODEL_ID) -> Any:
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    with _embedder_lock:
        if _embedder_instance is not None:
            return _embedder_instance
        logger.info("Loading embedding model: %s", model_id)
        _embedder_instance = _create_model(model_id)
        return _embedder_instance


def is_embedder_ready() -> bool:
    return _embedder_instance is not None


def embed_texts(
    texts: Sequence[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    normalize: bool = True,
) -> list[list[float]]:
    if not texts:
        return []

    model = init_embedder()
    all_vectors: list[list[float]] = []

    for batch in _iter_batches(texts, batch_size):
        encode_kwargs = {
            "batch_size": batch_size,
            "show_progress_bar": False,
            "convert_to_numpy": True,
            "normalize_embeddings": normalize,
        }
        try:
            encoded = model.encode(batch, **encode_kwargs)
        except TypeError:
            encode_kwargs.pop("normalize_embeddings", None)
            encoded = model.encode(batch, **encode_kwargs)

        batch_vectors = _coerce_vectors(encoded)
        all_vectors.extend(batch_vectors)

    if normalize:
        all_vectors = _normalize_vectors(all_vectors)

    _ensure_vector_dims(all_vectors)
    return all_vectors


def embed_query(query: str) -> list[float]:
    vectors = embed_texts([query], batch_size=1, normalize=True)
    return vectors[0] if vectors else []


def get_embedding_dims() -> int:
    return EMBEDDING_DIMS


def dispose_embedder() -> None:
    global _embedder_instance
    if _embedder_instance is None:
        return

    model = _embedder_instance
    _embedder_instance = None

    with suppress(Exception):
        cpu = getattr(model, "cpu", None)
        if callable(cpu):
            cpu()
    with suppress(Exception):
        to_fn = getattr(model, "to", None)
        if callable(to_fn):
            to_fn("cpu")
    with suppress(Exception):
        import torch

        torch.cuda.empty_cache()


initEmbedder = init_embedder  # noqa: N816
isEmbedderReady = is_embedder_ready  # noqa: N816
embedTexts = embed_texts  # noqa: N816
embedQuery = embed_query  # noqa: N816
getEmbeddingDims = get_embedding_dims  # noqa: N816
disposeEmbedder = dispose_embedder  # noqa: N816
