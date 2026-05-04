"""Hybrid search: BM25 + semantic similarity + RRF fusion.

Ported from Qode ``hybrid-search.ts`` (~300 lines → Python).
Combines BM25 and HNSW vector similarity via Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import asyncio
from typing import Any

from qode.core.search.bm25 import bm25_search
from qode.data.embedder import embed_query
from qode.data.kuzu_adapter import execute_query, load_cached_embeddings

DEFAULT_RRF_K = 60
DEFAULT_BM25_WEIGHT = 0.4
DEFAULT_SEMANTIC_WEIGHT = 0.6


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_query_vector(vector: list[float]) -> list[float]:
    if not vector:
        return []
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(v) / norm for v in vector]


def _dot_product(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _result_sort_key(item: dict[str, Any]) -> tuple[float, str, str, str]:
    return (
        -_safe_float(item.get("score"), 0.0),
        str(item.get("nodeId") or ""),
        str(item.get("name") or ""),
        str(item.get("filePath") or ""),
    )


def _escape_cypher_text(value: str) -> str:
    return value.replace("'", "''")


def _extract_row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, (list, tuple)) and len(row) > index:
        return row[index]
    return None


async def _fetch_node_metadata(node_ids: list[str]) -> dict[str, dict[str, str]]:
    if not node_ids:
        return {}

    escaped_ids = [f"'{_escape_cypher_text(node_id)}'" for node_id in node_ids]
    id_list = ", ".join(escaped_ids)
    cypher = (
        "MATCH (n) "
        f"WHERE n.id IN [{id_list}] "
        "RETURN n.id AS nodeId, n.name AS name, n.filePath AS filePath"
    )

    try:
        rows = await execute_query(cypher)
    except Exception:
        return {}

    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        node_id = str(_extract_row_value(row, "nodeId", 0) or "")
        if not node_id:
            continue
        by_id[node_id] = {
            "name": str(_extract_row_value(row, "name", 1) or ""),
            "filePath": str(_extract_row_value(row, "filePath", 2) or ""),
        }
    return by_id


async def semantic_search(query_text: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Semantic search over cached embeddings using cosine similarity."""
    query_text = query_text.strip()
    if not query_text or limit <= 0:
        return []

    query_vector = _normalize_query_vector(embed_query(query_text))
    if not query_vector:
        return []

    cached = await load_cached_embeddings()
    embeddings = cached.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        return []

    scored: list[dict[str, Any]] = []
    for row in embeddings:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("nodeId") or "")
        vector_value = row.get("embedding")
        if not node_id or not isinstance(vector_value, list):
            continue
        try:
            vector = [float(v) for v in vector_value]
        except Exception:
            continue
        score = _dot_product(query_vector, vector)
        scored.append({"nodeId": node_id, "score": score})

    if not scored:
        return []

    ordered = sorted(scored, key=_result_sort_key)[:limit]
    ordered_ids = [str(item["nodeId"]) for item in ordered]
    metadata_by_id = await _fetch_node_metadata(ordered_ids)

    output: list[dict[str, Any]] = []
    for rank, row in enumerate(ordered, start=1):
        node_id = str(row.get("nodeId") or "")
        meta = metadata_by_id.get(node_id, {})
        output.append(
            {
                "nodeId": node_id,
                "name": str(meta.get("name") or ""),
                "filePath": str(meta.get("filePath") or ""),
                "score": _safe_float(row.get("score"), 0.0),
                "rank": rank,
            }
        )
    return output


def reciprocal_rank_fusion(
    bm25_results: list[dict[str, Any]],
    semantic_results: list[dict[str, Any]],
    *,
    k: int = DEFAULT_RRF_K,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fuse BM25 and semantic ranked lists with weighted RRF."""
    if limit <= 0:
        return []

    fused: dict[str, dict[str, Any]] = {}
    safe_k = max(0, int(k))

    def upsert(
        rows: list[dict[str, Any]],
        *,
        weight: float,
        score_key: str,
        rank_key: str,
        source_key: str,
    ) -> None:
        for idx, row in enumerate(rows, start=1):
            node_id = str(row.get("nodeId") or "")
            if not node_id:
                continue

            rank = int(row.get("rank") or idx)
            rrf_component = float(weight) / float(safe_k + max(1, rank))
            entry = fused.setdefault(
                node_id,
                {
                    "nodeId": node_id,
                    "name": str(row.get("name") or ""),
                    "filePath": str(row.get("filePath") or ""),
                    "score": 0.0,
                    "bm25Score": 0.0,
                    "semanticScore": 0.0,
                    "bm25Rank": None,
                    "semanticRank": None,
                    "sources": set(),
                },
            )

            entry["score"] = float(entry["score"]) + rrf_component
            entry[score_key] = _safe_float(row.get("score"), 0.0)
            entry[rank_key] = rank
            entry["sources"].add(source_key)
            if not entry["name"] and row.get("name"):
                entry["name"] = str(row.get("name"))
            if not entry["filePath"] and row.get("filePath"):
                entry["filePath"] = str(row.get("filePath"))

    upsert(
        bm25_results,
        weight=bm25_weight,
        score_key="bm25Score",
        rank_key="bm25Rank",
        source_key="bm25",
    )
    upsert(
        semantic_results,
        weight=semantic_weight,
        score_key="semanticScore",
        rank_key="semanticRank",
        source_key="semantic",
    )

    merged = list(fused.values())
    merged.sort(
        key=lambda item: (
            -_safe_float(item.get("score"), 0.0),
            str(item.get("nodeId") or ""),
            str(item.get("name") or ""),
            str(item.get("filePath") or ""),
        )
    )

    output: list[dict[str, Any]] = []
    for idx, item in enumerate(merged[:limit], start=1):
        sources = item.get("sources")
        source_list = sorted(sources) if isinstance(sources, set) else []
        output.append(
            {
                "nodeId": str(item.get("nodeId") or ""),
                "name": str(item.get("name") or ""),
                "filePath": str(item.get("filePath") or ""),
                "score": _safe_float(item.get("score"), 0.0),
                "rank": idx,
                "bm25Score": _safe_float(item.get("bm25Score"), 0.0),
                "semanticScore": _safe_float(item.get("semanticScore"), 0.0),
                "bm25Rank": item.get("bm25Rank"),
                "semanticRank": item.get("semanticRank"),
                "sources": source_list,
            }
        )
    return output


async def hybrid_search(
    query_text: str,
    *,
    limit: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    conjunctive: bool = False,
) -> list[dict[str, Any]]:
    """Run BM25 + semantic search and merge results with weighted RRF."""
    query_text = query_text.strip()
    if not query_text or limit <= 0:
        return []

    bm25_results, semantic_results = await _run_parallel_searches(
        query_text,
        limit=limit,
        conjunctive=conjunctive,
    )
    return reciprocal_rank_fusion(
        bm25_results,
        semantic_results,
        k=rrf_k,
        bm25_weight=bm25_weight,
        semantic_weight=semantic_weight,
        limit=limit,
    )


async def _run_parallel_searches(
    query_text: str,
    *,
    limit: int,
    conjunctive: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bm25_task = bm25_search(query_text, limit=limit, conjunctive=conjunctive)
    semantic_task = semantic_search(query_text, limit=limit)
    bm25_results, semantic_results = await asyncio.gather(
        bm25_task,
        semantic_task,
    )
    return bm25_results, semantic_results


rrf_fusion = reciprocal_rank_fusion
hybridSearch = hybrid_search  # noqa: N816
semanticSearch = semantic_search  # noqa: N816
