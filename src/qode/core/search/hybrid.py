"""Hybrid search: BM25 + semantic similarity + RRF fusion.

Ported from GitNexus ``hybrid-search.ts`` (~300 lines → Python).
Combines BM25 and HNSW vector similarity via Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

# TODO(phase-1): implement hybrid search + RRF
