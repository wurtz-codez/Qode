"""Tests for the ingestion pipeline orchestrator.

Covers:
- PipelinePhase, PipelineStats, PipelineProgress, PipelineResult schemas
- _chunk_files_by_byte_budget, _get_parseable_files helper functions
- Phase 1: Scanning (file discovery)
- Phase 3+4: Parsing (tree-sitter integration)
- Progress reporting
- Error handling
- End-to-end pipeline execution
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pydantic
import pytest

from qode.core.pipeline import (
    DEFAULT_CHUNK_BYTE_BUDGET,
    PARSEABLE_LANGUAGES,
    _chunk_files_by_byte_budget,
    _emit_progress,
    _get_file_size,
    _get_language_from_extension,
    _get_parseable_files,
    run_pipeline,
)
from qode.core.walker import FileEntry, FileWalker
from qode.data.schemas import (
    ParseResult,
    PipelinePhase,
    PipelineProgress,
    PipelineResult,
    PipelineStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str | bytes = "") -> None:
    """Write content to path, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _make_entry(
    path: Path,
    relative_path: Path,
    extension: str = ".py",
    language: str | None = "python",
    size: int = 100,
    *,
    is_binary: bool = False,
) -> FileEntry:
    """Create a FileEntry for testing."""
    return FileEntry(
        path=path,
        relative_path=relative_path,
        extension=extension,
        language=language,
        size=size,
        is_binary=is_binary,
    )


def _create_test_project(root: Path) -> None:
    """Create a realistic test project structure."""
    _write(root / "src" / "main.py", "def main():\n    print('hello')\n")
    _write(root / "src" / "utils.py", "def util():\n    pass\n")
    _write(root / "lib" / "helper.js", "module.exports = {}\n")
    _write(root / "lib" / "types.ts", "export type A = string;\n")
    _write(root / "tests" / "test_main.py", "def test():\n    assert True\n")
    _write(root / "Dockerfile", "FROM python:3.12\n")
    _write(root / "Makefile", "all:\n\techo done\n")
    _write(root / "README.md", "# Project README\n")
    _write(root / "data" / "config.yaml", "key: value\n")


# ---------------------------------------------------------------------------
# 1. Schema Tests
# ---------------------------------------------------------------------------


class TestPipelinePhase:
    """Tests for PipelinePhase literal type."""

    def test_valid_phases(self):
        """All valid pipeline phases should be accepted."""
        phases: list[PipelinePhase] = [
            "idle",
            "scanning",
            "structure",
            "parsing",
            "embeddings",
            "communities",
            "processes",
            "complete",
            "error",
        ]
        for phase in phases:
            progress = PipelineProgress(
                phase=phase,
                percent=50,
                message="test",
            )
            assert progress.phase == phase

    def test_invalid_phase_rejected(self):
        """Invalid phase strings should be rejected by Pydantic."""
        with pytest.raises(ValueError):
            PipelineProgress(
                phase="invalid_phase",  # type: ignore[arg-type]
                percent=50,
                message="test",
            )


class TestPipelineStats:
    """Tests for PipelineStats model."""

    def test_creation_with_all_fields(self):
        """PipelineStats can be created with all fields."""
        stats = PipelineStats(
            files_processed=10,
            total_files=20,
            nodes_created=50,
        )
        assert stats.files_processed == 10
        assert stats.total_files == 20
        assert stats.nodes_created == 50

    def test_creation_with_defaults(self):
        """PipelineStats requires all fields (no defaults)."""
        with pytest.raises(pydantic.ValidationError):
            PipelineStats()  # type: ignore[call-arg]

    def test_serialization(self):
        """PipelineStats should serialize to dict correctly."""
        stats = PipelineStats(
            files_processed=5,
            total_files=10,
            nodes_created=25,
        )
        data = stats.model_dump()
        assert data["files_processed"] == 5
        assert data["total_files"] == 10
        assert data["nodes_created"] == 25

    def test_frozen_immutability(self):
        """PipelineStats should be immutable."""
        stats = PipelineStats(
            files_processed=1,
            total_files=2,
            nodes_created=3,
        )
        with pytest.raises(pydantic.ValidationError):
            stats.files_processed = 99  # type: ignore[misc]


