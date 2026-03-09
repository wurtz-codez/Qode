"""Filesystem discovery with ignore-pattern support.

Ported from GitNexus ``filesystem-walker.ts`` (~121 lines → Python).
Implements recursive directory walk, respecting .gitignore and .qodeignore.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from qode.core.ignore import IgnoreService

# Supported programming language extensions
CODE_EXTENSIONS: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyi": "python",
    # JavaScript/TypeScript
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # Java
    ".java": "java",
    # C/C++
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    # C#
    ".cs": "csharp",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rust",
    # Ruby
    ".rb": "ruby",
    # PHP
    ".php": "php",
    # Swift
    ".swift": "swift",
    # Kotlin
    ".kt": "kotlin",
    ".kts": "kotlin",
    # Scala
    ".scala": "scala",
    # R
    ".r": "r",
    # Perl
    ".pl": "perl",
    ".pm": "perl",
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    # SQL
    ".sql": "sql",
    # HTML
    ".html": "html",
    ".htm": "html",
    # CSS
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    # Vue
    ".vue": "vue",
    # Svelte
    ".svelte": "svelte",
    # YAML
    ".yaml": "yaml",
    ".yml": "yaml",
    # JSON
    ".json": "json",
    # XML
    ".xml": "xml",
    # Markdown
    ".md": "markdown",
    # Dockerfile
    "Dockerfile": "dockerfile",
}


@dataclass(frozen=True)
class FileEntry:
    """Represents a discovered file with metadata.

    Attributes:
        path: Absolute path to the file
        relative_path: Path relative to the root directory
        extension: File extension (including dot)
        language: Detected programming language
        size: File size in bytes
        is_binary: Whether the file is binary
    """

    path: Path
    relative_path: Path
    extension: str
    language: str | None
    size: int
    is_binary: bool


class FileWalker:
    """Recursively walks a directory tree, filtering ignored files.

    Supports language filtering to only include code files.
    """

    def __init__(
        self,
        root: Path | str,
        ignore_service: IgnoreService | None = None,
        include_languages: set[str] | None = None,
        exclude_languages: set[str] | None = None,
    ) -> None:
        """Initialize the file walker.

        Args:
            root: Root directory to walk
            ignore_service: IgnoreService for filtering (auto-created if None)
            include_languages: Set of languages to include (None = all)
            exclude_languages: Set of languages to exclude (None = none)
        """
        self.root = Path(root).resolve()
        self.ignore_service = ignore_service or IgnoreService(self.root)
        self.include_languages = include_languages
        self.exclude_languages = exclude_languages or set()

    def _detect_language(self, path: Path) -> str | None:
        """Detect programming language from file extension or name.

        Args:
            path: File path to check

        Returns:
            Language name or None if not a code file
        """
        # Check by extension
        ext = path.suffix.lower()
        if ext in CODE_EXTENSIONS:
            return CODE_EXTENSIONS[ext]

        # Check special filenames
        if path.name == "Dockerfile":
            return "dockerfile"
        if path.name == "Makefile":
            return "makefile"

        return None

    def _is_binary(self, path: Path) -> bool:
        """Check if a file is binary by reading first few bytes.

        Args:
            path: File path to check

        Returns:
            True if file appears to be binary
        """
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                # Check for null bytes - common in binary files
                if b"\x00" in chunk:
                    return True
                # Check for high ratio of non-text bytes
                text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)))
                non_text = sum(1 for byte in chunk if byte not in text_chars)
                if len(chunk) > 0 and non_text / len(chunk) > 0.3:
                    return True
        except OSError:
            return True

        return False

    def _should_include(self, path: Path) -> bool:
        """Check if a file should be included based on language filters.

        Args:
            path: File path to check

        Returns:
            True if file should be included
        """
        # Check if ignored
        if self.ignore_service.should_ignore(path):
            return False

        # Detect language
        language = self._detect_language(path)

        # No language detected - skip
        if language is None:
            return False

        # Check exclude list
        if language in self.exclude_languages:
            return False

        # Check include list (if specified)
        return not (self.include_languages and language not in self.include_languages)

    def walk(self) -> Iterator[FileEntry]:
        """Walk the directory tree and yield file entries.

        Yields:
            FileEntry for each discovered file
        """
        for root_dir, dirs, files in os.walk(self.root):
            root_path = Path(root_dir)

            # Filter ignored directories in-place to prevent traversal
            dirs[:] = [
                d for d in dirs if not self.ignore_service.should_ignore(root_path / d)
            ]

            for filename in files:
                file_path = root_path / filename

                try:
                    # Get file stats
                    stat = file_path.stat()
                    size = stat.st_size
                except OSError:
                    continue

                # Check if should include
                if not self._should_include(file_path):
                    continue

                # Get relative path
                try:
                    relative_path = file_path.relative_to(self.root)
                except ValueError:
                    relative_path = file_path

                # Detect language and binary
                language = self._detect_language(file_path)
                is_binary = self._is_binary(file_path) if size > 0 else False

                yield FileEntry(
                    path=file_path,
                    relative_path=relative_path,
                    extension=file_path.suffix.lower(),
                    language=language,
                    size=size,
                    is_binary=is_binary,
                )

    def walk_files(self) -> list[Path]:
        """Walk and return just the file paths.

        Returns:
            List of file paths
        """
        return [entry.path for entry in self.walk()]

    def count_files(self) -> int:
        """Count total number of files that would be walked.

        Returns:
            Number of files
        """
        return sum(1 for _ in self.walk())

    def count_by_language(self) -> dict[str, int]:
        """Count files grouped by language.

        Returns:
            Dictionary mapping language to file count
        """
        counts: dict[str, int] = {}
        for entry in self.walk():
            lang = entry.language or "unknown"
            counts[lang] = counts.get(lang, 0) + 1
        return counts


def walk_directory(
    root: Path | str,
    include_languages: set[str] | None = None,
    exclude_languages: set[str] | None = None,
) -> Iterator[FileEntry]:
    """Convenience function to walk a directory.

    Args:
        root: Root directory to walk
        include_languages: Set of languages to include (None = all)
        exclude_languages: Set of languages to exclude (None = none)

    Yields:
        FileEntry for each discovered file
    """
    walker = FileWalker(
        root=root,
        include_languages=include_languages,
        exclude_languages=exclude_languages,
    )
    yield from walker.walk()


# ----------------------------------------------------------------------
# CLI helpers (for testing)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m qode.core.walker <path>")
        sys.exit(1)

    root = Path(sys.argv[1])
    walker = FileWalker(root)

    print(f"Walking: {root}")
    print("-" * 60)

    total = 0
    by_lang = {}

    for entry in walker.walk():
        total += 1
        lang = entry.language or "unknown"
        by_lang[lang] = by_lang.get(lang, 0) + 1
        print(f"  {entry.relative_path} ({lang})")

    print("-" * 60)
    print(f"Total files: {total}")
    print("\nBy language:")
    for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
        print(f"  {lang}: {count}")
