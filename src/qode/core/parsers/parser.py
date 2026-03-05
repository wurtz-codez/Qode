"""py-tree-sitter parsing engine.

Ported from GitNexus ``workers/parse-worker.ts`` (~1316 lines → Python).
Parses source files into CSTs and extracts all entities using S-expression
queries. Runs in parallel via ``multiprocessing.Pool``.
"""

from __future__ import annotations

# TODO(phase-1): implement tree-sitter parsing engine