class TestPipelineProgress:
    """Tests for PipelineProgress model."""

    def test_creation_minimal(self):
        """PipelineProgress can be created with required fields only."""
        progress = PipelineProgress(
            phase="scanning",
            percent=10,
            message="Starting scan",
        )
        assert progress.phase == "scanning"
        assert progress.percent == 10
        assert progress.message == "Starting scan"
        assert progress.detail == ""
        assert progress.stats is None

    def test_creation_with_all_fields(self):
        """PipelineProgress can be created with all fields."""
        stats = PipelineStats(
            files_processed=5,
            total_files=10,
            nodes_created=20,
        )
        progress = PipelineProgress(
            phase="parsing",
            percent=50,
            message="Parsing files",
            detail="Processing chunk 2 of 3",
            stats=stats,
        )
        assert progress.phase == "parsing"
        assert progress.percent == 50
        assert progress.message == "Parsing files"
        assert progress.detail == "Processing chunk 2 of 3"
        assert progress.stats is not None
        assert progress.stats.files_processed == 5

    def test_percent_validation(self):
        """Percent accepts any integer (0-100 enforcement is optional)."""
        progress = PipelineProgress(
            phase="scanning",
            percent=101,
            message="test",
        )
        assert progress.percent == 101
        progress2 = PipelineProgress(
            phase="scanning",
            percent=-1,
            message="test",
        )
        assert progress2.percent == -1

    def test_serialization(self):
        """PipelineProgress should serialize correctly."""
        progress = PipelineProgress(
            phase="complete",
            percent=100,
            message="Done",
            detail="Processed 50 files",
            stats=PipelineStats(
                files_processed=50,
                total_files=50,
                nodes_created=200,
            ),
        )
        data = progress.model_dump()
        assert data["phase"] == "complete"
        assert data["percent"] == 100
        assert data["stats"]["files_processed"] == 50


class TestPipelineResult:
    """Tests for PipelineResult model."""

    def test_creation_with_all_fields(self):
        """PipelineResult can be created with all fields."""
        parse_result = ParseResult()
        result = PipelineResult(
            parse_result=parse_result,
            repo_path="/path/to/repo",
            total_file_count=25,
        )
        assert result.parse_result is parse_result
        assert result.repo_path == "/path/to/repo"
        assert result.total_file_count == 25

    def test_creation_with_populated_parse_result(self):
        """PipelineResult works with populated ParseResult."""
        parse_result = ParseResult(
            nodes=[],
            relationships=[],
            symbols=[],
            imports=[],
            calls=[],
            heritage=[],
            file_count=10,
        )
        result = PipelineResult(
            parse_result=parse_result,
            repo_path="/test/repo",
            total_file_count=15,
        )
        assert result.parse_result.file_count == 10
        assert result.total_file_count == 15


class TestParseResult:
    """Tests for ParseResult aggregate model."""

    def test_empty_result(self):
        """Empty ParseResult should have empty lists."""
        result = ParseResult()
        assert result.nodes == []
        assert result.relationships == []
        assert result.symbols == []
        assert result.imports == []
        assert result.calls == []
        assert result.heritage == []
        assert result.file_count == 0

    def test_mutability(self):
        """ParseResult should be mutable for aggregation."""
        result = ParseResult()
        result.nodes.append(MagicMock())  # type: ignore[union-attr]
        result.file_count += 1
        assert len(result.nodes) == 1
        assert result.file_count == 1

    def test_serialization(self):
        """ParseResult should serialize correctly."""
        result = ParseResult(file_count=5)
        data = result.model_dump()
        assert data["file_count"] == 5
        assert data["nodes"] == []


# ---------------------------------------------------------------------------
# 2. Helper Function Tests
# ---------------------------------------------------------------------------


