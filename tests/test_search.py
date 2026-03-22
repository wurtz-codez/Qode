"""Tests for BM25, semantic, and hybrid search."""

from __future__ import annotations

import pytest

from qode.core.search import bm25, hybrid


@pytest.mark.asyncio
async def test_bm25_bootstrap_once_and_deterministic_order(monkeypatch) -> None:
    create_calls: list[tuple[str, str, list[str], str]] = []
    query_calls: list[tuple[str, str, str, int, bool]] = []

    async def fake_create_fts_index(
        table_name: str,
        index_name: str,
        properties: list[str],
        stemmer: str = "porter",
    ) -> None:
        create_calls.append((table_name, index_name, properties, stemmer))

    async def fake_query_fts(
        table_name: str,
        index_name: str,
        query_text: str,
        limit: int = 20,
        *,
        conjunctive: bool = False,
    ) -> list[dict[str, object]]:
        query_calls.append((table_name, index_name, query_text, limit, conjunctive))
        return [
            {"nodeId": "n2", "name": "b", "filePath": "x.py", "score": 0.5},
            {"nodeId": "n1", "name": "a", "filePath": "x.py", "score": 0.5},
            {"nodeId": "n3", "name": "c", "filePath": "x.py", "score": 0.9},
        ]

    monkeypatch.setattr(bm25, "create_fts_index", fake_create_fts_index)
    monkeypatch.setattr(bm25, "query_fts", fake_query_fts)

    index = bm25.BM25SearchIndex(
        table_name="CodeElement",
        index_name="test_bm25_idx",
        properties=["name", "content"],
    )

    first = await index.query("http client", limit=3)
    second = await index.query("cache", limit=2)

    assert len(create_calls) == 1
    assert len(query_calls) == 2
    assert [row["nodeId"] for row in first] == ["n3", "n1", "n2"]
    assert [row["rank"] for row in first] == [1, 2, 3]
    assert [row["nodeId"] for row in second] == ["n3", "n1", "n2"]


@pytest.mark.asyncio
async def test_bm25_empty_query_or_zero_limit_short_circuit(monkeypatch) -> None:
    call_count = 0

    async def fake_create_fts_index(*_args, **_kwargs) -> None:
        nonlocal call_count
        call_count += 1

    async def fake_query_fts(*_args, **_kwargs) -> list[dict[str, object]]:
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(bm25, "create_fts_index", fake_create_fts_index)
    monkeypatch.setattr(bm25, "query_fts", fake_query_fts)

    index = bm25.BM25SearchIndex()
    assert await index.query("   ") == []
    assert await index.query("text", limit=0) == []
    assert call_count == 0


def test_rrf_weighted_fusion_and_dedup() -> None:
    bm25_results = [
        {"nodeId": "A", "name": "A", "filePath": "a.py", "score": 8.0, "rank": 1},
        {"nodeId": "B", "name": "B", "filePath": "b.py", "score": 7.0, "rank": 2},
    ]
    semantic_results = [
        {"nodeId": "B", "name": "B", "filePath": "b.py", "score": 0.9, "rank": 1},
        {"nodeId": "C", "name": "C", "filePath": "c.py", "score": 0.8, "rank": 2},
    ]

    fused = hybrid.reciprocal_rank_fusion(
        bm25_results,
        semantic_results,
        k=60,
        bm25_weight=0.4,
        semantic_weight=0.6,
        limit=10,
    )

    assert [row["nodeId"] for row in fused] == ["B", "C", "A"]
    assert [row["rank"] for row in fused] == [1, 2, 3]
    assert fused[0]["sources"] == ["bm25", "semantic"]
    assert fused[1]["sources"] == ["semantic"]
    assert fused[2]["sources"] == ["bm25"]
    assert fused[0]["score"] == pytest.approx((0.4 / 62.0) + (0.6 / 61.0))
    assert fused[1]["score"] == pytest.approx(0.6 / 62.0)
    assert fused[2]["score"] == pytest.approx(0.4 / 61.0)


def test_rrf_deterministic_tie_breaker() -> None:
    bm25_results = [
        {"nodeId": "b-node", "name": "B", "filePath": "b.py", "score": 1.0, "rank": 1}
    ]
    semantic_results = [
        {"nodeId": "a-node", "name": "A", "filePath": "a.py", "score": 1.0, "rank": 1}
    ]

    fused = hybrid.reciprocal_rank_fusion(
        bm25_results,
        semantic_results,
        k=60,
        bm25_weight=0.5,
        semantic_weight=0.5,
    )

    assert [row["nodeId"] for row in fused] == ["a-node", "b-node"]


@pytest.mark.asyncio
async def test_hybrid_search_merge_dedupe_and_ranking(monkeypatch) -> None:
    async def fake_bm25_search(*_args, **_kwargs) -> list[dict[str, object]]:
        return [
            {"nodeId": "n1", "name": "A", "filePath": "a.py", "score": 9.0, "rank": 1},
            {"nodeId": "n2", "name": "B", "filePath": "b.py", "score": 8.0, "rank": 2},
        ]

    async def fake_semantic_search(*_args, **_kwargs) -> list[dict[str, object]]:
        return [
            {"nodeId": "n2", "name": "B", "filePath": "b.py", "score": 0.9, "rank": 1},
            {"nodeId": "n3", "name": "C", "filePath": "c.py", "score": 0.8, "rank": 2},
        ]

    monkeypatch.setattr(hybrid, "bm25_search", fake_bm25_search)
    monkeypatch.setattr(hybrid, "semantic_search", fake_semantic_search)

    results = await hybrid.hybrid_search(
        "database query",
        limit=10,
        rrf_k=0,
        bm25_weight=0.5,
        semantic_weight=0.5,
    )

    assert [row["nodeId"] for row in results] == ["n2", "n1", "n3"]
    assert [row["rank"] for row in results] == [1, 2, 3]
    assert results[0]["sources"] == ["bm25", "semantic"]


@pytest.mark.asyncio
async def test_hybrid_search_with_empty_branches(monkeypatch) -> None:
    async def fake_bm25_search(*_args, **_kwargs) -> list[dict[str, object]]:
        return [
            {
                "nodeId": "bm25-only",
                "name": "Only BM25",
                "filePath": "only.py",
                "score": 5.0,
                "rank": 1,
            }
        ]

    async def fake_semantic_search(*_args, **_kwargs) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(hybrid, "bm25_search", fake_bm25_search)
    monkeypatch.setattr(hybrid, "semantic_search", fake_semantic_search)

    one_branch = await hybrid.hybrid_search("single branch", limit=5)
    assert [row["nodeId"] for row in one_branch] == ["bm25-only"]
    assert one_branch[0]["sources"] == ["bm25"]

    both_empty = await hybrid.hybrid_search("   ", limit=5)
    assert both_empty == []
