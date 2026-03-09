"""Tests for FileWalker, FileEntry, CODE_EXTENSIONS, and walk_directory."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qode.core.ignore import IgnoreService
from qode.core.walker import (
    CODE_EXTENSIONS,
    FileEntry,
    FileWalker,
    walk_directory,
)

# ── helpers ──────────────────────────────────────────────────────────


def _write(path, content=""):
    """Write *content* to *path*, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _make_project(root):
    """Create a small but realistic project tree under *root*.

    Layout::

        src/
            main.py
            utils.py
        lib/
            helper.js
            types.ts
        tests/
            test_main.py
        Dockerfile
        Makefile
        README.txt          # not a code extension
        node_modules/
            pkg/
                index.js
        .git/
            config
        data.bin            # binary file
    """
    _write(root / "src" / "main.py", "print('hello')\n")
    _write(root / "src" / "utils.py", "# utils\n")
    _write(root / "lib" / "helper.js", "module.exports = {}\n")
    _write(root / "lib" / "types.ts", "export type A = string;\n")
    _write(root / "tests" / "test_main.py", "def test(): pass\n")
    _write(root / "Dockerfile", "FROM python:3.12\n")
    _write(root / "Makefile", "all:\n\techo done\n")
    _write(root / "README.txt", "readme contents")
    # ignored dirs
    _write(root / "node_modules" / "pkg" / "index.js", "// pkg\n")
    _write(root / ".git" / "config", "[core]\n")
    # binary
    _write(root / "data.bin", b"\x00\x01\x02binary content")


# ── CODE_EXTENSIONS ──────────────────────────────────────────────────


