"""EXTENDS / IMPLEMENTS heritage extraction.

Ported from GitNexus ``heritage-processor.ts`` (~200 lines → Python).
"""

from __future__ import annotations

from qode.data.schemas import ParseResult


def process_heritage(parse_result: ParseResult) -> None:
    """Extract EXTENDS/IMPLEMENTS relationships between classes.

    Called during Phase 3 (symbol resolution) of the pipeline.
    Currently a stub — will be implemented in a later phase.
    """
    # TODO(phase-2): implement heritage extraction
    return None
