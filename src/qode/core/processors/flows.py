"""BFS execution flow tracing.

Ported from GitNexus ``process-processor.ts`` (~300 lines → Python).
Traces execution paths from entry points via BFS over the call graph.
"""

from __future__ import annotations

from collections import deque

from qode.core.parsers.parser import generate_id
from qode.data.schemas import (
    ParsedNode,
    ParsedNodeProperties,
    ParsedRelationship,
    ParseResult,
)

_EXCLUDED_LABELS = {"File", "Folder", "Community", "Process"}


def _build_call_graph(parse_result: ParseResult) -> dict[str, list[str]]:
    graph: dict[str, set[str]] = {}
    for rel in parse_result.relationships:
        if rel.type != "CALLS":
            continue
        graph.setdefault(rel.source_id, set()).add(rel.target_id)
    return {node_id: sorted(targets) for node_id, targets in graph.items()}


def _entry_points(parse_result: ParseResult) -> list[ParsedNode]:
    entries = [
        node
        for node in parse_result.nodes
        if node.label not in _EXCLUDED_LABELS
        and node.properties.entry_point_score is not None
        and node.properties.entry_point_score > 0
    ]
    entries.sort(
        key=lambda node: (
            -(node.properties.entry_point_score or 0.0),
            node.properties.file_path,
            node.properties.name,
            node.id,
        )
    )
    return entries


def _collect_communities(parse_result: ParseResult) -> dict[str, list[str]]:
    communities_by_symbol: dict[str, set[str]] = {}
    for rel in parse_result.relationships:
        if rel.type != "MEMBER_OF":
            continue
        communities_by_symbol.setdefault(rel.source_id, set()).add(rel.target_id)
    return {
        symbol_id: sorted(community_ids)
        for symbol_id, community_ids in communities_by_symbol.items()
    }


def _new_process_node(
    process_id: str,
    entry_id: str,
    terminal_id: str,
    step_count: int,
    communities: list[str],
) -> ParsedNode:
    return ParsedNode(
        id=process_id,
        label="Process",
        properties=ParsedNodeProperties(
            name=f"process-{entry_id[:12]}",
            file_path="",
            start_line=-1,
            end_line=-1,
            language="",
            is_exported=False,
            heuristic_label="entrypoint-bfs",
            process_type="entrypoint-bfs",
            step_count=step_count,
            communities=communities,
            entry_point_id=entry_id,
            terminal_id=terminal_id,
        ),
    )


def _new_step_relationship(
    symbol_id: str,
    process_id: str,
    step: int,
) -> ParsedRelationship:
    return ParsedRelationship(
        id=generate_id("STEP_IN_PROCESS", f"{symbol_id}->{process_id}:{step}"),
        source_id=symbol_id,
        target_id=process_id,
        type="STEP_IN_PROCESS",
        confidence=1.0,
        reason="bfs",
        step=step,
    )


def process_flows(parse_result: ParseResult) -> None:
    """Trace BFS execution flows from entry points.

    Called during Phase 6 (processes/flows) of the pipeline.
    """
    parse_result.nodes = [
        node for node in parse_result.nodes if node.label != "Process"
    ]
    parse_result.relationships = [
        rel for rel in parse_result.relationships if rel.type != "STEP_IN_PROCESS"
    ]

    call_graph = _build_call_graph(parse_result)
    if not call_graph:
        return None

    communities_by_symbol = _collect_communities(parse_result)
    process_nodes: list[ParsedNode] = []
    step_relationships: list[ParsedRelationship] = []

    for entry in _entry_points(parse_result):
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(entry.id, 0)])
        order: list[str] = []
        step_by_node: dict[str, int] = {}

        while queue:
            node_id, step = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            order.append(node_id)
            step_by_node[node_id] = step

            for neighbor_id in call_graph.get(node_id, []):
                if neighbor_id not in visited:
                    queue.append((neighbor_id, step + 1))

        if not order:
            continue

        terminal_id = max(order, key=lambda node_id: (step_by_node[node_id], node_id))
        process_id = generate_id("Process", f"{entry.id}|{'|'.join(order)}")

        process_communities: set[str] = set()
        for node_id in order:
            for community_id in communities_by_symbol.get(node_id, []):
                process_communities.add(community_id)
            step_relationships.append(
                _new_step_relationship(node_id, process_id, step_by_node[node_id])
            )

        process_nodes.append(
            _new_process_node(
                process_id=process_id,
                entry_id=entry.id,
                terminal_id=terminal_id,
                step_count=(max(step_by_node.values()) + 1),
                communities=sorted(process_communities),
            )
        )

    parse_result.nodes.extend(process_nodes)
    parse_result.relationships.extend(step_relationships)
    return None
