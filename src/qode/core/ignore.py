"""Ignore-pattern service (.gitignore + .qodeignore).

Ported from Qode ``ignore-service.ts`` (~239 lines → Python).
Uses ``pathspec`` for gitignore-style glob matching.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pathspec


class IgnoreService:
    """Handles .gitignore and .qodeignore pattern matching.

    Provides efficient filtering of files and directories that should be
    excluded from analysis based on ignore patterns.
    """

    def __init__(self, root: Path | str) -> None:
        """Initialize ignore service with a root directory.

        Args:
            root: Root directory to search for ignore files
        """
        self.root = Path(root).resolve()
        self._matcher: pathspec.PathSpec | None = None
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load and combine .gitignore and .qodeignore patterns."""
        patterns: list[str] = []

        # Default patterns to always ignore
        default_patterns = [
            # Version control
            ".git",
            ".svn",
            ".hg",
            ".bzr",
            # IDE and editor files
            ".vscode",
            ".idea",
            "*.swp",
            "*.swo",
            "*~",
            ".DS_Store",
            "Thumbs.db",
            # Build outputs
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            "node_modules",
            "dist",
            "build",
            "*.egg-info",
            # Coverage outputs
            ".coverage",
            "htmlcov",
            # Virtual environments
            ".venv",
            "venv",
            "env",
            # Logs
            "*.log",
        ]
        patterns.extend(default_patterns)

        # Load .gitignore if exists
        gitignore_path = self.root / ".gitignore"
        if gitignore_path.exists():
            patterns.extend(self._read_ignore_file(gitignore_path))

        # Load .qodeignore if exists (takes precedence)
        qodeignore_path = self.root / ".qodeignore"
        if qodeignore_path.exists():
            patterns.extend(self._read_ignore_file(qodeignore_path))

        # Create pathspec matcher
        self._matcher = pathspec.PathSpec.from_lines("gitignore", patterns)

    def _read_ignore_file(self, path: Path) -> Iterable[str]:
        """Read ignore file and yield non-empty, non-comment lines.

        Args:
            path: Path to ignore file

        Yields:
            Non-empty, non-comment pattern lines
        """
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith("#"):
                        yield line
        except OSError:
            # Silently ignore unreadable files
            pass

    def should_ignore(self, path: Path | str) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Path to check (relative or absolute)

        Returns:
            True if path matches any ignore pattern
        """
        if self._matcher is None:
            return False

        path = Path(path)

        # Convert to relative path if absolute
        try:
            if path.is_absolute():
                path = path.relative_to(self.root)
        except ValueError:
            # Path is not relative to root, check if it's outside
            pass

        # Check both the full path and individual parts
        path_str = str(path)

        # Check if any parent directory should be ignored
        parts = path.parts
        for i in range(len(parts)):
            partial = "/".join(parts[: i + 1])
            if self._matcher.match_file(partial):
                return True

        return self._matcher.match_file(path_str)

    def filter_paths(self, paths: Iterable[Path | str]) -> list[Path]:
        """Filter a list of paths, returning only non-ignored paths.

        Args:
            paths: Iterable of paths to filter

        Returns:
            List of paths that are not ignored
        """
        result: list[Path] = []
        for path in paths:
            path = Path(path)
            if not self.should_ignore(path):
                result.append(path)
        return result

    def matches_glob(self, pattern: str) -> bool:
        """Check if a pattern matches any file in the tree.

        Note: This is a simple implementation. For complex glob matching,
        use the pathspec match_file method directly.

        Args:
            pattern: Glob pattern to match

        Returns:
            True if pattern could match (simplified check)
        """
        if self._matcher is None:
            return False
        # Simple check - just see if pattern looks like a gitignore pattern
        return "*" in pattern or "?" in pattern or "[" in pattern


def create_ignore_service(root: Path | str) -> IgnoreService:
    """Factory function to create an IgnoreService.

    Args:
        root: Root directory to search for ignore files

    Returns:
        Configured IgnoreService instance
    """
    return IgnoreService(root)


# ----------------------------------------------------------------------
# CLI helpers (for testing)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m qode.core.ignore <path>")
        sys.exit(1)

    root = Path(sys.argv[1])
    ignore = IgnoreService(root)

    print(f"Ignore service initialized for: {root}")
    print(f"Testing paths in: {root}")

    # Walk and show ignored files
    for path in root.rglob("*"):
        if path.is_file() and ignore.should_ignore(path):
            print(f"IGNORED: {path.relative_to(root)}")
