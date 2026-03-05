"""3-tier call resolution with confidence scoring.

Ported from GitNexus ``call-processor.ts`` (~529 lines → Python).
Tiers: direct (high), inferred (medium), heuristic (low).
"""

from __future__ import annotations

# TODO(phase-1): implement call resolution
