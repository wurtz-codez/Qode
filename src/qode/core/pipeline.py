"""6-phase ingestion pipeline orchestrator.

Ported from GitNexus ``pipeline.ts`` (~375 lines → Python).
Phases:
  1. File discovery (walker + ignore)
  2. Structure (directory tree processing)
  3. Parsing (Tree-sitter, chunked by byte budget)
  4. Symbol resolution (imports, calls, heritage) — stub calls
  5. Communities (Leiden detection) — stub call
  6. Processes/Flows (BFS execution traces) — stub call

This module is the core engine that drives the Explorer Agent.
All subsequent agents (Analyst, Security, Test, Documenter) depend on
its output — a populated knowledge graph.
"""

from __future__ import annotations

import asyncio
import importlib
import threading
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, Optional, TypeVar, cast

from qode.core.ignore import IgnoreService
from qode.core.parsers import parse_batch
from qode.core.parsers.queries import LANGUAGE_QUERIES
from qode.core.processors import (
    process_calls,
    process_communities,
    process_entry_points,
    process_flows,
    process_heritage,
    process_imports,
    process_structure,
)
from qode.core.symbol_table import SymbolTable
from qode.core.walker import CODE_EXTENSIONS, FileEntry, FileWalker
from qode.data.embedder import dispose_embedder, embed_texts
from qode.data.kuzu_adapter import (
    is_kuzu_ready,
    load_cached_embeddings,
    upsert_embeddings,
)
from qode.data.schemas import (
    ParseResult,
    PipelinePhase,
    PipelineProgress,
    PipelineResult,
    PipelineStats,
)

# Languages that have tree-sitter grammars and queries available.
# Derived from LANGUAGE_QUERIES + tsx (uses typescript grammar).
PARSEABLE_LANGUAGES: frozenset[str] = frozenset(LANGUAGE_QUERIES) | {"tsx"}

# Default byte budget per chunk — keeps peak memory ~200-400MB for large repos
DEFAULT_CHUNK_BYTE_BUDGET = 20 * 1024 * 1024  # 20MB

# Maximum file size to parse (matches parser.py MAX_FILE_BYTES)
MAX_FILE_BYTES = 512 * 1024  # 512KB


