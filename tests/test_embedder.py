"""Tests for embedding pipeline utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from qode.data import embedder


def test_embed_texts_normalizes_and_shapes(monkeypatch):
    fake_model = MagicMock()
    fake_model.encode.return_value = [[1.0] * embedder.EMBEDDING_DIMS]

    monkeypatch.setattr(embedder, "_create_model", lambda _model_id: fake_model)
    monkeypatch.setattr(embedder, "_embedder_instance", None)

    vectors = embedder.embed_texts(["hello"], batch_size=1, normalize=True)

    assert len(vectors) == 1
    assert len(vectors[0]) == embedder.EMBEDDING_DIMS
    assert abs(sum(v * v for v in vectors[0]) - 1.0) < 1e-6


def test_embed_texts_rejects_wrong_dims(monkeypatch):
    fake_model = MagicMock()
    fake_model.encode.return_value = [[0.0] * (embedder.EMBEDDING_DIMS - 1)]

    monkeypatch.setattr(embedder, "_create_model", lambda _model_id: fake_model)
    monkeypatch.setattr(embedder, "_embedder_instance", None)

    with pytest.raises(ValueError):
        embedder.embed_texts(["oops"], batch_size=1, normalize=False)