class TestCodeExtensions:
    """Tests for the CODE_EXTENSIONS mapping."""

    @pytest.mark.parametrize(
        "ext, lang",
        [
            (".py", "python"),
            (".pyi", "python"),
            (".js", "javascript"),
            (".jsx", "javascript"),
            (".ts", "typescript"),
            (".tsx", "typescript"),
            (".mjs", "javascript"),
            (".cjs", "javascript"),
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
    def test_extension_maps_to_language(self, ext, lang):
        """CODE_EXTENSIONS[ext] should equal the expected language."""
        assert CODE_EXTENSIONS[ext] == lang

    def test_contains_dockerfile_key(self):
        """The literal string 'Dockerfile' is also in CODE_EXTENSIONS."""
        assert "Dockerfile" in CODE_EXTENSIONS
        assert CODE_EXTENSIONS["Dockerfile"] == "dockerfile"


# ── FileEntry dataclass ──────────────────────────────────────────────


class TestFileEntry:
    """Tests for the FileEntry frozen dataclass."""

    def _make_entry(self, **overrides):
        """Return a FileEntry with sensible defaults, allowing overrides."""
        defaults = {
            "path": Path("/tmp/f.py"),
            "relative_path": Path("f.py"),
            "extension": ".py",
            "language": "python",
            "size": 42,
            "is_binary": False,
        }
        defaults.update(overrides)
        return FileEntry(**defaults)

    def test_fields_accessible(self):
        """All declared fields should be readable."""
        entry = self._make_entry()
        assert entry.path == Path("/tmp/f.py")
        assert entry.relative_path == Path("f.py")
        assert entry.extension == ".py"
        assert entry.language == "python"
        assert entry.size == 42
        assert entry.is_binary is False

    def test_frozen_immutability(self):
        """Assigning to a field on a frozen dataclass must raise."""
        entry = self._make_entry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.size = 99  # type: ignore[misc]

    def test_language_can_be_none(self):
        """language field accepts None."""
        entry = self._make_entry(language=None)
        assert entry.language is None


# ── FileWalker initialisation ────────────────────────────────────────


class TestFileWalkerInit:
    """Tests for FileWalker.__init__ behaviour."""

    def test_root_resolved_from_path(self, tmp_path):
        """Root should be resolved to an absolute path when given a Path."""
        walker = FileWalker(tmp_path)
        assert walker.root == tmp_path.resolve()

    def test_root_resolved_from_str(self, tmp_path):
        """Root should be resolved to an absolute path when given a str."""
        walker = FileWalker(str(tmp_path))
        assert walker.root == tmp_path.resolve()

    def test_auto_creates_ignore_service(self, tmp_path):
        """An IgnoreService should be created automatically."""
        walker = FileWalker(tmp_path)
        assert isinstance(walker.ignore_service, IgnoreService)

    def test_explicit_ignore_service(self, tmp_path):
        """A caller-provided IgnoreService should be used as-is."""
        svc = IgnoreService(tmp_path)
        walker = FileWalker(tmp_path, ignore_service=svc)
        assert walker.ignore_service is svc

    def test_include_languages(self, tmp_path):
        """include_languages should be stored."""
        langs = {"python", "javascript"}
        walker = FileWalker(tmp_path, include_languages=langs)
        assert walker.include_languages == langs

    def test_exclude_languages_default(self, tmp_path):
        """exclude_languages defaults to an empty set."""
        walker = FileWalker(tmp_path)
        assert walker.exclude_languages == set()

    def test_exclude_languages_explicit(self, tmp_path):
        """exclude_languages should be stored when provided."""
        walker = FileWalker(tmp_path, exclude_languages={"java"})
        assert walker.exclude_languages == {"java"}


# ── _detect_language ─────────────────────────────────────────────────


class TestDetectLanguage:
    """Tests for FileWalker._detect_language."""

    def _detect(self, tmp_path, filename):
        """Helper: create a walker and detect language for *filename*."""
        walker = FileWalker(tmp_path)
        return walker._detect_language(Path(filename))

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("app.py", "python"),
            ("stubs.pyi", "python"),
            ("index.js", "javascript"),
            ("app.ts", "typescript"),
            ("component.jsx", "javascript"),
            ("component.tsx", "typescript"),
            ("module.mjs", "javascript"),
            ("require.cjs", "javascript"),
        ],
    )
    def test_known_extensions(self, tmp_path, filename, expected):
        """Files with known extensions should map to the correct language."""
        assert self._detect(tmp_path, filename) == expected

    def test_dockerfile(self, tmp_path):
        """Dockerfile should be detected by name, not extension."""
        assert self._detect(tmp_path, "Dockerfile") == "dockerfile"

    def test_makefile(self, tmp_path):
        """Makefile should be detected by name."""
        assert self._detect(tmp_path, "Makefile") == "makefile"

    def test_unknown_extension_returns_none(self, tmp_path):
        """Files with unrecognised extensions should return None."""
        assert self._detect(tmp_path, "data.csv") is None
        assert self._detect(tmp_path, "notes.txt") is None
        assert self._detect(tmp_path, "image.png") is None

    def test_case_insensitive_extension(self, tmp_path):
        """Extension matching is lower-cased, so .PY -> python."""
        assert self._detect(tmp_path, "App.PY") == "python"
        assert self._detect(tmp_path, "style.CSS") == "css"


# ── _is_binary ───────────────────────────────────────────────────────


