"""Entry-point scoring algorithm.

Ported from Qode ``entry-point-scoring.ts`` (~331 lines → Python).
Scores each entity by likelihood of being an execution entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from qode.core.framework_detection import detect_framework_from_path
from qode.data.schemas import ParsedNode, ParseResult

__all__ = [
    "ENTRY_POINT_PATTERNS",
    "UTILITY_PATTERNS",
    "calculate_entry_point_score",
    "is_test_file",
    "is_utility_file",
    "process_entry_points",
]

# ==========================================================================
# Name patterns - all supported languages
# ==========================================================================

ENTRY_POINT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "*": [
        re.compile(r"^(main|init|bootstrap|start|run|setup|configure)$", re.I),
        re.compile(r"^handle[A-Z]"),
        re.compile(r"^on[A-Z]"),
        re.compile(r"Handler$"),
        re.compile(r"Controller$"),
        re.compile(r"^process[A-Z]"),
        re.compile(r"^execute[A-Z]"),
        re.compile(r"^perform[A-Z]"),
        re.compile(r"^dispatch[A-Z]"),
        re.compile(r"^trigger[A-Z]"),
        re.compile(r"^fire[A-Z]"),
        re.compile(r"^emit[A-Z]"),
    ],
    "javascript": [
        re.compile(r"^use[A-Z]"),
    ],
    "typescript": [
        re.compile(r"^use[A-Z]"),
    ],
    "python": [
        re.compile(r"^app$"),
        re.compile(r"^(get|post|put|delete|patch)_", re.I),
        re.compile(r"^api_"),
        re.compile(r"^view_"),
    ],
    "java": [
        re.compile(r"^do[A-Z]"),
        re.compile(r"^create[A-Z]"),
        re.compile(r"^build[A-Z]"),
        re.compile(r"Service$"),
    ],
    "csharp": [
        re.compile(r"^(Get|Post|Put|Delete)"),
        re.compile(r"Action$"),
        re.compile(r"^On[A-Z]"),
        re.compile(r"Async$"),
    ],
    "go": [
        re.compile(r"Handler$"),
        re.compile(r"^Serve"),
        re.compile(r"^New[A-Z]"),
        re.compile(r"^Make[A-Z]"),
    ],
    "rust": [
        re.compile(r"^(get|post|put|delete)_handler$", re.I),
        re.compile(r"^handle_"),
        re.compile(r"^new$"),
        re.compile(r"^run$"),
        re.compile(r"^spawn"),
    ],
    "c": [
        re.compile(r"^main$"),
        re.compile(r"^init_"),
        re.compile(r"^start_"),
        re.compile(r"^run_"),
    ],
    "cpp": [
        re.compile(r"^main$"),
        re.compile(r"^init_"),
        re.compile(r"^Create[A-Z]"),
        re.compile(r"^Run$"),
        re.compile(r"^Start$"),
    ],
    "swift": [
        re.compile(r"^viewDidLoad$"),
        re.compile(r"^viewWillAppear$"),
        re.compile(r"^viewDidAppear$"),
        re.compile(r"^viewWillDisappear$"),
        re.compile(r"^viewDidDisappear$"),
        re.compile(r"^application\("),
        re.compile(r"^scene\("),
        re.compile(r"^body$"),
        re.compile(r"Coordinator$"),
        re.compile(r"^sceneDidBecomeActive$"),
        re.compile(r"^sceneWillResignActive$"),
        re.compile(r"^didFinishLaunchingWithOptions$"),
        re.compile(r"ViewController$"),
        re.compile(r"^configure[A-Z]"),
        re.compile(r"^setup[A-Z]"),
        re.compile(r"^makeBody$"),
    ],
    "php": [
        re.compile(r"Controller$"),
        re.compile(r"^handle$"),
        re.compile(r"^execute$"),
        re.compile(r"^boot$"),
        re.compile(r"^register$"),
        re.compile(r"^__invoke$"),
        re.compile(r"^(index|show|store|update|destroy|create|edit)$"),
        re.compile(r"^(get|post|put|delete|patch)[A-Z]"),
        re.compile(r"^run$"),
        re.compile(r"^fire$"),
        re.compile(r"^dispatch$"),
        re.compile(r"Service$"),
        re.compile(r"Repository$"),
        re.compile(r"^find$"),
        re.compile(r"^findAll$"),
        re.compile(r"^save$"),
        re.compile(r"^delete$"),
    ],
}

# ==========================================================================
# Utility patterns - penalize helper-like functions
# ==========================================================================

UTILITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(get|set|is|has|can|should|will|did)[A-Z]"),
    re.compile(r"^_"),
    re.compile(r"^(format|parse|validate|convert|transform)", re.I),
    re.compile(r"^(log|debug|error|warn|info)$", re.I),
    re.compile(r"^(to|from)[A-Z]"),
    re.compile(r"^(encode|decode)", re.I),
    re.compile(r"^(serialize|deserialize)", re.I),
    re.compile(r"^(clone|copy|deep)", re.I),
    re.compile(r"^(merge|extend|assign)", re.I),
    re.compile(r"^(filter|map|reduce|sort|find)", re.I),
    re.compile(r"Helper$"),
    re.compile(r"Util$"),
    re.compile(r"Utils$"),
    re.compile(r"^utils?$", re.I),
    re.compile(r"^helpers?$", re.I),
]


@dataclass(frozen=True)
class EntryPointScoreResult:
    score: float
    reasons: list[str]


def calculate_entry_point_score(
    name: str,
    language: str,
    caller_count: int,
    callee_count: int,
    *,
    is_exported: bool,
    file_path: str = "",
) -> EntryPointScoreResult:
    """Calculate entry point score for a function/method.

    Higher scores indicate better entry point candidates.
    """
    reasons: list[str] = []

    if callee_count == 0:
        return EntryPointScoreResult(score=0, reasons=["no-outgoing-calls"])

    base_score = callee_count / (caller_count + 1)
    reasons.append(f"base:{base_score:.2f}")

    export_multiplier = 2.0 if is_exported else 1.0
    if is_exported:
        reasons.append("exported")

    name_multiplier = 1.0
    if any(pattern.search(name) for pattern in UTILITY_PATTERNS):
        name_multiplier = 0.3
        reasons.append("utility-pattern")
    else:
        universal_patterns = ENTRY_POINT_PATTERNS.get("*", [])
        lang_patterns = ENTRY_POINT_PATTERNS.get(language, [])
        if any(pattern.search(name) for pattern in universal_patterns + lang_patterns):
            name_multiplier = 1.5
            reasons.append("entry-pattern")

    framework_multiplier = 1.0
    if file_path:
        framework_hint = detect_framework_from_path(file_path)
        if framework_hint is not None:
            framework_multiplier = framework_hint.entry_point_multiplier
            reasons.append(f"framework:{framework_hint.reason}")

    final_score = (
        base_score * export_multiplier * name_multiplier * framework_multiplier
    )

    return EntryPointScoreResult(score=final_score, reasons=reasons)


def is_test_file(file_path: str) -> bool:
    """Return True if *file_path* matches common test patterns."""
    p = file_path.lower().replace("\\", "/")
    return (
        p.find(".test.") != -1
        or p.find(".spec.") != -1
        or p.find("__tests__/") != -1
        or p.find("__mocks__/") != -1
        or p.find("/test/") != -1
        or p.find("/tests/") != -1
        or p.find("/testing/") != -1
        or p.endswith("_test.py")
        or p.find("/test_") != -1
        or p.endswith("_test.go")
        or p.find("/src/test/") != -1
        or p.find("/tests/") != -1
        or p.endswith("tests.swift")
        or p.endswith("test.swift")
        or p.find("uitests/") != -1
        or p.find(".tests/") != -1
        or p.find("tests.cs") != -1
        or p.endswith("test.php")
        or p.endswith("spec.php")
        or p.find("/tests/feature/") != -1
        or p.find("/tests/unit/") != -1
    )


def is_utility_file(file_path: str) -> bool:
    """Return True if *file_path* matches utility/helper patterns."""
    p = file_path.lower().replace("\\", "/")
    return (
        p.find("/utils/") != -1
        or p.find("/util/") != -1
        or p.find("/helpers/") != -1
        or p.find("/helper/") != -1
        or p.find("/common/") != -1
        or p.find("/shared/") != -1
        or p.find("/lib/") != -1
        or p.endswith("/utils.ts")
        or p.endswith("/utils.js")
        or p.endswith("/helpers.ts")
        or p.endswith("/helpers.js")
        or p.endswith("_utils.py")
        or p.endswith("_helpers.py")
    )


def _update_node_entry_point(
    node: ParsedNode,
    score: float,
    reasons: list[str],
) -> ParsedNode:
    props = node.properties.model_copy(
        update={
            "entry_point_score": score,
            "entry_point_reason": " x ".join(reasons),
        }
    )
    return node.model_copy(update={"properties": props})


def process_entry_points(parse_result: ParseResult) -> None:
    """Score entry points for parsed Function/Method nodes.

    Called during Phase 6 (entry-point analysis) of the pipeline.
    """
    caller_count: dict[str, int] = {}
    callee_count: dict[str, int] = {}

    for rel in parse_result.relationships:
        if rel.type != "CALLS":
            continue
        callee_count[rel.source_id] = callee_count.get(rel.source_id, 0) + 1
        caller_count[rel.target_id] = caller_count.get(rel.target_id, 0) + 1

    updated_nodes: list[ParsedNode] = []
    for node in parse_result.nodes:
        if node.label not in {"Function", "Method"}:
            updated_nodes.append(node)
            continue

        file_path = node.properties.file_path
        if is_test_file(file_path):
            updated_nodes.append(node)
            continue

        node_caller_count = caller_count.get(node.id, 0)
        node_callee_count = callee_count.get(node.id, 0)

        score_result = calculate_entry_point_score(
            node.properties.name,
            node.properties.language or "javascript",
            node_caller_count,
            node_callee_count,
            is_exported=node.properties.is_exported,
            file_path=file_path,
        )

        score = score_result.score
        reasons = list(score_result.reasons)

        if score > 0:
            updated_nodes.append(_update_node_entry_point(node, score, reasons))
        else:
            updated_nodes.append(node)

    parse_result.nodes = updated_nodes
    return None
