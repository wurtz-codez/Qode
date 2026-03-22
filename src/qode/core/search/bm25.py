"""BM25 full-text search index.

Ported from GitNexus ``bm25-index.ts`` (~200 lines → Python).
Wraps KuzuDB's native BM25 FTS index.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from qode.data.kuzu_adapter import create_fts_index, query_fts

DEFAULT_FTS_TABLE = "CodeElement"
DEFAULT_FTS_INDEX = "code_bm25_idx"
DEFAULT_FTS_PROPERTIES = ("name", "content", "description")
DEFAULT_FTS_STEMMER = "porter"


def _result_sort_key(item: dict[str, Any]) -> tuple[float, str, str, str]:
    return (
        -float(item.get("score") or 0.0),
        str(item.get("nodeId") or ""),
        str(item.get("name") or ""),
        str(item.get("filePath") or ""),
    )


class BM25SearchIndex:
    """Thin wrapper around Kuzu FTS index lifecycle and querying."""

    def __init__(
        self,
        *,
        table_name: str = DEFAULT_FTS_TABLE,
        index_name: str = DEFAULT_FTS_INDEX,
        properties: Sequence[str] = DEFAULT_FTS_PROPERTIES,
        stemmer: str = DEFAULT_FTS_STEMMER,
    ) -> None:
        self.table_name = table_name
        self.index_name = index_name
        self.properties = list(properties)
        self.stemmer = stemmer
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    async def bootstrap_index(self) -> None:
        """Create BM25 index once; no-op on subsequent calls."""
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return
            await create_fts_index(
                self.table_name,
                self.index_name,
                self.properties,
                stemmer=self.stemmer,
            )
            self._bootstrapped = True

    async def query(
        self,
        query_text: str,
        *,
        limit: int = 20,
        conjunctive: bool = False,
        ensure_index: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute BM25 query and return deterministic ranked rows."""
        query_text = query_text.strip()
        if not query_text or limit <= 0:
            return []

        if ensure_index:
            await self.bootstrap_index()

        rows = await query_fts(
            self.table_name,
            self.index_name,
            query_text,
            limit=limit,
            conjunctive=conjunctive,
        )
        ordered = sorted(rows, key=_result_sort_key)
        for rank, row in enumerate(ordered, start=1):
            row["rank"] = rank
        return ordered


_DEFAULT_BM25_INDEX = BM25SearchIndex()


async def bm25_search(
    query_text: str,
    *,
    limit: int = 20,
    conjunctive: bool = False,
    ensure_index: bool = True,
) -> list[dict[str, Any]]:
    """Search with default BM25 index configuration."""
    return await _DEFAULT_BM25_INDEX.query(
        query_text,
        limit=limit,
        conjunctive=conjunctive,
        ensure_index=ensure_index,
    )


BM25Index = BM25SearchIndex
bm25Search = bm25_search  # noqa: N816