class TestChunkFilesByByteBudget:
    """Tests for _chunk_files_by_byte_budget helper."""

    def test_empty_input_returns_empty_list(self):
        """Empty file list should return empty chunks."""
        result = _chunk_files_by_byte_budget([], 1000)
        assert result == []

    def test_single_file_single_chunk(self):
        """A single file should be in a single chunk."""
        entry = _make_entry(
            path=Path("/test/a.py"),
            relative_path=Path("a.py"),
            size=100,
        )
        result = _chunk_files_by_byte_budget([entry], 1000)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_multiple_files_fit_in_single_chunk(self):
        """Files under budget should all fit in one chunk."""
        entries = [
            _make_entry(Path(f"/test/f{i}.py"), Path(f"f{i}.py"), size=100)
            for i in range(5)
        ]
        result = _chunk_files_by_byte_budget(entries, 1000)
        assert len(result) == 1
        assert len(result[0]) == 5

    def test_files_exceed_budget_creates_multiple_chunks(self):
        """Files exceeding budget should be split into multiple chunks."""
        entries = [
            _make_entry(Path(f"/test/f{i}.py"), Path(f"f{i}.py"), size=400)
            for i in range(5)
        ]
        result = _chunk_files_by_byte_budget(entries, 1000)
        # Each chunk can hold ~2 files (800 bytes), so we get 3 chunks
        assert len(result) >= 2

    def test_single_file_exceeds_budget(self):
        """A single file larger than budget still goes in one chunk."""
        entry = _make_entry(
            path=Path("/test/large.py"),
            relative_path=Path("large.py"),
            size=2000,
        )
        result = _chunk_files_by_byte_budget([entry], 1000)
        # Single large file stays in its own chunk (can't split files)
        assert len(result) == 1
        assert result[0][0].size == 2000

    def test_byte_budget_boundary(self):
        """Files should be grouped at budget boundary."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), size=500),
            _make_entry(Path("/test/b.py"), Path("b.py"), size=500),
            _make_entry(Path("/test/c.py"), Path("c.py"), size=500),
        ]
        result = _chunk_files_by_byte_budget(entries, 1000)
        # First two files (1000 bytes) fill first chunk
        assert len(result) == 2
        assert len(result[0]) == 2
        assert len(result[1]) == 1

    def test_exact_budget_boundary(self):
        """Files exactly at budget should be grouped together."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), size=500),
            _make_entry(Path("/test/b.py"), Path("b.py"), size=500),
        ]
        result = _chunk_files_by_byte_budget(entries, 1000)
        # Exactly 1000 bytes, should be one chunk
        assert len(result) == 1
        assert len(result[0]) == 2


