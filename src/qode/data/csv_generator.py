"""Streaming CSV generator for bulk KuzuDB ingestion.

Ported from GitNexus ``kuzu/csv-generator.ts`` (~300 lines → Python).
"""

from __future__ import annotations

import os
import re
import shutil
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from typing import Any, Protocol, TypedDict, cast

from .kuzu_schema import NodeTableName

# ==========================================================================
# CONSTANTS
# ==========================================================================

FLUSH_EVERY = 500

# ==========================================================================
# TYPING
# ==========================================================================


class GraphNode(Protocol):
    id: str
    label: str
    properties: Mapping[str, Any]


class GraphRelationship(Protocol):
    sourceId: str  # noqa: N815
    targetId: str  # noqa: N815
    type: str
    confidence: float | None
    reason: str


class KnowledgeGraph(Protocol):
    def iter_nodes(self) -> Iterable[GraphNode]: ...

    def iter_relationships(self) -> Iterable[GraphRelationship]: ...


class StreamedNodeFile(TypedDict):
    csvPath: str
    rows: int


class StreamedCSVResult(TypedDict):
    nodeFiles: dict[NodeTableName, StreamedNodeFile]
    relCsvPath: str
    relRows: int


# ==========================================================================
# CSV ESCAPE UTILITIES
# ==========================================================================


_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_SURROGATE_RE = re.compile(r"[\uD800-\uDFFF]")
_NONCHARS_RE = re.compile(r"[\uFFFE\uFFFF]")