class TestIsBinary:
    """Tests for FileWalker._is_binary."""

    def test_text_file(self, tmp_path):
        """Plain text should not be detected as binary."""
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n", encoding="utf-8")
        walker = FileWalker(tmp_path)
        assert walker._is_binary(f) is False

    def test_file_with_null_bytes(self, tmp_path):
        """A file containing null bytes should be detected as binary."""
        f = tmp_path / "bin.dat"
        f.write_bytes(b"abc\x00def")
        walker = FileWalker(tmp_path)
        assert walker._is_binary(f) is True

    def test_high_non_text_ratio(self, tmp_path):
        """A file whose bytes are mostly outside printable ASCII is binary."""
        f = tmp_path / "weird.dat"
        # 100 bytes where >30 % are non-text (high bytes, no null)
        content = bytes(range(128, 228))  # all > 127, none are null
        f.write_bytes(content)
        walker = FileWalker(tmp_path)
        assert walker._is_binary(f) is True

    def test_empty_file_not_checked(self, tmp_path):
        """walk() skips binary check for size-0 files; verify _is_binary
        still returns False when called directly on an empty file."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        walker = FileWalker(tmp_path)
        # An empty read → chunk is b"", len(chunk)==0, no null check fires
        assert walker._is_binary(f) is False

    def test_unreadable_file_treated_as_binary(self, tmp_path):
        """If the file cannot be opened, _is_binary returns True."""
        f = tmp_path / "noperm.py"
        f.write_text("x")
        f.chmod(0o000)
        walker = FileWalker(tmp_path)
        try:
            assert walker._is_binary(f) is True
        finally:
            f.chmod(0o644)  # restore so tmp_path cleanup works


# ── _should_include ──────────────────────────────────────────────────


class TestShouldInclude:
    """Tests for FileWalker._should_include."""

    def test_ignored_file_returns_false(self, tmp_path):
        """A path the IgnoreService says to ignore should be excluded."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = True
        walker = FileWalker(tmp_path, ignore_service=mock_svc)
        assert walker._should_include(tmp_path / "foo.py") is False

    def test_unrecognised_language_returns_false(self, tmp_path):
        """Files with unknown extensions should be excluded."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = False
        walker = FileWalker(tmp_path, ignore_service=mock_svc)
        assert walker._should_include(tmp_path / "data.csv") is False

    def test_excluded_language_returns_false(self, tmp_path):
        """A language in exclude_languages should be excluded."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = False
        walker = FileWalker(
            tmp_path,
            ignore_service=mock_svc,
            exclude_languages={"python"},
        )
        assert walker._should_include(tmp_path / "app.py") is False

    def test_include_filter_accepts_matching_language(self, tmp_path):
        """When include_languages is set, matching languages pass."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = False
        walker = FileWalker(
            tmp_path,
            ignore_service=mock_svc,
            include_languages={"python"},
        )
        assert walker._should_include(tmp_path / "app.py") is True

    def test_include_filter_rejects_non_matching_language(self, tmp_path):
        """When include_languages is set, non-matching languages fail."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = False
        walker = FileWalker(
            tmp_path,
            ignore_service=mock_svc,
            include_languages={"python"},
        )
        assert walker._should_include(tmp_path / "app.js") is False

    def test_no_filters_includes_known_language(self, tmp_path):
        """With no include/exclude, any known language is included."""
        mock_svc = MagicMock(spec=IgnoreService)
        mock_svc.should_ignore.return_value = False
        walker = FileWalker(tmp_path, ignore_service=mock_svc)
        assert walker._should_include(tmp_path / "style.css") is True


# ── walk() ───────────────────────────────────────────────────────────