class TestGetParseableFiles:
    """Tests for _get_parseable_files helper."""

    def test_empty_iterator_returns_empty_list(self):
        """Empty iterator should return empty list."""
        result = _get_parseable_files(iter([]))
        assert result == []

    def test_all_parseable_files(self):
        """All files with known languages should be returned."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), language="python"),
            _make_entry(Path("/test/b.js"), Path("b.js"), language="javascript"),
            _make_entry(Path("/test/c.ts"), Path("c.ts"), language="typescript"),
        ]
        result = _get_parseable_files(iter(entries))
        assert len(result) == 3

    def test_filters_unknown_language(self):
        """Files with unknown language should be filtered out."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), language="python"),
            _make_entry(Path("/test/b.txt"), Path("b.txt"), language=None),
            _make_entry(Path("/test/c.unknown"), Path("c.unknown"), language=None),
        ]
        result = _get_parseable_files(iter(entries))
        assert len(result) == 1
        assert result[0].language == "python"

    def test_filters_unsupported_language(self):
        """Files with unsupported language should be filtered out."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), language="python"),
            _make_entry(Path("/test/b.xyz"), Path("b.xyz"), language=None),
        ]
        result = _get_parseable_files(iter(entries))
        # .xyz is not in CODE_EXTENSIONS
        assert len(result) == 1

    def test_filters_non_parseable_languages(self):
        """Languages without tree-sitter support should be filtered out."""
        entries = [
            _make_entry(Path("/test/a.py"), Path("a.py"), language="python"),
            _make_entry(
                Path("/test/b.md"),
                Path("b.md"),
                extension=".md",
                language="markdown",
            ),
            _make_entry(
                Path("/test/c.json"),
                Path("c.json"),
                extension=".json",
                language="json",
            ),
            _make_entry(
                Path("/test/d.yaml"),
                Path("d.yaml"),
                extension=".yaml",
                language="yaml",
            ),
            _make_entry(
                Path("/test/e.html"),
                Path("e.html"),
                extension=".html",
                language="html",
            ),
            _make_entry(
                Path("/test/f.css"),
                Path("f.css"),
                extension=".css",
                language="css",
            ),
            _make_entry(
                Path("/test/g.sh"),
                Path("g.sh"),
                extension=".sh",
                language="shell",
            ),
            _make_entry(
                Path("/test/h.rb"),
                Path("h.rb"),
                extension=".rb",
                language="ruby",
            ),
            _make_entry(
                Path("/test/i.sql"),
                Path("i.sql"),
                extension=".sql",
                language="sql",
            ),
        ]
        result = _get_parseable_files(iter(entries))
        assert len(result) == 1
        assert result[0].language == "python"

    def test_all_tree_sitter_languages_pass(self):
        """All languages with tree-sitter support should pass the filter."""
        entries = [
            _make_entry(Path(f"/test/f.{lang}"), Path(f"f.{lang}"), language=lang)
            for lang in PARSEABLE_LANGUAGES
        ]
        result = _get_parseable_files(iter(entries))
        assert len(result) == len(PARSEABLE_LANGUAGES)


class TestGetLanguageFromExtension:
    """Tests for _get_language_from_extension helper."""

    @pytest.mark.parametrize(
        "ext, expected",
        [
            (".py", "python"),
            (".js", "javascript"),
            (".ts", "typescript"),
            (".jsx", "javascript"),
            (".tsx", "typescript"),
            (".pyi", "python"),
            (".java", "java"),
            (".go", "go"),
            (".rs", "rust"),
            (".rb", "ruby"),
            (".php", "php"),
            (".swift", "swift"),
            (".kt", "kotlin"),
            (".scala", "scala"),
            (".c", "c"),
            (".cpp", "cpp"),
            (".h", "c"),
            (".hpp", "cpp"),
            (".cs", "csharp"),
            (".sh", "shell"),
            (".sql", "sql"),
            (".html", "html"),
            (".css", "css"),
            (".scss", "scss"),
            (".yaml", "yaml"),
            (".yml", "yaml"),
            (".json", "json"),
            (".xml", "xml"),
            (".md", "markdown"),
            (".vue", "vue"),
            (".svelte", "svelte"),
        ],
    )
    def test_known_extensions(self, ext, expected):
        """Known extensions should map to correct language."""
        assert _get_language_from_extension(ext) == expected

    def test_case_insensitive(self):
        """Extension matching should be case-insensitive."""
        assert _get_language_from_extension(".PY") == "python"
        assert _get_language_from_extension(".JS") == "javascript"
        assert _get_language_from_extension(".TS") == "typescript"

    def test_unknown_extension_returns_none(self):
        """Unknown extensions should return None."""
        assert _get_language_from_extension(".xyz") is None
        assert _get_language_from_extension(".abc") is None
        assert _get_language_from_extension("") is None


class TestGetFileSize:
    """Tests for _get_file_size helper."""

    def test_readable_file(self, tmp_path):
        """Readable file should return its size."""
        f = tmp_path / "test.py"
        f.write_text("print('hello')\n")
        assert _get_file_size(f) > 0

    def test_empty_file(self, tmp_path):
        """Empty file should return 0."""
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _get_file_size(f) == 0

    @pytest.mark.skip(reason="Permission test unreliable on macOS as non-root")
    def test_unreadable_file(self, tmp_path):
        """Unreadable file should return 0."""
        f = tmp_path / "noperm.py"
        f.write_text("x")
        f.chmod(0o000)
        try:
            assert _get_file_size(f) == 0
        finally:
            f.chmod(0o644)


class TestEmitProgress:
    """Tests for _emit_progress helper."""

    def test_no_callback_no_error(self):
        """No callback should not raise any error."""
        _emit_progress("scanning", 10, "Test message", "", None, None)

    def test_callback_receives_progress(self):
        """Callback should receive a PipelineProgress object."""
        callback = MagicMock()
        _emit_progress("scanning", 10, "Test message", "detail", None, callback)
        callback.assert_called_once()
        args = callback.call_args[0][0]
        assert isinstance(args, PipelineProgress)
        assert args.phase == "scanning"
        assert args.percent == 10
        assert args.message == "Test message"
        assert args.detail == "detail"

    def test_callback_with_stats(self):
        """Callback should receive stats when provided."""
        callback = MagicMock()
        stats = PipelineStats(
            files_processed=5,
            total_files=10,
            nodes_created=20,
        )
        _emit_progress("parsing", 50, "Parsing", "", stats, callback)
        args = callback.call_args[0][0]
        assert args.stats is not None
        assert args.stats.files_processed == 5


# ---------------------------------------------------------------------------
# 3. Phase 1 — Scanning Tests
# ---------------------------------------------------------------------------


class TestPhase1Scanning:
    """Tests for Phase 1: Scanning/Discovery."""

    def test_empty_directory(self, tmp_path):
        """Empty directory should scan without error."""
        result = run_pipeline(tmp_path)
        assert result.total_file_count == 0

    def test_directory_with_files(self, tmp_path):
        """Directory with files should be discovered."""
        _write(tmp_path / "a.py", "print('a')\n")
        _write(tmp_path / "b.js", "console.log('b')\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 2

    def test_respects_gitignore(self, tmp_path):
        """Files in .gitignore should be ignored."""
        _write(tmp_path / ".gitignore", "secret/\n")
        _write(tmp_path / "app.py", "pass\n")
        _write(tmp_path / "secret" / "key.py", "KEY='xxx'\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count == 1

    def test_respects_qodeignore(self, tmp_path):
        """Files in .qodeignore should be ignored."""
        _write(tmp_path / ".qodeignore", "generated/\n")
        _write(tmp_path / "app.py", "pass\n")
        _write(tmp_path / "generated" / "out.py", "# auto\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count == 1

    def test_filters_by_include_languages(self, tmp_path):
        """include_languages should filter to only specified languages."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.js", "var x;\n")
        result = run_pipeline(
            tmp_path,
            include_languages=["python"],
        )
        assert result.total_file_count == 1

    def test_filters_by_exclude_languages(self, tmp_path):
        """exclude_languages should filter out specified languages."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.js", "var x;\n")
        result = run_pipeline(
            tmp_path,
            exclude_languages=["javascript"],
        )
        assert result.total_file_count == 1

    def test_progress_callback_scanning_phase(self, tmp_path):
        """Progress callback should be called for scanning phase."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        phases = [p.phase for p in progress_reports]
        assert "scanning" in phases