def _get_file_size(path: Path) -> int:
    """Get file size in bytes, returning 0 for unreadable files."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _chunk_files_by_byte_budget(
    files: list[FileEntry],
    byte_budget: int,
) -> list[list[FileEntry]]:
    """Group files into chunks that respect the byte budget.

    Args:
        files: List of FileEntry objects to chunk.
        byte_budget: Maximum total bytes per chunk.

    Returns:
        List of chunks, each a list of FileEntry objects.
    """
    if not files:
        return []

    chunks: list[list[FileEntry]] = []
    current_chunk: list[FileEntry] = []
    current_bytes = 0

    for file_entry in files:
        file_size = file_entry.size
        # If adding this file would exceed budget and we have files in chunk,
        # start a new chunk
        if current_chunk and current_bytes + file_size > byte_budget:
            chunks.append(current_chunk)
            current_chunk = []
            current_bytes = 0
        current_chunk.append(file_entry)
        current_bytes += file_size

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _get_parseable_files(files: Iterator[FileEntry]) -> list[FileEntry]:
    """Filter files to only those with a tree-sitter parser available.

    A file is parseable if:
    - It has a known language
    - The language has a tree-sitter grammar and query defined
    """
    parseable = []
    for f in files:
        if f.language and f.language in PARSEABLE_LANGUAGES:
            parseable.append(f)
    return parseable


def _get_language_from_extension(extension: str) -> Optional[str]:
    """Map file extension to language name.

    Mirrors the logic in walker.py but returns the language name string.
    """
    return CODE_EXTENSIONS.get(extension.lower())


def _emit_progress(
    phase: PipelinePhase,
    percent: int,
    message: str,
    detail: str = "",
    stats: Optional[PipelineStats] = None,
    callback: Optional[Callable[[PipelineProgress], None]] = None,
) -> None:
    """Emit a progress update via callback if provided."""
    if callback is not None:
        progress = PipelineProgress(
            phase=phase,
            percent=percent,
            message=message,
            detail=detail,
            stats=stats,
        )
        callback(progress)


T = TypeVar("T")


def _load_pipeline_config(repo_path: Path) -> dict[str, object]:
    config_path = repo_path / ".qode.toml"
    if not config_path.exists():
        return {}

    try:
        try:
            toml_loader = importlib.import_module("tomllib")
        except ModuleNotFoundError:  # pragma: no cover - py39 fallback
            toml_loader = importlib.import_module("tomli")

        with config_path.open("rb") as handle:
            data = toml_loader.load(handle)
    except Exception:
        return {}

    if isinstance(data, dict):
        return data
    return {}


def _should_skip_embeddings(
    repo_path: Path,
    config: Optional[dict[str, object]] = None,
) -> bool:
    config_data = config if config is not None else _load_pipeline_config(repo_path)
    analysis = config_data.get("analysis")
    if isinstance(analysis, dict):
        skip_value = analysis.get("skip_embeddings")
        if isinstance(skip_value, bool):
            return skip_value
    return False


def _run_async(operation: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return cast(T, asyncio.run(operation))

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(operation)
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=_runner, name="qode-async-runner", daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return cast(T, result.get("value"))


def _collect_embedding_texts(parse_result: ParseResult) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    node_ids: list[str] = []
    for node in parse_result.nodes:
        properties = node.properties
        name = properties.name
        file_path = properties.file_path
        label = node.label
        payload = f"{label} {name} {file_path}".strip()
        if not payload:
            continue
        texts.append(payload)
        node_ids.append(node.id)
    return node_ids, texts


def _normalize_cached_ids(cached: dict[str, Any]) -> set[str]:
    value = cached.get("embeddingNodeIds")
    if isinstance(value, set):
        return {str(item) for item in value}
    return set()


def run_pipeline(
    repo_path: str | Path,
    on_progress: Optional[Callable[[PipelineProgress], None]] = None,
    *,
    chunk_byte_budget: int = DEFAULT_CHUNK_BYTE_BUDGET,
    include_languages: Optional[list[str]] = None,
    exclude_languages: Optional[list[str]] = None,
) -> PipelineResult:
    """Run the 6-phase ingestion pipeline on a repository.

    This is the main entry point for the Explorer Agent. It coordinates
    file discovery, parsing, symbol resolution, graph construction, and
    algorithm enrichment (communities, flows, entry points).

    Args:
        repo_path: Path to the repository root directory.
        on_progress: Optional callback for progress updates.
        chunk_byte_budget: Maximum bytes per parse chunk (default 20MB).
        include_languages: Optional list of languages to include.
        exclude_languages: Optional list of languages to exclude.

    Returns:
        PipelineResult containing the aggregated parse result and stats.

    The pipeline runs through 6 phases:
      1. Scanning (0-15%): File discovery via FileWalker
      2. Structure (15-20%): Directory tree processing
      3. Parsing (20-82%): Chunked tree-sitter parsing
      4. Symbol Resolution (within parsing): Import/call/heritage resolution
      5. Communities (82-92%): Leiden community detection
      6. Processes (94-100%): Execution flow tracing
    """
    repo_path = Path(repo_path).resolve()
    if not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")

    try:
        # Initialize aggregate parse result
        aggregate_result = ParseResult()

        # Track stats for final result
        total_file_count = 0

        # ---------------------------------------------------------------------
        # Phase 1: Scanning (0-15%)
        # ---------------------------------------------------------------------
        _emit_progress("scanning", 0, "Scanning repository...", "", None, on_progress)

        # Create walker with ignore service
        ignore_service = IgnoreService(repo_path)
        walker = FileWalker(
            repo_path,
            ignore_service=ignore_service,
            include_languages=set(include_languages) if include_languages else None,
            exclude_languages=set(exclude_languages) if exclude_languages else None,
        )

        # Collect all files
        all_entries = list(walker.walk())
        total_file_count = len(all_entries)

        # Filter to parseable files
        parseable_files = _get_parseable_files(iter(all_entries))

        # Report progress
        stats = PipelineStats(
            files_processed=total_file_count,
            total_files=total_file_count,
            nodes_created=0,
        )
        _emit_progress(
            "scanning",
            15,
            f"Repository scanned: {total_file_count} files found, "
            f"{len(parseable_files)} parseable",
            "",
            stats,
            on_progress,
        )

        # ---------------------------------------------------------------------
        # Phase 2: Structure (15-20%)
        # ---------------------------------------------------------------------
        _emit_progress(
            "structure",
            15,
            "Analyzing project structure...",
            "",
            stats,
            on_progress,
        )

        # Extract file paths for structure processing
        file_paths = [str(e.path) for e in all_entries]

        # Process structure (stub — no-op for now)
        process_structure(file_paths)

        _emit_progress(
            "structure",
            20,
            "Project structure analyzed",
            "",
            stats,
            on_progress,
        )

        # ---------------------------------------------------------------------
        # Phase 3+4: Chunked Parsing (20-82%)
        # ---------------------------------------------------------------------
        # Group files into byte-budgeted chunks
        chunks = _chunk_files_by_byte_budget(parseable_files, chunk_byte_budget)
        num_chunks = len(chunks)
        total_parseable = len(parseable_files)

        _emit_progress(
            "parsing",
            20,
            f"Parsing {total_parseable} files in {num_chunks} chunk(s)...",
            "",
            stats,
            on_progress,
        )

        files_parsed_so_far = 0

        for chunk_idx, chunk in enumerate(chunks):
            # Read file contents for this chunk
            chunk_files: list[tuple[str, bytes, str]] = []
            for entry in chunk:
                try:
                    content = entry.path.read_bytes()
                    # Skip files larger than MAX_FILE_BYTES
                    if len(content) > MAX_FILE_BYTES:
                        continue
                    chunk_files.append((str(entry.path), content, entry.language or ""))
                except OSError:
                    # Skip unreadable files gracefully
                    continue

            if not chunk_files:
                files_parsed_so_far += len(chunk)
                continue

            # Parse this chunk
            chunk_result = parse_batch(chunk_files)

            # Merge into aggregate
            aggregate_result.nodes.extend(chunk_result.nodes)
            aggregate_result.relationships.extend(chunk_result.relationships)
            aggregate_result.symbols.extend(chunk_result.symbols)
            aggregate_result.imports.extend(chunk_result.imports)
            aggregate_result.calls.extend(chunk_result.calls)
            aggregate_result.heritage.extend(chunk_result.heritage)
            aggregate_result.file_count += chunk_result.file_count

            files_parsed_so_far += len(chunk)

            # Report progress (20-82% range)
            progress_percent = 20 + int((files_parsed_so_far / total_parseable) * 62)
            progress_percent = min(82, progress_percent)

            current_stats = PipelineStats(
                files_processed=files_parsed_so_far,
                total_files=total_parseable,
                nodes_created=len(aggregate_result.nodes),
            )

            _emit_progress(
                "parsing",
                progress_percent,
                f"Parsing chunk {chunk_idx + 1}/{num_chunks}...",
                "",
                current_stats,
                on_progress,
            )

        # After parsing, run processors for symbol resolution
        import_map = process_imports(aggregate_result, project_root=str(repo_path))
        # Build symbol table for call resolution
        symbol_table = SymbolTable.from_parse_result(aggregate_result)

        process_heritage(
            aggregate_result,
            symbol_table=symbol_table,
            import_map=import_map,
        )
        process_calls(
            aggregate_result,
            symbol_table=symbol_table,
            import_map=import_map,
        )

        # ---------------------------------------------------------------------
        # Phase 4.5: Embeddings (82-92%)
        # ---------------------------------------------------------------------
        skip_embeddings = _should_skip_embeddings(repo_path)
        if skip_embeddings or not is_kuzu_ready():
            _emit_progress(
                "embeddings",
                82,
                "Skipping embeddings",
                "Disabled by config" if skip_embeddings else "KuzuDB not ready",
                stats,
                on_progress,
            )
        else:
            _emit_progress(
                "embeddings",
                82,
                "Generating embeddings...",
                "",
                stats,
                on_progress,
            )

            node_ids, texts = _collect_embedding_texts(aggregate_result)
            cached_ids: set[str] = set()
            if texts:
                cached = cast(dict[str, Any], _run_async(load_cached_embeddings()))
                cached_ids = _normalize_cached_ids(cached)

            new_node_ids: list[str] = []
            new_texts: list[str] = []
            cache_lookup = cached_ids.__contains__ if cached_ids else None
            for node_id, text in zip(node_ids, texts):
                if cache_lookup is not None and cache_lookup(node_id):
                    continue
                new_node_ids.append(node_id)
                new_texts.append(text)

            if new_texts:
                vectors = embed_texts(new_texts)
                embed_payload = [
                    {"nodeId": node_id, "embedding": vector}
                    for node_id, vector in zip(new_node_ids, vectors)
                ]
                if embed_payload:
                    _run_async(upsert_embeddings(embed_payload))

            dispose_embedder()
            _emit_progress(
                "embeddings",
                92,
                "Embeddings generated",
                "",
                stats,
                on_progress,
            )

        # Update final stats
        stats = PipelineStats(
            files_processed=total_file_count,
            total_files=total_file_count,
            nodes_created=len(aggregate_result.nodes),
        )

        # ---------------------------------------------------------------------
        # Phase 5: Communities (82-92%)
        # ---------------------------------------------------------------------
        _emit_progress(
            "communities",
            92 if not skip_embeddings and is_kuzu_ready() else 82,
            "Detecting code communities...",
            "",
            stats,
            on_progress,
        )

        # Process communities (stub — no-op for now)
        process_communities(aggregate_result)

        _emit_progress(
            "communities",
            94 if not skip_embeddings and is_kuzu_ready() else 92,
            "Code communities detected",
            "",
            stats,
            on_progress,
        )

        # ---------------------------------------------------------------------
        # Phase 6: Processes/Flows (94-100%)
        # ---------------------------------------------------------------------
        _emit_progress(
            "processes",
            96 if not skip_embeddings and is_kuzu_ready() else 94,
            "Detecting execution flows...",
            "",
            stats,
            on_progress,
        )

        # Process entry points and flows (stubs — no-op for now)
        process_entry_points(aggregate_result)
        process_flows(aggregate_result)

        _emit_progress(
            "processes",
            100,
            "Execution flows detected",
            "",
            stats,
            on_progress,
        )

        # ---------------------------------------------------------------------
        # Complete
        # ---------------------------------------------------------------------
        _emit_progress(
            "complete",
            100,
            f"Pipeline complete! Processed {total_file_count} files, "
            f"extracted {len(aggregate_result.nodes)} entities.",
            "",
            stats,
            on_progress,
        )

        return PipelineResult(
            parse_result=aggregate_result,
            repo_path=str(repo_path),
            total_file_count=total_file_count,
        )
    except Exception as exc:
        _emit_progress("error", 0, f"Pipeline failed: {exc}", "", None, on_progress)
        raise
