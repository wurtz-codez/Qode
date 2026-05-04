"""EXTENDS / IMPLEMENTS heritage extraction.

Ported from Qode ``heritage-processor.ts`` (~200 lines → Python).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from qode.core.parsers.parser import generate_id
from qode.core.symbol_table import SymbolTable
from qode.data.schemas import ExtractedHeritage, ParsedRelationship, ParseResult

__all__ = ["process_heritage"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ResolveResult:
    node_id: str
    confidence: float
    reason: str


def _resolve_heritage_target(
    parent_name: str,
    current_file: str,
    symbol_table: SymbolTable,
    import_map: dict[str, set[str]],
) -> _ResolveResult | None:
    # Tier 1: Same-file
    local_node_id = symbol_table.lookup_exact(current_file, parent_name)
    if local_node_id is not None:
        return _ResolveResult(
            node_id=local_node_id,
            confidence=0.95,
            reason="same-file",
        )

    all_defs = symbol_table.lookup_fuzzy(parent_name)
    if not all_defs:
        return None

    # Tier 2: Import-resolved
    imported_files = import_map.get(current_file)
    if imported_files is not None:
        for defn in all_defs:
            if defn.file_path in imported_files:
                return _ResolveResult(
                    node_id=defn.node_id,
                    confidence=0.9,
                    reason="import-resolved",
                )

    # Tier 3: Fuzzy global
    confidence = 0.5 if len(all_defs) == 1 else 0.3
    return _ResolveResult(
        node_id=all_defs[0].node_id,
        confidence=confidence,
        reason="fuzzy-global",
    )


def process_heritage(
    parse_result: ParseResult,
    *,
    symbol_table: SymbolTable,
    import_map: dict[str, set[str]],
) -> None:
    """Extract EXTENDS/IMPLEMENTS relationships between classes.

    Called during Phase 3 (symbol resolution) of the pipeline.
    Resolves ExtractedHeritage items into INHERITS relationships.
    """
    heritage_list: list[ExtractedHeritage] = parse_result.heritage

    resolved_count = 0
    unresolved_count = 0

    for heritage in heritage_list:
        # 1. Resolve child node (the class itself)
        child_node_id = symbol_table.lookup_exact(
            heritage.file_path, heritage.class_name
        )
        if not child_node_id:
            # If we cannot find the child class in the exact file, skip
            unresolved_count += 1
            continue

        # 2. Resolve parent node
        resolved_parent = _resolve_heritage_target(
            heritage.parent_name,
            heritage.file_path,
            symbol_table,
            import_map,
        )

        if not resolved_parent:
            unresolved_count += 1
            continue

        # Build the INHERITS relationship edge
        rel_id = generate_id(
            "INHERITS",
            f"{child_node_id}:{heritage.kind}->{resolved_parent.node_id}",
        )

        parse_result.relationships.append(
            ParsedRelationship(
                id=rel_id,
                source_id=child_node_id,
                target_id=resolved_parent.node_id,
                type="INHERITS",
                confidence=resolved_parent.confidence,
                reason=resolved_parent.reason,
                properties={"heritage_type": heritage.kind},
            )
        )
        resolved_count += 1

    logger.info(
        (
            "Heritage resolution complete: %d resolved, %d unresolved "
            "out of %d total heritages"
        ),
        resolved_count,
        unresolved_count,
        len(heritage_list),
    )