class TestWalk:
    """Tests for FileWalker.walk()."""

    def test_discovers_code_files(self, tmp_path):
        """walk() should yield entries for recognised code files."""
        _write(tmp_path / "a.py", "x = 1\n")
        _write(tmp_path / "b.js", "var x;\n")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        names = {e.relative_path.name for e in entries}
        assert "a.py" in names
        assert "b.js" in names

    def test_ignores_node_modules(self, tmp_path):
        """node_modules/ is in default ignore patterns and must be pruned."""
        _write(tmp_path / "index.js", "ok\n")
        _write(tmp_path / "node_modules" / "pkg" / "lib.js", "// pkg\n")
        walker = FileWalker(tmp_path)
        paths = [str(e.relative_path) for e in walker.walk()]
        assert not any("node_modules" in p for p in paths)

    def test_ignores_dot_git(self, tmp_path):
        """.git/ directory should not be traversed."""
        _write(tmp_path / "app.py", "pass\n")
        _write(tmp_path / ".git" / "config", "[core]\n")
        walker = FileWalker(tmp_path)
        paths = [str(e.relative_path) for e in walker.walk()]
        assert not any(".git" in p for p in paths)

    def test_entry_fields_populated(self, tmp_path):
        """Each yielded FileEntry must have correct field values."""
        _write(tmp_path / "sub" / "main.py", "# hello\n")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        assert len(entries) == 1
        entry = entries[0]
        assert entry.path == (tmp_path / "sub" / "main.py").resolve()
        assert entry.relative_path == Path("sub") / "main.py"
        assert entry.extension == ".py"
        assert entry.language == "python"
        assert entry.size > 0
        assert entry.is_binary is False

    def test_relative_path_is_relative(self, tmp_path):
        """relative_path should not be absolute."""
        _write(tmp_path / "a.py", "pass\n")
        walker = FileWalker(tmp_path)
        for entry in walker.walk():
            assert not entry.relative_path.is_absolute()

    def test_skips_non_code_files(self, tmp_path):
        """Files with unrecognised extensions should not appear."""
        _write(tmp_path / "notes.txt", "some notes\n")
        _write(tmp_path / "data.csv", "a,b,c\n")
        _write(tmp_path / "real.py", "pass\n")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        names = {e.relative_path.name for e in entries}
        assert "notes.txt" not in names
        assert "data.csv" not in names
        assert "real.py" in names

    def test_empty_file_is_not_binary(self, tmp_path):
        """A zero-byte code file should have is_binary=False."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        assert len(entries) == 1
        assert entries[0].is_binary is False
        assert entries[0].size == 0

    def test_dockerfile_and_makefile(self, tmp_path):
        """Special filenames should be discovered."""
        _write(tmp_path / "Dockerfile", "FROM alpine\n")
        _write(tmp_path / "Makefile", "all:\n")
        walker = FileWalker(tmp_path)
        langs = {e.language for e in walker.walk()}
        assert "dockerfile" in langs
        assert "makefile" in langs


# ── walk_files() ─────────────────────────────────────────────────────


class TestWalkFiles:
    """Tests for FileWalker.walk_files()."""

    def test_returns_list_of_paths(self, tmp_path):
        """walk_files() should return a list of Path objects."""
        _write(tmp_path / "a.py", "pass\n")
        walker = FileWalker(tmp_path)
        result = walker.walk_files()
        assert isinstance(result, list)
        assert all(isinstance(p, Path) for p in result)

    def test_matches_walk_results(self, tmp_path):
        """walk_files() paths should match those from walk()."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.js", "x\n")
        walker = FileWalker(tmp_path)
        walked = {e.path for e in walker.walk()}
        filed = set(walker.walk_files())
        assert walked == filed


# ── count_files() ────────────────────────────────────────────────────


class TestCountFiles:
    """Tests for FileWalker.count_files()."""

    def test_count_matches_walk(self, tmp_path):
        """count_files() should equal the number of entries from walk()."""
        _write(tmp_path / "a.py", "1\n")
        _write(tmp_path / "b.ts", "2\n")
        _write(tmp_path / "c.go", "3\n")
        walker = FileWalker(tmp_path)
        assert walker.count_files() == len(list(walker.walk()))

    def test_empty_directory(self, tmp_path):
        """An empty directory should yield zero files."""
        walker = FileWalker(tmp_path)
        assert walker.count_files() == 0


# ── count_by_language() ──────────────────────────────────────────────


class TestCountByLanguage:
    """Tests for FileWalker.count_by_language()."""

    def test_language_grouping(self, tmp_path):
        """Files should be grouped correctly by language."""
        _write(tmp_path / "a.py", "1\n")
        _write(tmp_path / "b.py", "2\n")
        _write(tmp_path / "c.js", "3\n")
        walker = FileWalker(tmp_path)
        counts = walker.count_by_language()
        assert counts["python"] == 2
        assert counts["javascript"] == 1

    def test_no_files_returns_empty(self, tmp_path):
        """No code files should produce an empty dict."""
        walker = FileWalker(tmp_path)
        assert walker.count_by_language() == {}


# ── walk_directory() convenience function ────────────────────────────