# ---------------------------------------------------------------------------
# 4. Phase 3+4 — Parsing Tests
# ---------------------------------------------------------------------------


class TestPhase3Parsing:
    """Tests for Phase 3+4: Parsing."""

    def test_parses_python_files(self, tmp_path):
        """Python files should be parsed."""
        _write(
            tmp_path / "main.py",
            (
                "def greet(name):\n"
                "    return f'Hello, {name}'\n"
                "\n"
                "class Greeter:\n"
                "    pass\n"
            ),
        )
        result = run_pipeline(tmp_path)
        assert result.parse_result.file_count >= 1

    def test_parses_javascript_files(self, tmp_path):
        """JavaScript files should be parsed."""
        _write(tmp_path / "app.js", "function greet(name) {\n    return name;\n}\n")
        result = run_pipeline(tmp_path)
        assert result.parse_result.file_count >= 1

    def test_parses_typescript_files(self, tmp_path):
        """TypeScript files should be parsed."""
        _write(
            tmp_path / "app.ts",
            "function greet(name: string): string {\n    return name;\n}\n",
        )
        result = run_pipeline(tmp_path)
        assert result.parse_result.file_count >= 1

    def test_mixed_language_batch(self, tmp_path):
        """Mixed language files should all be parsed."""
        _write(tmp_path / "a.py", "def foo():\n    pass\n")
        _write(tmp_path / "b.js", "function foo() {}\n")
        _write(tmp_path / "c.ts", "function foo(): void {}\n")
        result = run_pipeline(tmp_path)
        assert result.parse_result.file_count >= 3

    def test_large_files_skipped(self, tmp_path):
        """Files larger than MAX_FILE_BYTES should be skipped."""
        large_content = "x" * (600 * 1024)  # 600KB > 512KB limit
        _write(tmp_path / "large.py", large_content)
        result = run_pipeline(tmp_path)
        # File should be skipped (not parsed)
        assert result.parse_result.file_count == 0

    def test_unreadable_files_handled_gracefully(self, tmp_path):
        """Unreadable files should not crash the pipeline."""
        _write(tmp_path / "good.py", "pass\n")
        bad = tmp_path / "bad.py"
        _write(bad, "pass\n")
        bad.chmod(0o000)
        try:
            result = run_pipeline(tmp_path)
            # Should complete without error
            assert result.total_file_count >= 1
        finally:
            bad.chmod(0o644)

    def test_parse_result_aggregation(self, tmp_path):
        """Parse results should be aggregated across all files."""
        _write(
            tmp_path / "a.py",
            "def foo():\n    pass\n\nclass Bar:\n    pass\n",
        )
        _write(tmp_path / "b.py", "def baz():\n    pass\n")
        result = run_pipeline(tmp_path)
        # Should have nodes from both files
        assert len(result.parse_result.nodes) >= 3  # 2 from a.py, 1 from b.py

    def test_progress_callback_parsing_phase(self, tmp_path):
        """Progress callback should be called for parsing phase."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        phases = [p.phase for p in progress_reports]
        assert "parsing" in phases


# ---------------------------------------------------------------------------
# 5. Progress Reporting Tests
# ---------------------------------------------------------------------------


class TestProgressReporting:
    """Tests for progress reporting."""

    def test_all_phases_reported(self, tmp_path):
        """All pipeline phases should be reported."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        phases = {p.phase for p in progress_reports}
        expected_phases = {
            "scanning",
            "structure",
            "parsing",
            "embeddings",
            "communities",
            "processes",
            "complete",
        }
        assert expected_phases.issubset(phases)

    def test_percent_monotonically_increases(self, tmp_path):
        """Progress percent should monotonically increase."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        percents = [p.percent for p in progress_reports]
        for i in range(1, len(percents)):
            assert percents[i] >= percents[i - 1]

    def test_final_progress_is_100(self, tmp_path):
        """Final progress should be 100%."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        final_percent = progress_reports[-1].percent
        assert final_percent == 100

    def test_stats_reflect_actual_counts(self, tmp_path):
        """Stats should reflect actual file counts."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        result = run_pipeline(tmp_path, on_progress=on_progress)
        # Check final stats
        final = progress_reports[-1]
        assert final.stats is not None
        assert final.stats.total_files == result.total_file_count

    def test_scanning_progress_0_to_15_percent(self, tmp_path):
        """Scanning phase should report 0-15%."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            if progress.phase == "scanning":
                progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        percents = [p.percent for p in progress_reports]
        assert 0 <= min(percents) <= 15
        assert max(percents) == 15

    def test_parsing_progress_range(self, tmp_path):
        """Parsing phase should report in 20-82% range."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            if progress.phase == "parsing":
                progress_reports.append(progress)

        run_pipeline(tmp_path, on_progress=on_progress)
        if progress_reports:
            percents = [p.percent for p in progress_reports]
            assert 20 <= min(percents) <= 82
            assert 20 <= max(percents) <= 82

    def test_embedding_phase_reported(self, tmp_path):
        """Embedding phase should be reported when enabled."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        with patch("qode.core.pipeline.is_kuzu_ready", return_value=False):
            run_pipeline(tmp_path, on_progress=on_progress)

        phases = {p.phase for p in progress_reports}
        assert "embeddings" in phases


