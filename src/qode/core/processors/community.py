"""Leiden community detection for graph clustering.

Ported from Qode ``vendor/leiden/`` (~747 lines → Python).
Groups related nodes into communities for visual coloring in Sigma.js.
"""

from __future__ import annotations

import re
from collections import defaultdict

from qode.core.parsers.parser import generate_id
from qode.data.schemas import (
    ParsedNode,
    ParsedNodeProperties,
    ParsedRelationship,
    ParseResult,
)

_EXCLUDED_LABELS = {"File", "Folder", "Community", "Process"}
_COMMUNITY_EDGE_TYPES = {"CALLS", "INHERITS", "EXTENDS", "IMPLEMENTS", "IMPORTS"}
_TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _code_node_ids(parse_result: ParseResult) -> list[str]:
    return sorted(
        node.id for node in parse_result.nodes if node.label not in _EXCLUDED_LABELS
    )


def _build_adjacency(
    parse_result: ParseResult,
    node_ids: set[str],
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for rel in parse_result.relationships:
        if rel.type not in _COMMUNITY_EDGE_TYPES:
            continue
        if rel.source_id not in node_ids or rel.target_id not in node_ids:
            continue
        adjacency[rel.source_id].add(rel.target_id)
        adjacency[rel.target_id].add(rel.source_id)
    return adjacency


def _try_leiden(adjacency: dict[str, set[str]]) -> list[list[str]] | None:
    try:
        import igraph  # type: ignore
        import leidenalg  # type: ignore
    except Exception:
        return None

    node_ids = sorted(adjacency)
    if not node_ids:
        return []

    index_by_id = {node_id: idx for idx, node_id in enumerate(node_ids)}
    edges: list[tuple[int, int]] = []
    for source_id in node_ids:
        for target_id in sorted(adjacency[source_id]):
            source_idx = index_by_id[source_id]
            target_idx = index_by_id[target_id]
            if source_idx < target_idx:
                edges.append((source_idx, target_idx))

    graph = igraph.Graph(n=len(node_ids), edges=edges, directed=False)
    partition = leidenalg.find_partition(
        graph,
        leidenalg.ModularityVertexPartition,
        seed=0,
        n_iterations=2,
    )

    communities: list[list[str]] = []
    for members in partition:
        ids = sorted(node_ids[idx] for idx in members)
        if ids:
            communities.append(ids)

    communities.sort(key=lambda members: (members[0], len(members)))
    return communities


def _deterministic_fallback(adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Deterministic Leiden-like fallback without external dependencies.

    This approximates community refinement with stable, synchronous weighted
    label propagation. It is production-safe, repeatable, and does not require
    optional native packages.
    """

    node_ids = sorted(adjacency)
    if not node_ids:
        return []

    labels = {node_id: node_id for node_id in node_ids}
    for _ in range(12):
        changed = False
        for node_id in node_ids:
            neighbors = adjacency[node_id]
            if not neighbors:
                continue

            weights: dict[str, int] = defaultdict(int)
            for neighbor_id in neighbors:
                weights[labels[neighbor_id]] += 1
            current_label = labels[node_id]
            current_weight = weights.get(current_label, 0)
            best_label, best_weight = max(
                weights.items(),
                key=lambda item: (item[1], item[0] == current_label, item[0]),
            )
            if best_weight > current_weight and best_label != current_label:
                labels[node_id] = best_label
                changed = True
        if not changed:
            break

    grouped: dict[str, list[str]] = defaultdict(list)
    for node_id in node_ids:
        grouped[labels[node_id]].append(node_id)

    communities = [sorted(members) for members in grouped.values() if members]
    communities.sort(key=lambda members: (members[0], len(members)))
    return communities


def _tokenize_name(name: str) -> list[str]:
    normalized = name.replace("_", " ").replace("-", " ")
    tokens: list[str] = []
    for raw in normalized.split():
        for match in _TOKEN_RE.findall(raw):
            token = match.lower()
            if len(token) >= 3:
                tokens.append(token)
    return tokens


def _community_keywords(member_ids: list[str], name_by_id: dict[str, str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for node_id in member_ids:
        for token in _tokenize_name(name_by_id.get(node_id, "")):
            counts[token] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:5]]


def _community_cohesion(member_ids: list[str], adjacency: dict[str, set[str]]) -> float:
    if len(member_ids) <= 1:
        return 1.0
    member_set = set(member_ids)
    undirected_edges = 0
    for source_id in member_ids:
        for target_id in adjacency[source_id]:
            if source_id < target_id and target_id in member_set:
                undirected_edges += 1
    max_edges = len(member_ids) * (len(member_ids) - 1) / 2
    if max_edges == 0:
        return 0.0
    return round(undirected_edges / max_edges, 4)


def process_communities(parse_result: ParseResult) -> None:
    """Run Leiden community detection on the graph.

    Called during Phase 5 (communities) of the pipeline.
    """
    parse_result.nodes = [
        node for node in parse_result.nodes if node.label != "Community"
    ]
    parse_result.relationships = [
        rel for rel in parse_result.relationships if rel.type != "MEMBER_OF"
    ]

    node_ids = _code_node_ids(parse_result)
    if not node_ids:
        return None

    adjacency = _build_adjacency(parse_result, set(node_ids))
    communities = _try_leiden(adjacency)
    enriched_by = "leiden"
    if communities is None:
        communities = _deterministic_fallback(adjacency)
        enriched_by = "fallback-deterministic"

    node_by_id = {node.id: node for node in parse_result.nodes}
    for index, member_ids in enumerate(communities, start=1):
        if not member_ids:
            continue

        name_by_id = {
            node_id: node_by_id[node_id].properties.name for node_id in member_ids
        }
        keywords = _community_keywords(
            member_ids,
            name_by_id,
        )
        cohesion = _community_cohesion(member_ids, adjacency)
        community_id = generate_id("Community", "|".join(member_ids))
        community_name = f"community-{index}"

        parse_result.nodes.append(
            ParsedNode(
                id=community_id,
                label="Community",
                properties=ParsedNodeProperties(
                    name=community_name,
                    file_path="",
                    start_line=-1,
                    end_line=-1,
                    language="",
                    is_exported=False,
                    heuristic_label=keywords[0] if keywords else community_name,
                    keywords=keywords,
                    description=f"Cluster of {len(member_ids)} related symbols",
                    enriched_by=enriched_by,
                    cohesion=cohesion,
                    symbol_count=len(member_ids),
                ),
            )
        )

        for member_id in member_ids:
            parse_result.relationships.append(
                ParsedRelationship(
                    id=generate_id("MEMBER_OF", f"{member_id}->{community_id}"),
                    source_id=member_id,
                    target_id=community_id,
                    type="MEMBER_OF",
                    confidence=0.95,
                    reason=enriched_by,
                )
            )
    return None
