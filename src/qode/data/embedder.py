"""all-MiniLM-L6-v2 embedding engine (local, CPU inference).

Ported from GitNexus ``embeddings/`` (~500 lines → Python).
Produces 384-dimensional vectors stored in KuzuDB's native HNSW index.
"""

from __future__ import annotations

# TODO(phase-1): implement embedding pipeline
