"""6-phase ingestion pipeline orchestrator.

Ported from GitNexus ``pipeline.ts`` (~375 lines → Python).
Phases:
  1. File discovery (walker + ignore)
  2. Parsing (Tree-sitter, parallel via multiprocessing)
  3. Symbol extraction (imports, calls, heritage)
  4. Graph construction (KuzuDB write)
  5. Embedding generation (all-MiniLM-L6-v2)
  6. Algorithm enrichment (Leiden, BFS flows, entry-point scoring)
"""

from __future__ import annotations

# TODO(phase-1): implement ingestion pipeline
