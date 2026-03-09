"""Tests for the IgnoreService (.gitignore + .qodeignore pattern matching)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qode.core.ignore import IgnoreService, create_ignore_service

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(tmp_path):
    """Return an IgnoreService rooted at a bare temp directory."""
    return IgnoreService(tmp_path)


@pytest.fixture()
def svc_with_gitignore(tmp_path):
    """Return an IgnoreService whose root contains a .gitignore."""
    (tmp_path / ".gitignore").write_text("*.tmp\nsecrets/\n", encoding="utf-8")
    return IgnoreService(tmp_path)


@pytest.fixture()
def svc_with_qodeignore(tmp_path):
    """Return an IgnoreService whose root contains a .qodeignore."""
    (tmp_path / ".qodeignore").write_text("*.dat\nreports/\n", encoding="utf-8")
    return IgnoreService(tmp_path)


@pytest.fixture()
def svc_with_both(tmp_path):
    """Return an IgnoreService with both .gitignore and .qodeignore."""
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (tmp_path / ".qodeignore").write_text("*.dat\n", encoding="utf-8")
    return IgnoreService(tmp_path)


# ---------------------------------------------------------------------------
# Default pattern tests
# ---------------------------------------------------------------------------


class TestDefaultPatterns:
    """Default built-in patterns should be active even without ignore files."""

    def test_git_directory_ignored(self, svc):
        """The .git directory is ignored by default."""
        assert svc.should_ignore(".git") is True

    def test_node_modules_ignored(self, svc):
        """The node_modules directory is ignored by default."""
        assert svc.should_ignore("node_modules") is True

    def test_pycache_ignored(self, svc):
        """The __pycache__ directory is ignored by default."""
        assert svc.should_ignore("__pycache__") is True

    def test_venv_ignored(self, svc):
        """The .venv directory is ignored by default."""
        assert svc.should_ignore(".venv") is True

    def test_pyc_files_ignored(self, svc):
        """Compiled Python files (*.pyc) are ignored by default."""
        assert svc.should_ignore("foo.pyc") is True

    def test_log_files_ignored(self, svc):
        """Log files (*.log) are ignored by default."""
        assert svc.should_ignore("server.log") is True

    def test_ds_store_ignored(self, svc):
        """.DS_Store is ignored by default."""
        assert svc.should_ignore(".DS_Store") is True

    def test_normal_source_not_ignored(self, svc):
        """Regular source files should not be ignored."""
        assert svc.should_ignore("main.py") is False
        assert svc.should_ignore("src/app.ts") is False
        assert svc.should_ignore("README.md") is False


# ---------------------------------------------------------------------------
# .gitignore loading tests
# ---------------------------------------------------------------------------


class TestGitignoreLoading:
    """Patterns from .gitignore should be loaded and merged."""

    def test_custom_pattern_applied(self, svc_with_gitignore):
        """Custom *.tmp pattern from .gitignore is respected."""
        assert svc_with_gitignore.should_ignore("data.tmp") is True

    def test_directory_pattern_applied(self, svc_with_gitignore):
        """Directory pattern (trailing /) from .gitignore ignores children."""
        assert svc_with_gitignore.should_ignore("secrets/key.pem") is True

    def test_missing_gitignore_no_error(self, svc):
        """IgnoreService works fine when no .gitignore exists."""
        assert svc.should_ignore("main.py") is False

    def test_default_patterns_still_active(self, svc_with_gitignore):
        """Default patterns remain active alongside .gitignore patterns."""
        assert svc_with_gitignore.should_ignore("node_modules") is True


# ---------------------------------------------------------------------------
# .qodeignore loading tests
# ---------------------------------------------------------------------------


class TestQodeignoreLoading:
    """Patterns from .qodeignore should be loaded and merged."""

    def test_custom_pattern_applied(self, svc_with_qodeignore):
        """Custom *.dat pattern from .qodeignore is respected."""
        assert svc_with_qodeignore.should_ignore("dump.dat") is True

    def test_directory_pattern_applied(self, svc_with_qodeignore):
        """Directory pattern (trailing /) from .qodeignore ignores children."""
        assert svc_with_qodeignore.should_ignore("reports/q1.pdf") is True

    def test_missing_qodeignore_no_error(self, svc):
        """IgnoreService works fine when no .qodeignore exists."""
        assert svc.should_ignore("main.py") is False

    def test_combines_with_gitignore(self, svc_with_both):
        """Both .gitignore and .qodeignore patterns are active."""
        assert svc_with_both.should_ignore("file.tmp") is True
        assert svc_with_both.should_ignore("file.dat") is True
        assert svc_with_both.should_ignore("file.py") is False


# ---------------------------------------------------------------------------
# should_ignore method tests
# ---------------------------------------------------------------------------


class TestShouldIgnore:
    """Edge cases and path handling for should_ignore."""

    def test_relative_string_path(self, svc):
        """Relative string paths are matched correctly."""
        assert svc.should_ignore("node_modules") is True
        assert svc.should_ignore("src/app.py") is False

    def test_relative_path_object(self, svc):
        """Relative Path objects are matched correctly."""
        assert svc.should_ignore(Path("node_modules")) is True
        assert svc.should_ignore(Path("src/app.py")) is False

    def test_absolute_path_under_root(self, tmp_path):
        """Absolute paths under root are converted to relative and matched."""
        svc = IgnoreService(tmp_path)
        abs_path = tmp_path / "node_modules"
        assert svc.should_ignore(abs_path) is True

    def test_absolute_source_not_ignored(self, tmp_path):
        """Absolute path to a normal file under root is not ignored."""
        svc = IgnoreService(tmp_path)
        abs_path = tmp_path / "src" / "main.py"
        assert svc.should_ignore(abs_path) is False

    def test_child_of_ignored_parent(self, svc):
        """Files nested under an ignored directory are also ignored."""
        assert svc.should_ignore("node_modules/package/index.js") is True
        assert svc.should_ignore("__pycache__/foo.cpython-312.pyc") is True

    def test_path_outside_root_no_crash(self, tmp_path):
        """Paths outside root raise no error (ValueError is caught)."""
        svc = IgnoreService(tmp_path)
        outside = Path("/some/completely/other/path/main.py")
        # Should not raise; result depends on patterns but must not crash.
        result = svc.should_ignore(outside)
        assert isinstance(result, bool)

    def test_none_matcher_returns_false(self, tmp_path):
        """If _matcher is None, should_ignore returns False."""
        svc = IgnoreService(tmp_path)
        svc._matcher = None
        assert svc.should_ignore("node_modules") is False


# ---------------------------------------------------------------------------
# filter_paths tests
# ---------------------------------------------------------------------------


class TestFilterPaths:
    """filter_paths should return only non-ignored paths."""

    def test_filters_ignored_paths(self, svc):
        """Ignored paths are removed from the result list."""
        paths = ["main.py", "node_modules", "src/util.py", ".DS_Store"]
        result = svc.filter_paths(paths)
        assert result == [Path("main.py"), Path("src/util.py")]

    def test_empty_input(self, svc):
        """Empty input yields empty output."""
        assert svc.filter_paths([]) == []

    def test_all_ignored(self, svc):
        """If every path is ignored, result is empty."""
        paths = ["node_modules", ".git", "__pycache__"]
        assert svc.filter_paths(paths) == []

    def test_none_ignored(self, svc):
        """If no path is ignored, all are returned."""
        paths = ["main.py", "lib/helpers.py"]
        result = svc.filter_paths(paths)
        assert result == [Path("main.py"), Path("lib/helpers.py")]

    def test_returns_path_objects(self, svc):
        """Returned items are Path objects regardless of input type."""
        result = svc.filter_paths(["main.py"])
        assert all(isinstance(p, Path) for p in result)


# ---------------------------------------------------------------------------
# matches_glob tests
# ---------------------------------------------------------------------------


class TestMatchesGlob:
    """matches_glob should detect glob metacharacters."""

    def test_star_pattern(self, svc):
        """Pattern containing * is recognized as a glob."""
        assert svc.matches_glob("*.py") is True

    def test_question_mark_pattern(self, svc):
        """Pattern containing ? is recognized as a glob."""
        assert svc.matches_glob("file?.txt") is True

    def test_bracket_pattern(self, svc):
        """Pattern containing [ is recognized as a glob."""
        assert svc.matches_glob("[abc].txt") is True

    def test_plain_string(self, svc):
        """Plain string without metacharacters is not a glob."""
        assert svc.matches_glob("README.md") is False

    def test_none_matcher_returns_false(self, tmp_path):
        """If _matcher is None, matches_glob returns False."""
        svc = IgnoreService(tmp_path)
        svc._matcher = None
        assert svc.matches_glob("*.py") is False


# ---------------------------------------------------------------------------
# create_ignore_service factory tests
# ---------------------------------------------------------------------------


class TestCreateIgnoreService:
    """Factory function should return a configured IgnoreService."""

    def test_returns_instance(self, tmp_path):
        """create_ignore_service returns an IgnoreService."""
        svc = create_ignore_service(tmp_path)
        assert isinstance(svc, IgnoreService)

    def test_root_resolved(self, tmp_path):
        """The returned service has a resolved root path."""
        svc = create_ignore_service(tmp_path)
        assert svc.root == tmp_path.resolve()

    def test_accepts_string_path(self, tmp_path):
        """Factory accepts a string path as well as a Path."""
        svc = create_ignore_service(str(tmp_path))
        assert isinstance(svc, IgnoreService)


# ---------------------------------------------------------------------------
# _read_ignore_file tests
# ---------------------------------------------------------------------------


class TestReadIgnoreFile:
    """Internal helper that reads and filters lines from ignore files."""

    def test_comments_skipped(self, tmp_path):
        """Lines starting with # are treated as comments and skipped."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text(
            "# This is a comment\n*.tmp\n# Another comment\n",
            encoding="utf-8",
        )
        svc = IgnoreService(tmp_path)
        # The comment lines should not be interpreted as patterns.
        assert svc.should_ignore("# This is a comment") is False
        assert svc.should_ignore("data.tmp") is True

    def test_empty_lines_skipped(self, tmp_path):
        """Blank lines in ignore files are harmless."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("\n\n*.tmp\n\n", encoding="utf-8")
        svc = IgnoreService(tmp_path)
        assert svc.should_ignore("data.tmp") is True
        assert svc.should_ignore("main.py") is False

    def test_nonexistent_file_no_error(self, tmp_path):
        """Calling _read_ignore_file on a missing path yields nothing."""
        svc = IgnoreService(tmp_path)
        result = list(svc._read_ignore_file(tmp_path / "nonexistent"))
        assert result == []

    def test_whitespace_stripped(self, tmp_path):
        """Leading/trailing whitespace on pattern lines is stripped."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("  *.tmp  \n  *.bak  \n", encoding="utf-8")
        svc = IgnoreService(tmp_path)
        assert svc.should_ignore("data.tmp") is True
        assert svc.should_ignore("backup.bak") is True