def sanitize_utf8(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CTRL_CHARS_RE.sub("", value)
    value = _SURROGATE_RE.sub("", value)
    value = _NONCHARS_RE.sub("", value)
    return value


def escape_csv_field(value: object | None) -> str:
    if value is None:
        return '""'
    string_value = sanitize_utf8(str(value))
    return '"' + string_value.replace('"', '""') + '"'


def escape_csv_number(value: float | None, default_value: float = -1) -> str:
    if value is None:
        return str(default_value)
    return str(value)


# ==========================================================================
# CONTENT EXTRACTION (lazy — reads from disk on demand)
# ==========================================================================


def is_binary_content(content: str) -> bool:
    if not content:
        return False
    sample = content[:1000]
    non_printable = 0
    for ch in sample:
        code = ord(ch)
        if (code < 9) or (13 < code < 32) or code == 127:
            non_printable += 1
    return (non_printable / len(sample)) >= 0.1


class FileContentCache:
    def __init__(self, repo_path: str, max_size: int = 3000) -> None:
        self._repo_path = repo_path
        self._max_size = max_size
        self._cache: OrderedDict[str, str] = OrderedDict()

    async def get(self, relative_path: str) -> str:
        if not relative_path:
            return ""
        cached = self._cache.get(relative_path)
        if cached is not None:
            self._cache.move_to_end(relative_path)
            return cached
        try:
            full_path = os.path.join(self._repo_path, relative_path)
            with open(full_path, encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            self._set(relative_path, content)
            return content
        except Exception:
            self._set(relative_path, "")
            return ""

    def _set(self, key: str, value: str) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = value
            return
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = value


async def extract_content(node: GraphNode, content_cache: FileContentCache) -> str:
    file_path = str(node.properties.get("filePath") or "")
    content = await content_cache.get(file_path)
    if not content:
        return ""
    if node.label == "Folder":
        return ""
    if is_binary_content(content):
        return "[Binary file - content not stored]"

    if node.label == "File":
        max_file_content = 10000
        if len(content) <= max_file_content:
            return content
        return content[:max_file_content] + "\n... [truncated]"

    start_line = node.properties.get("startLine")
    end_line = node.properties.get("endLine")
    if start_line is None or end_line is None:
        return ""

    lines = content.split("\n")
    start = max(0, int(start_line) - 2)
    end = min(len(lines) - 1, int(end_line) + 2)
    snippet = "\n".join(lines[start : end + 1])
    max_snippet = 5000
    if len(snippet) <= max_snippet:
        return snippet
    return snippet[:max_snippet] + "\n... [truncated]"


# ==========================================================================
# BUFFERED CSV WRITER
# ==========================================================================


class BufferedCSVWriter:
    def __init__(self, file_path: str, header: str) -> None:
        self._path = file_path
        self._handle = open(  # noqa: SIM115 - managed by BufferedCSVWriter lifecycle
            file_path,
            "w",
            encoding="utf-8",
            newline="",
        )
        self._buffer: list[str] = [header]
        self.rows = 0

    async def add_row(self, row: str) -> None:
        self._buffer.append(row)
        self.rows += 1
        if len(self._buffer) >= FLUSH_EVERY:
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        chunk = "\n".join(self._buffer) + "\n"
        self._buffer.clear()
        self._handle.write(chunk)
        self._handle.flush()

    async def finish(self) -> None:
        await self.flush()
        self._handle.close()


# ==========================================================================
# STREAMING CSV GENERATION — SINGLE PASS
# ==========================================================================


def _iter_nodes(graph: KnowledgeGraph) -> Iterable[GraphNode]:
    iter_nodes_fn = getattr(graph, "iter_nodes", None)
    if callable(iter_nodes_fn):
        return cast(Callable[[], Iterable[GraphNode]], iter_nodes_fn)()
    legacy_iter_nodes = cast(
        Callable[[], Iterable[GraphNode]],
        graph.iterNodes,  # type: ignore[attr-defined]
    )
    return legacy_iter_nodes()


def _iter_relationships(graph: KnowledgeGraph) -> Iterable[GraphRelationship]:
    iter_relationships_fn = getattr(graph, "iter_relationships", None)
    if callable(iter_relationships_fn):
        return cast(Callable[[], Iterable[GraphRelationship]], iter_relationships_fn)()
    legacy_iter_relationships = cast(
        Callable[[], Iterable[GraphRelationship]],
        graph.iterRelationships,  # type: ignore[attr-defined]
    )
    return legacy_iter_relationships()


def _get_relationship_field(rel: GraphRelationship, attr: str, fallback: str) -> str:
    value = getattr(rel, attr, None)
    if value is None:
        value = getattr(rel, fallback)
    return str(value)


def _get_relationship_number(
    rel: GraphRelationship,
    attr: str,
    fallback: str,
) -> float | None:
    value = getattr(rel, attr, None)
    if value is None:
        value = getattr(rel, fallback, None)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def stream_all_csvs_to_disk(
    graph: KnowledgeGraph,
    repo_path: str,
    csv_dir: str,
) -> StreamedCSVResult:
    with suppress(Exception):
        shutil.rmtree(csv_dir)
    os.makedirs(csv_dir, exist_ok=True)

    content_cache = FileContentCache(repo_path)

    file_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "file.csv"),
        "id,name,filePath,content",
    )
    folder_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "folder.csv"),
        "id,name,filePath",
    )
    code_element_header = (
        "id,name,filePath,startLine,endLine,isExported,content,description"
    )
    function_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "function.csv"),
        code_element_header,
    )
    class_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "class.csv"),
        code_element_header,
    )
    interface_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "interface.csv"),
        code_element_header,
    )
    method_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "method.csv"),
        code_element_header,
    )
    code_elem_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "codeelement.csv"),
        code_element_header,
    )
    community_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "community.csv"),
        "id,label,heuristicLabel,keywords,description,enrichedBy,cohesion,symbolCount",
    )
    process_writer = BufferedCSVWriter(
        os.path.join(csv_dir, "process.csv"),
        "id,label,heuristicLabel,processType,stepCount,communities,entryPointId,"
        "terminalId",
    )

    multi_lang_header = "id,name,filePath,startLine,endLine,content,description"
    multi_lang_types = (
        "Struct",
        "Enum",
        "Macro",
        "Typedef",
        "Union",
        "Namespace",
        "Trait",
        "Impl",
        "TypeAlias",
        "Const",
        "Static",
        "Property",
        "Record",
        "Delegate",
        "Annotation",
        "Constructor",
        "Template",
        "Module",
    )
    multi_lang_writers: dict[NodeTableName, BufferedCSVWriter] = {
        cast(NodeTableName, name): BufferedCSVWriter(
            os.path.join(csv_dir, f"{name.lower()}.csv"),
            multi_lang_header,
        )
        for name in multi_lang_types
    }

    code_writer_map: dict[str, BufferedCSVWriter] = {
        "Function": function_writer,
        "Class": class_writer,
        "Interface": interface_writer,
        "Method": method_writer,
        "CodeElement": code_elem_writer,
    }

    seen_file_ids: set[str] = set()

    for node in _iter_nodes(graph):
        if node.label == "File":
            if node.id in seen_file_ids:
                continue
            seen_file_ids.add(node.id)
            content = await extract_content(node, content_cache)
            await file_writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("filePath") or ""),
                        escape_csv_field(content),
                    ]
                )
            )
            continue

        if node.label == "Folder":
            await folder_writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("filePath") or ""),
                    ]
                )
            )
            continue

        if node.label == "Community":
            keywords = list(node.properties.get("keywords") or [])
            keyword_parts = []
            for keyword in keywords:
                kw = str(keyword)
                kw = kw.replace("\\", "\\\\")
                kw = kw.replace("'", "''")
                kw = kw.replace(",", "\\,")
                keyword_parts.append(f"'{kw}'")
            keywords_str = "[" + ",".join(keyword_parts) + "]"
            enriched_by = node.properties.get("enrichedBy") or "heuristic"
            await community_writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("heuristicLabel") or ""),
                        keywords_str,
                        escape_csv_field(node.properties.get("description") or ""),
                        escape_csv_field(enriched_by),
                        escape_csv_number(node.properties.get("cohesion"), 0),
                        escape_csv_number(node.properties.get("symbolCount"), 0),
                    ]
                )
            )
            continue

        if node.label == "Process":
            communities = list(node.properties.get("communities") or [])
            community_parts = []
            for community in communities:
                comm = str(community).replace("'", "''")
                community_parts.append(f"'{comm}'")
            communities_str = "[" + ",".join(community_parts) + "]"
            await process_writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("heuristicLabel") or ""),
                        escape_csv_field(node.properties.get("processType") or ""),
                        escape_csv_number(node.properties.get("stepCount"), 0),
                        escape_csv_field(communities_str),
                        escape_csv_field(node.properties.get("entryPointId") or ""),
                        escape_csv_field(node.properties.get("terminalId") or ""),
                    ]
                )
            )
            continue

        writer = code_writer_map.get(node.label)
        if writer is not None:
            content = await extract_content(node, content_cache)
            await writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("filePath") or ""),
                        escape_csv_number(node.properties.get("startLine"), -1),
                        escape_csv_number(node.properties.get("endLine"), -1),
                        "true" if node.properties.get("isExported") else "false",
                        escape_csv_field(content),
                        escape_csv_field(node.properties.get("description") or ""),
                    ]
                )
            )
            continue

        ml_writer = multi_lang_writers.get(cast(NodeTableName, node.label))
        if ml_writer is not None:
            content = await extract_content(node, content_cache)
            await ml_writer.add_row(
                ",".join(
                    [
                        escape_csv_field(node.id),
                        escape_csv_field(node.properties.get("name") or ""),
                        escape_csv_field(node.properties.get("filePath") or ""),
                        escape_csv_number(node.properties.get("startLine"), -1),
                        escape_csv_number(node.properties.get("endLine"), -1),
                        escape_csv_field(content),
                        escape_csv_field(node.properties.get("description") or ""),
                    ]
                )
            )

    all_writers = [
        file_writer,
        folder_writer,
        function_writer,
        class_writer,
        interface_writer,
        method_writer,
        code_elem_writer,
        community_writer,
        process_writer,
        *multi_lang_writers.values(),
    ]
    for writer in all_writers:
        await writer.finish()

    rel_csv_path = os.path.join(csv_dir, "relations.csv")
    rel_writer = BufferedCSVWriter(
        rel_csv_path,
        "from,to,type,confidence,reason,step",
    )
    for rel in _iter_relationships(graph):
        source_id = _get_relationship_field(rel, "source_id", "sourceId")
        target_id = _get_relationship_field(rel, "target_id", "targetId")
        reason = _get_relationship_field(rel, "reason", "reason")
        step = _get_relationship_number(rel, "step", "step")
        await rel_writer.add_row(
            ",".join(
                [
                    escape_csv_field(source_id),
                    escape_csv_field(target_id),
                    escape_csv_field(_get_relationship_field(rel, "type", "type")),
                    escape_csv_number(
                        _get_relationship_number(rel, "confidence", "confidence"),
                        1.0,
                    ),
                    escape_csv_field(reason),
                    escape_csv_number(step, 0),
                ]
            )
        )
    await rel_writer.finish()

    node_files: dict[NodeTableName, StreamedNodeFile] = {}
    table_map: Iterable[tuple[NodeTableName, BufferedCSVWriter]] = (
        ("File", file_writer),
        ("Folder", folder_writer),
        ("Function", function_writer),
        ("Class", class_writer),
        ("Interface", interface_writer),
        ("Method", method_writer),
        ("CodeElement", code_elem_writer),
        ("Community", community_writer),
        ("Process", process_writer),
        *multi_lang_writers.items(),
    )
    for name, writer in table_map:
        if writer.rows > 0:
            node_files[name] = {
                "csvPath": os.path.join(csv_dir, f"{name.lower()}.csv"),
                "rows": writer.rows,
            }

    return {
        "nodeFiles": node_files,
        "relCsvPath": rel_csv_path,
        "relRows": rel_writer.rows,
    }


sanitizeUTF8 = sanitize_utf8  # noqa: N816
escapeCSVField = escape_csv_field  # noqa: N816
escapeCSVNumber = escape_csv_number  # noqa: N816
isBinaryContent = is_binary_content  # noqa: N816
extractContent = extract_content  # noqa: N816
streamAllCSVsToDisk = stream_all_csvs_to_disk  # noqa: N816
BufferedCSVWriter.addRow = BufferedCSVWriter.add_row  # type: ignore[attr-defined]
