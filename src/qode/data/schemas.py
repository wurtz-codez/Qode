"""Pydantic models for all Qode entities.

Covers: File, Directory, Module, Class, Function, Variable, Import, Call,
Parameter, ReturnType, Decorator, TypeAnnotation, Property, Export,
Heritage, Community, EntryPoint, ExecutionFlow, FrameworkPattern.
Also covers agent annotation models and search result models.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Phase 1 (Task 4): Parser-related models only.
#
# The full schema set (File, Directory, Module graph nodes, community
# detection models, agent annotation models, search result models, etc.)
# will be added in later phases as the corresponding subsystems are built.
# ---------------------------------------------------------------------------

# Every valid entity label the parser can produce.
NodeLabel = Literal[
    "Function",
    "Class",
    "Interface",
    "Method",
    "Struct",
    "Enum",
    "Namespace",
    "Module",
    "Trait",
    "Impl",
    "TypeAlias",
    "Const",
    "Static",
    "Typedef",
    "Macro",
    "Union",
    "Property",
    "Record",
    "Delegate",
    "Annotation",
    "Constructor",
    "Template",
    "CodeElement",
]

HeritageKind = Literal["extends", "implements", "trait-impl"]


# -- Parsed node -----------------------------------------------------------


class ParsedNodeProperties(BaseModel):
    """Properties bag attached to every parsed code entity."""

    model_config = ConfigDict(frozen=True)

    name: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    is_exported: bool
    ast_framework_multiplier: Optional[float] = None  # noqa: UP045
    ast_framework_reason: Optional[str] = None  # noqa: UP045
    entry_point_score: Optional[float] = None  # noqa: UP045
    entry_point_reason: Optional[str] = None  # noqa: UP045
    description: Optional[str] = None  # noqa: UP045


class ParsedNode(BaseModel):
    """A single code entity extracted by the tree-sitter parser.

    Examples include classes, functions, methods, interfaces, structs,
    enums, and other language-specific constructs.  The ``id`` is
    deterministically generated from ``label``, ``file_path``, ``name``,
    and ``start_line`` so that repeated parses yield stable identifiers.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    label: NodeLabel
    properties: ParsedNodeProperties


# -- Parsed relationship ----------------------------------------------------


class ParsedRelationship(BaseModel):
    """A DEFINES relationship emitted by the parser.

    Represents the fact that a source file *defines* a particular code
    entity.  ``source_id`` is the file node ID and ``target_id`` is the
    entity node ID.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    source_id: str
    target_id: str
    type: str  # always "DEFINES" for parser output
    confidence: float
    reason: str
    properties: Optional[dict[str, str]] = None  # noqa: UP045


# -- Symbol table entry -----------------------------------------------------


class ParsedSymbol(BaseModel):
    """Symbol-table entry linking a name to its parsed node.

    Used during the resolution phase to match imports and call-sites to
    their target definitions.
    """

    model_config = ConfigDict(frozen=True)

    file_path: str
    name: str
    node_id: str
    type: str  # mirrors the NodeLabel of the owning ParsedNode


# -- Extracted artefacts ----------------------------------------------------


class ExtractedImport(BaseModel):
    """An import statement extracted from a source file.

    ``raw_import_path`` is the verbatim module/package path as it
    appears in source (e.g. ``"../utils/helpers"``).  Resolution to an
    absolute file path happens in a later phase.
    """

    model_config = ConfigDict(frozen=True)

    file_path: str
    raw_import_path: str
    language: str


class ExtractedCall(BaseModel):
    """A call-site extracted from a source file.

    ``source_id`` is the node ID of the enclosing function or method.
    For top-level calls that are not inside any function, ``source_id``
    falls back to the file's own node ID.
    """

    model_config = ConfigDict(frozen=True)

    file_path: str
    called_name: str
    source_id: str


class ExtractedHeritage(BaseModel):
    """An inheritance or trait-implementation relationship.

    Captures ``extends``, ``implements``, and ``trait-impl`` edges
    between classes / interfaces / traits.
    """

    model_config = ConfigDict(frozen=True)

    file_path: str
    class_name: str
    parent_name: str
    kind: HeritageKind


# -- Aggregate parse result -------------------------------------------------


class ParseResult(BaseModel):
    """Aggregate result returned after parsing a batch of source files.

    This is the top-level container handed back by the parsing engine
    and consumed by downstream phases (resolution, graph ingestion,
    embedding, etc.).

    Unlike the individual models above, ``ParseResult`` is **mutable**
    so that the parser can incrementally append to its lists during a
    batch run.
    """

    nodes: list[ParsedNode] = Field(default_factory=list)
    relationships: list[ParsedRelationship] = Field(default_factory=list)
    symbols: list[ParsedSymbol] = Field(default_factory=list)
    imports: list[ExtractedImport] = Field(default_factory=list)
    calls: list[ExtractedCall] = Field(default_factory=list)
    heritage: list[ExtractedHeritage] = Field(default_factory=list)
    file_count: int = 0


# -- Pipeline phase -----------------------------------------------------------

PipelinePhase = Literal[
    "idle",
    "scanning",
    "structure",
    "parsing",
    "communities",
    "processes",
    "complete",
    "error",
]


# -- Pipeline progress --------------------------------------------------------


class PipelineStats(BaseModel):
    """Counters embedded in progress reports."""

    model_config = ConfigDict(frozen=True)

    files_processed: int
    total_files: int
    nodes_created: int


class PipelineProgress(BaseModel):
    """Progress report emitted by the pipeline during execution."""

    phase: PipelinePhase
    percent: int  # 0-100
    message: str
    detail: str = ""
    stats: Optional[PipelineStats] = None  # noqa: UP045


# -- Pipeline result ----------------------------------------------------------


class PipelineResult(BaseModel):
    """Final output of the ingestion pipeline.

    Contains the aggregated parse result from all chunks, repository path,
    and statistics about the ingestion run.
    """

    parse_result: ParseResult
    repo_path: str
    total_file_count: int