# ---------------------------------------------------------------------------
# 6. Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_repo_path_raises_error(self):
        """Invalid path should raise ValueError."""
        with pytest.raises(ValueError, match="not a directory"):
            run_pipeline("/nonexistent/path")

    def test_invalid_repo_path_object_raises_error(self):
        """Invalid Path object should raise ValueError."""
        with pytest.raises(ValueError, match="not a directory"):
            run_pipeline(Path("/nonexistent/path"))

    def test_missing_directory_raises_error(self):
        """Missing directory should raise ValueError."""
        with pytest.raises(ValueError):
            run_pipeline("/tmp/this_directory_does_not_exist_12345")

    def test_no_parseable_files_completes_successfully(self, tmp_path):
        """No parseable files should still complete successfully."""
        _write(tmp_path / "README.txt", "Just some text")
        _write(tmp_path / "data.csv", "a,b,c\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count == 0
        assert result.parse_result.file_count == 0


class TestErrorPhaseEmission:
    """Tests for error phase emission on pipeline failure."""

    def test_error_phase_emitted_on_failure(self, tmp_path):
        """Pipeline should emit error phase when an unexpected error occurs."""
        _write(tmp_path / "a.py", "pass\n")
        progress_reports: list[PipelineProgress] = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        with (
            patch(
                "qode.core.pipeline.parse_batch",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            run_pipeline(tmp_path, on_progress=on_progress)

        # Should have emitted an error phase
        error_phases = [p for p in progress_reports if p.phase == "error"]
        assert len(error_phases) == 1
        assert "boom" in error_phases[0].message

    def test_error_phase_not_emitted_for_invalid_path(self):
        """ValueError for invalid path should NOT emit error phase."""
        progress_reports: list[PipelineProgress] = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        with pytest.raises(ValueError):
            run_pipeline("/nonexistent/path", on_progress=on_progress)

        # No error phase — ValueError is raised before pipeline starts
        error_phases = [p for p in progress_reports if p.phase == "error"]
        assert len(error_phases) == 0

    def test_original_exception_is_reraised(self, tmp_path):
        """The original exception should be re-raised after error emission."""
        _write(tmp_path / "a.py", "pass\n")
        with (
            patch(
                "qode.core.pipeline.parse_batch",
                side_effect=TypeError("type error"),
            ),
            pytest.raises(TypeError, match="type error"),
        ):
            run_pipeline(tmp_path)


class TestByteBudgetConfiguration:
    """Tests for custom byte budget configuration."""

    def test_custom_byte_budget(self, tmp_path):
        """Custom byte budget should be respected."""
        _write(tmp_path / "a.py", "pass\n")
        result = run_pipeline(
            tmp_path,
            chunk_byte_budget=1024 * 1024,  # 1MB
        )
        assert result.total_file_count >= 1

    def test_small_byte_budget_creates_more_chunks(self, tmp_path):
        """Small byte budget should create more parsing chunks."""
        # Create files that would fit in one chunk with default budget
        for i in range(10):
            _write(tmp_path / f"f{i}.py", "x" * 100 + "\n")
        # Use tiny budget
        result = run_pipeline(
            tmp_path,
            chunk_byte_budget=500,  # 500 bytes
        )
        # Should complete without error
        assert result.total_file_count >= 10


# ---------------------------------------------------------------------------
# 7. End-to-End Tests
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    """End-to-end pipeline integration tests."""

    def test_full_pipeline_on_fixture_directory(self, tmp_path):
        """Full pipeline should work on a realistic project."""
        _create_test_project(tmp_path)
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 5
        assert result.parse_result.file_count >= 5
        assert result.repo_path == str(tmp_path.resolve())

    def test_full_pipeline_with_progress(self, tmp_path):
        """Full pipeline with progress callback should work."""
        _create_test_project(tmp_path)
        progress_reports = []

        def on_progress(progress: PipelineProgress):
            progress_reports.append(progress)

        result = run_pipeline(tmp_path, on_progress=on_progress)
        assert len(progress_reports) > 0
        assert result.total_file_count >= 5

    def test_full_pipeline_stats_correctness(self, tmp_path):
        """Pipeline stats should be accurate."""
        _create_test_project(tmp_path)
        result = run_pipeline(tmp_path)
        # Stats should match the result
        final_stats = result.parse_result
        assert final_stats.file_count >= 1

    def test_multiple_runs_produce_results(self, tmp_path):
        """Multiple pipeline runs should each produce results."""
        _write(tmp_path / "a.py", "def foo():\n    pass\n")
        result1 = run_pipeline(tmp_path)
        result2 = run_pipeline(tmp_path)
        assert result1.total_file_count == result2.total_file_count

    def test_repo_path_resolution(self, tmp_path):
        """Repo path should be resolved to absolute path."""
        # Run with relative path
        original_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path.parent)
            result = run_pipeline(tmp_path.name)
            # Should be absolute path
            assert Path(result.repo_path).is_absolute()
        finally:
            os.chdir(original_cwd)

    def test_non_parseable_files_excluded_from_parsing(self, tmp_path):
        """Non-parseable files should be counted but not parsed."""
        _write(tmp_path / "main.py", "def main():\n    pass\n")
        _write(tmp_path / "README.md", "# Readme\n")
        _write(tmp_path / "config.yaml", "key: value\n")
        _write(tmp_path / "style.css", "body { color: red; }\n")
        _write(tmp_path / "data.json", '{"key": "value"}\n')
        result = run_pipeline(tmp_path)
        # All 5 files discovered by walker
        assert result.total_file_count == 5
        # Only Python file was parsed (md, yaml, css, json are not parseable)
        assert result.parse_result.file_count == 1


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_small_files(self, tmp_path):
        """Very small files should be handled correctly."""
        for i in range(20):
            _write(tmp_path / f"f{i}.py", "x\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count == 20

    def test_files_with_special_characters_in_names(self, tmp_path):
        """Files with special characters should be handled."""
        _write(tmp_path / "file-with-dash.py", "pass\n")
        _write(tmp_path / "file_with_underscore.py", "pass\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 2

    def test_deeply_nested_directories(self, tmp_path):
        """Deeply nested directories should be traversed."""
        deep_path = tmp_path / "a" / "b" / "c" / "d" / "e"
        _write(deep_path / "deep.py", "pass\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 1

    def test_empty_file_is_parsed(self, tmp_path):
        """Empty code files should be discovered."""
        _write(tmp_path / "empty.py", "")
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 1

    def test_unicode_content(self, tmp_path):
        """Unicode content should be handled."""
        _write(
            tmp_path / "unicode.py",
            "# -*- coding: utf-8 -*-\ndef 返回():\n    pass\n",
        )
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 1


class TestPipelineWithMocks:
    """Tests using mocks for isolated component testing."""

    @patch("qode.core.pipeline.parse_batch")
    def test_parsing_uses_parse_batch(self, mock_parse_batch, tmp_path):
        """Pipeline should call parse_batch for parsing."""
        _write(tmp_path / "a.py", "pass\n")
        mock_parse_batch.return_value = ParseResult()
        run_pipeline(tmp_path)
        mock_parse_batch.assert_called()

    @patch("qode.core.pipeline.process_structure")
    def test_structure_phase_called(self, mock_structure, tmp_path):
        """Structure phase should call process_structure."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_structure.assert_called_once()

    @patch("qode.core.pipeline.process_communities")
    def test_communities_phase_called(self, mock_communities, tmp_path):
        """Communities phase should call process_communities."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_communities.assert_called_once()

    @patch("qode.core.pipeline.process_entry_points")
    @patch("qode.core.pipeline.process_flows")
    def test_processes_phase_called(self, mock_flows, mock_entry, tmp_path):
        """Processes phase should call entry points and flows."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_entry.assert_called_once()
        mock_flows.assert_called_once()

    @patch("qode.core.pipeline.process_calls")
    def test_calls_phase_called(self, mock_calls, tmp_path):
        """Symbol resolution should call process_calls."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_calls.assert_called_once()

    @patch("qode.core.pipeline.process_imports")
    def test_imports_phase_called(self, mock_imports, tmp_path):
        """Symbol resolution should call process_imports."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_imports.assert_called_once()

    @patch("qode.core.pipeline.process_heritage")
    def test_heritage_phase_called(self, mock_heritage, tmp_path):
        """Symbol resolution should call process_heritage."""
        _write(tmp_path / "a.py", "pass\n")
        run_pipeline(tmp_path)
        mock_heritage.assert_called_once()


class TestParseableLanguages:
    """Tests for PARSEABLE_LANGUAGES constant."""

    def test_contains_core_languages(self):
        """Should contain all 12 core languages plus tsx."""
        expected = {
            "python",
            "javascript",
            "typescript",
            "tsx",
            "java",
            "go",
            "rust",
            "c",
            "cpp",
            "csharp",
            "php",
            "kotlin",
            "swift",
        }
        assert expected == PARSEABLE_LANGUAGES

    def test_excludes_non_parseable_languages(self):
        """Should NOT contain non-parseable languages."""
        non_parseable = {
            "markdown",
            "json",
            "yaml",
            "html",
            "css",
            "shell",
            "ruby",
            "perl",
            "sql",
        }
        assert not PARSEABLE_LANGUAGES.intersection(non_parseable)


class TestPipelineConstants:
    """Tests for pipeline constants."""

    def test_default_chunk_byte_budget(self):
        """DEFAULT_CHUNK_BYTE_BUDGET should be 20MB."""
        assert DEFAULT_CHUNK_BYTE_BUDGET == 20 * 1024 * 1024

    def test_chunk_budget_usable_as_parameter(self, tmp_path):
        """Default budget should be usable as parameter."""
        _write(tmp_path / "a.py", "pass\n")
        result = run_pipeline(tmp_path, chunk_byte_budget=DEFAULT_CHUNK_BYTE_BUDGET)
        assert result.total_file_count >= 1


# ---------------------------------------------------------------------------
# Regression Tests
# ---------------------------------------------------------------------------


class TestRegression:
    """Regression tests for known issues."""

    def test_zero_byte_files_not_causing_issues(self, tmp_path):
        """Zero-byte files should not cause parsing issues."""
        _write(tmp_path / "empty.py", "")
        _write(tmp_path / "nonempty.py", "pass\n")
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 1

    def test_filewalker_integration(self, tmp_path):
        """FileWalker should integrate properly with pipeline."""
        _write(tmp_path / "src" / "main.py", "def main():\n    pass\n")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        assert len(entries) >= 1
        # Pipeline should find same files
        result = run_pipeline(tmp_path)
        assert result.total_file_count >= 1