class TestWalkDirectory:
    """Tests for the walk_directory() module-level function."""

    def test_basic_walk(self, tmp_path):
        """walk_directory() should yield FileEntry objects."""
        _write(tmp_path / "a.py", "pass\n")
        entries = list(walk_directory(tmp_path))
        assert len(entries) == 1
        assert isinstance(entries[0], FileEntry)

    def test_include_languages_filter(self, tmp_path):
        """Only requested languages should appear."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.js", "x\n")
        entries = list(walk_directory(tmp_path, include_languages={"python"}))
        langs = {e.language for e in entries}
        assert langs == {"python"}

    def test_exclude_languages_filter(self, tmp_path):
        """Excluded languages should not appear."""
        _write(tmp_path / "a.py", "pass\n")
        _write(tmp_path / "b.js", "x\n")
        entries = list(walk_directory(tmp_path, exclude_languages={"javascript"}))
        langs = {e.language for e in entries}
        assert "javascript" not in langs
        assert "python" in langs


# ── Integration tests ────────────────────────────────────────────────


class TestIntegration:
    """End-to-end tests with a realistic project tree."""

    @pytest.fixture()
    def project(self, tmp_path):
        """Create and return a realistic project root."""
        _make_project(tmp_path)
        return tmp_path

    def test_discovers_all_source_files(self, project):
        """Walker should find exactly the expected source files."""
        walker = FileWalker(project)
        names = {e.relative_path.as_posix() for e in walker.walk()}
        # expected
        assert "src/main.py" in names
        assert "src/utils.py" in names
        assert "lib/helper.js" in names
        assert "lib/types.ts" in names
        assert "tests/test_main.py" in names
        assert "Dockerfile" in names
        assert "Makefile" in names
        # must NOT appear
        assert "README.txt" not in names
        assert "node_modules/pkg/index.js" not in names
        assert ".git/config" not in names

    def test_binary_detection_in_project(self, project):
        """data.bin should not appear because it has no code extension."""
        walker = FileWalker(project)
        names = {e.relative_path.name for e in walker.walk()}
        assert "data.bin" not in names

    def test_binary_flag_set_on_binary_code_file(self, tmp_path):
        """A .py file that is actually binary should have is_binary=True."""
        f = tmp_path / "tricky.py"
        f.write_bytes(b"\x00" * 100)
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        assert len(entries) == 1
        assert entries[0].is_binary is True

    def test_language_counts_realistic(self, project):
        """count_by_language should reflect the realistic project layout."""
        walker = FileWalker(project)
        counts = walker.count_by_language()
        assert counts.get("python", 0) == 3  # main.py, utils.py, test_main.py
        assert counts.get("javascript", 0) == 1  # helper.js
        assert counts.get("typescript", 0) == 1  # types.ts
        assert counts.get("dockerfile", 0) == 1
        assert counts.get("makefile", 0) == 1

    def test_include_filter_integration(self, project):
        """include_languages should restrict results across the full tree."""
        walker = FileWalker(project, include_languages={"python"})
        entries = list(walker.walk())
        assert all(e.language == "python" for e in entries)
        assert len(entries) == 3

    def test_exclude_filter_integration(self, project):
        """exclude_languages should drop matching files across the tree."""
        walker = FileWalker(project, exclude_languages={"python"})
        entries = list(walker.walk())
        assert all(e.language != "python" for e in entries)
        # helper.js, types.ts, Dockerfile, Makefile
        assert len(entries) == 4

    def test_walk_files_returns_absolute_paths(self, project):
        """walk_files() should return absolute paths."""
        walker = FileWalker(project)
        for p in walker.walk_files():
            assert p.is_absolute()

    def test_deeply_nested_files(self, tmp_path):
        """Files several levels deep should still be discovered."""
        _write(tmp_path / "a" / "b" / "c" / "d" / "deep.py", "pass\n")
        walker = FileWalker(tmp_path)
        entries = list(walker.walk())
        assert len(entries) == 1
        assert entries[0].relative_path == Path("a/b/c/d/deep.py")

    def test_gitignore_respected(self, tmp_path):
        """A .gitignore in the project root should be honoured."""
        _write(tmp_path / ".gitignore", "secret/\n")
        _write(tmp_path / "app.py", "pass\n")
        _write(tmp_path / "secret" / "key.py", "KEY='xxx'\n")
        walker = FileWalker(tmp_path)
        names = {e.relative_path.as_posix() for e in walker.walk()}
        assert "app.py" in names
        assert "secret/key.py" not in names

    def test_qodeignore_respected(self, tmp_path):
        """A .qodeignore file should add extra patterns."""
        _write(tmp_path / ".qodeignore", "generated/\n")
        _write(tmp_path / "app.py", "pass\n")
        _write(tmp_path / "generated" / "out.py", "# auto\n")
        walker = FileWalker(tmp_path)
        names = {e.relative_path.as_posix() for e in walker.walk()}
        assert "app.py" in names
        assert "generated/out.py" not in names
