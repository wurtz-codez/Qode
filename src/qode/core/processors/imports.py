"""12-language import resolution engine.

Ported from ``import-processor.ts`` (~1132 lines -> Python).
Resolves pre-extracted ``ExtractedImport`` entries to concrete file paths
and emits ``ParsedRelationship`` edges (type ``"IMPORTS"``) into the
aggregate ``ParseResult``.

Supported languages: TypeScript, JavaScript, Python, Java, Kotlin, Go,
Rust, C, C++, C#, PHP, Swift (plus TSX as a TypeScript variant).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from qode.core.parsers.parser import generate_id
from qode.data.schemas import ExtractedImport, ParsedRelationship, ParseResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESOLVE_CACHE_CAP = 100_000

EXTENSIONS: list[str] = [
    "",
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    "/index.tsx",
    "/index.ts",
    "/index.jsx",
    "/index.js",
    ".py",
    "/__init__.py",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".hxx",
    ".hh",
    ".cs",
    ".go",
    ".rs",
    "/mod.rs",
    ".php",
    ".phtml",
    ".swift",
]

KOTLIN_EXTENSIONS: list[str] = [".kt", ".kts"]


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TsconfigPaths:
    """TypeScript path-alias configuration from ``tsconfig.json``."""

    aliases: dict[str, str]
    base_url: str


@dataclass(frozen=True)
class GoModuleConfig:
    """Go module configuration from ``go.mod``."""

    module_path: str


@dataclass(frozen=True)
class ComposerConfig:
    """PHP Composer PSR-4 autoload configuration."""

    psr4: dict[str, str]


@dataclass(frozen=True)
class SwiftPackageConfig:
    """Swift package target directory mapping."""

    targets: dict[str, str]


# ---------------------------------------------------------------------------
# SuffixIndex
# ---------------------------------------------------------------------------


@dataclass
class SuffixIndex:
    """Suffix-based file lookup index for fast import resolution.

    Provides three lookup strategies:

    * **exact** — case-sensitive suffix match.
    * **insensitive** — lowercased suffix match (fallback).
    * **dir** — directory-suffix + extension lookup for JVM wildcards.
    """

    exact_map: dict[str, str] = field(default_factory=dict)
    lower_map: dict[str, str] = field(default_factory=dict)
    dir_map: dict[str, list[str]] = field(default_factory=dict)

    def get(self, suffix: str) -> str | None:
        """Case-sensitive suffix lookup."""
        return self.exact_map.get(suffix)

    def get_insensitive(self, suffix: str) -> str | None:
        """Case-insensitive suffix lookup."""
        return self.lower_map.get(suffix.lower())

    def get_files_in_dir(
        self,
        dir_suffix: str,
        extension: str,
    ) -> list[str]:
        """Return files matching a directory suffix and extension."""
        return self.dir_map.get(f"{dir_suffix}:{extension}", [])


def build_suffix_index(
    normalized_file_list: list[str],
    all_file_list: list[str],
) -> SuffixIndex:
    """Build a ``SuffixIndex`` from parallel file-path lists.

    Args:
        normalized_file_list: Forward-slash normalised paths.
        all_file_list: Original file paths (may use OS separators).

    Returns:
        A populated ``SuffixIndex``.
    """
    exact_map: dict[str, str] = {}
    lower_map: dict[str, str] = {}
    dir_map: dict[str, list[str]] = {}

    for i, normalized in enumerate(normalized_file_list):
        original = all_file_list[i]
        parts = normalized.split("/")

        # Build suffix entries for every trailing segment combination.
        for j in range(len(parts) - 1, -1, -1):
            suffix = "/".join(parts[j:])
            if suffix not in exact_map:
                exact_map[suffix] = original
            lower = suffix.lower()
            if lower not in lower_map:
                lower_map[lower] = original

        # Build directory map for JVM wildcard resolution.
        last_slash = normalized.rfind("/")
        if last_slash >= 0:
            dir_parts = parts[:-1]
            file_name = parts[-1]
            dot_idx = file_name.rfind(".")
            ext = file_name[dot_idx:] if dot_idx >= 0 else ""

            for j in range(len(dir_parts) - 1, -1, -1):
                dir_suffix = "/".join(dir_parts[j:])
                key = f"{dir_suffix}:{ext}"
                if key not in dir_map:
                    dir_map[key] = []
                dir_map[key].append(original)

    return SuffixIndex(
        exact_map=exact_map,
        lower_map=lower_map,
        dir_map=dir_map,
    )


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------


def load_tsconfig_paths(repo_root: str) -> TsconfigPaths | None:
    """Load TypeScript path aliases from the repository root.

    Tries ``tsconfig.json``, ``tsconfig.app.json``, and
    ``tsconfig.base.json`` in order.  Strips single-line (``//``) and
    block (``/* */``) comments before parsing JSON.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A ``TsconfigPaths`` instance, or ``None`` if no aliases found.
    """
    candidates = [
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.base.json",
    ]
    for filename in candidates:
        try:
            tsconfig_path = os.path.join(repo_root, filename)
            raw = Path(tsconfig_path).read_text(encoding="utf-8")
            # Strip single-line and block comments.
            stripped = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
            stripped = re.sub(r"/\*[\s\S]*?\*/", "", stripped)
            tsconfig = json.loads(stripped)
            compiler_options = tsconfig.get("compilerOptions")
            if not compiler_options or "paths" not in compiler_options:
                continue
            base_url: str = compiler_options.get("baseUrl", ".")
            aliases: dict[str, str] = {}
            paths: dict[str, list[str]] = compiler_options["paths"]
            for pattern, targets in paths.items():
                if not isinstance(targets, list) or len(targets) == 0:
                    continue
                target = targets[0]
                alias_prefix = pattern[:-1] if pattern.endswith("/*") else pattern
                target_prefix = target[:-1] if target.endswith("/*") else target
                aliases[alias_prefix] = target_prefix
            if aliases:
                return TsconfigPaths(
                    aliases=aliases,
                    base_url=base_url,
                )
        except Exception:
            continue
    return None


def load_go_module_path(repo_root: str) -> GoModuleConfig | None:
    """Load Go module path from ``go.mod``.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A ``GoModuleConfig`` instance, or ``None`` if not found.
    """
    try:
        go_mod_path = os.path.join(repo_root, "go.mod")
        content = Path(go_mod_path).read_text(encoding="utf-8")
        match = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
        if match:
            return GoModuleConfig(module_path=match.group(1))
    except Exception:
        pass
    return None


def load_composer_config(repo_root: str) -> ComposerConfig | None:
    """Load PHP Composer PSR-4 autoload configuration.

    Merges both ``autoload`` and ``autoload-dev`` PSR-4 mappings.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A ``ComposerConfig`` instance, or ``None`` if not found.
    """
    try:
        composer_path = os.path.join(repo_root, "composer.json")
        raw = Path(composer_path).read_text(encoding="utf-8")
        composer = json.loads(raw)
        psr4_raw: dict[str, str] = composer.get("autoload", {}).get("psr-4", {})
        psr4_dev: dict[str, str] = composer.get("autoload-dev", {}).get("psr-4", {})
        merged = {**psr4_raw, **psr4_dev}
        psr4: dict[str, str] = {}
        for ns, dir_val in merged.items():
            ns_norm = ns.rstrip("\\")
            dir_norm = dir_val.replace("\\", "/").rstrip("/")
            psr4[ns_norm] = dir_norm
        return ComposerConfig(psr4=psr4)
    except Exception:
        return None


def load_swift_package_config(
    repo_root: str,
) -> SwiftPackageConfig | None:
    """Discover Swift package targets by scanning source directories.

    Checks ``Sources``, ``Package/Sources``, and ``src`` for
    subdirectories representing Swift targets.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A ``SwiftPackageConfig`` instance, or ``None`` if none found.
    """
    targets: dict[str, str] = {}
    source_dirs = ["Sources", "Package/Sources", "src"]
    for source_dir in source_dirs:
        try:
            full_path = os.path.join(repo_root, source_dir)
            entries = os.scandir(full_path)
            for entry in entries:
                if entry.is_dir():
                    targets[entry.name] = source_dir + "/" + entry.name
        except Exception:
            continue
    if targets:
        return SwiftPackageConfig(targets=targets)
    return None


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def try_resolve_with_extensions(
    base_path: str,
    all_files: set[str],
) -> str | None:
    """Try appending each known extension to *base_path*.

    Args:
        base_path: The base file path (without extension).
        all_files: Set of all known file paths in the repository.

    Returns:
        The first matching file path, or ``None``.
    """
    for ext in EXTENSIONS:
        candidate = base_path + ext
        if candidate in all_files:
            return candidate
    return None


def suffix_resolve(
    path_parts: list[str],
    normalized_file_list: list[str],
    all_file_list: list[str],
    index: SuffixIndex,
) -> str | None:
    """Resolve a path by trying suffix matches against the index.

    Iterates over increasingly shorter suffixes of *path_parts* and
    tries each known extension.

    Args:
        path_parts: Segments of the import path.
        normalized_file_list: Normalised file paths (unused when index
            is provided, kept for API parity).
        all_file_list: Original file paths (unused when index is
            provided, kept for API parity).
        index: Pre-built suffix index for fast lookups.

    Returns:
        The resolved file path, or ``None``.
    """
    for i in range(len(path_parts)):
        suffix = "/".join(path_parts[i:])
        for ext in EXTENSIONS:
            suffix_with_ext = suffix + ext
            result = index.get(suffix_with_ext)
            if result is None:
                result = index.get_insensitive(suffix_with_ext)
            if result is not None:
                return result
    return None


# ---------------------------------------------------------------------------
# Rust resolution
# ---------------------------------------------------------------------------


def _try_rust_module_path(
    module_path: str,
    all_files: set[str],
) -> str | None:
    """Try Rust module path conventions (``.rs``, ``mod.rs``, ``lib.rs``).

    Also checks the parent directory as a fallback.

    Args:
        module_path: The module path to resolve.
        all_files: Set of all known file paths.

    Returns:
        The resolved file path, or ``None``.
    """
    if module_path + ".rs" in all_files:
        return module_path + ".rs"
    if module_path + "/mod.rs" in all_files:
        return module_path + "/mod.rs"
    if module_path + "/lib.rs" in all_files:
        return module_path + "/lib.rs"
    last_slash = module_path.rfind("/")
    if last_slash > 0:
        parent_path = module_path[:last_slash]
        if parent_path + ".rs" in all_files:
            return parent_path + ".rs"
        if parent_path + "/mod.rs" in all_files:
            return parent_path + "/mod.rs"
    return None


def resolve_rust_import(
    current_file: str,
    import_path: str,
    all_files: set[str],
) -> str | None:
    """Resolve a Rust import path.

    Handles ``crate::``, ``super::``, ``self::``, and external
    crate-style paths.

    Args:
        current_file: The file containing the import statement.
        import_path: The raw import path (e.g. ``"crate::foo::bar"``).
        all_files: Set of all known file paths.

    Returns:
        The resolved file path, or ``None``.
    """
    if import_path.startswith("crate::"):
        rust_path = import_path[7:].replace("::", "/")
        from_src = _try_rust_module_path("src/" + rust_path, all_files)
        if from_src is not None:
            return from_src
        from_root = _try_rust_module_path(rust_path, all_files)
        if from_root is not None:
            return from_root
        return None

    if import_path.startswith("super::"):
        current_dir = current_file.split("/")[:-1]
        current_dir.pop()
        rust_path = import_path[7:].replace("::", "/")
        full_path = "/".join([*current_dir, rust_path])
        return _try_rust_module_path(full_path, all_files)

    if import_path.startswith("self::"):
        current_dir = current_file.split("/")[:-1]
        rust_path = import_path[6:].replace("::", "/")
        full_path = "/".join([*current_dir, rust_path])
        return _try_rust_module_path(full_path, all_files)

    if "::" in import_path:
        rust_path = import_path.replace("::", "/")
        return _try_rust_module_path(rust_path, all_files)

    return None


# ---------------------------------------------------------------------------
# JVM resolution (Java + Kotlin)
# ---------------------------------------------------------------------------


def resolve_jvm_wildcard(
    import_path: str,
    normalized_file_list: list[str],
    all_file_list: list[str],
    extensions: list[str],
    index: SuffixIndex,
) -> list[str]:
    """Resolve a JVM wildcard import (e.g. ``com.example.models.*``).

    Uses the directory map in the suffix index to find all files within
    the package directory matching the given extensions.

    Args:
        import_path: The raw import path ending in ``.*``.
        normalized_file_list: Normalised file paths (unused, API parity).
        all_file_list: Original file paths (unused, API parity).
        extensions: File extensions to match (e.g. ``[".java"]``).
        index: Pre-built suffix index.

    Returns:
        List of matching file paths.
    """
    package_path = import_path[:-2].replace(".", "/")
    candidates: list[str] = []
    for ext in extensions:
        candidates.extend(index.get_files_in_dir(package_path, ext))

    package_suffix = "/" + package_path + "/"
    result: list[str] = []
    for f in candidates:
        normalized = f.replace("\\", "/")
        idx = normalized.find(package_suffix)
        if idx < 0:
            continue
        after_pkg = normalized[idx + len(package_suffix) :]
        if "/" not in after_pkg:
            result.append(f)
    return result


def resolve_jvm_member_import(
    import_path: str,
    normalized_file_list: list[str],
    all_file_list: list[str],
    extensions: list[str],
    index: SuffixIndex,
) -> str | None:
    """Resolve a JVM member import to its containing class file.

    If the last segment is lowercase, all-uppercase (a constant), or
    ``*``, the import is treated as a member import and the penultimate
    segments form the class path.

    Args:
        import_path: Dot-separated import path.
        normalized_file_list: Normalised file paths (unused, API parity).
        all_file_list: Original file paths (unused, API parity).
        extensions: File extensions to match.
        index: Pre-built suffix index.

    Returns:
        The resolved file path, or ``None``.
    """
    segments = import_path.split(".")
    if len(segments) < 3:
        return None

    last_seg = segments[-1]
    is_wildcard = last_seg == "*"
    is_lowercase_start = len(last_seg) > 0 and last_seg[0].islower()
    is_all_upper = bool(re.match(r"^[A-Z_]+$", last_seg))

    if is_wildcard or is_lowercase_start or is_all_upper:
        class_path = "/".join(segments[:-1])
        for ext in extensions:
            class_suffix = class_path + ext
            result = index.get(class_suffix)
            if result is None:
                result = index.get_insensitive(class_suffix)
            if result is not None:
                return result
    return None


# ---------------------------------------------------------------------------
# Go resolution
# ---------------------------------------------------------------------------


def resolve_go_package(
    import_path: str,
    go_module: GoModuleConfig,
    normalized_file_list: list[str],
    all_file_list: list[str],
) -> list[str]:
    """Resolve a Go package import to all ``.go`` files in the package.

    Only resolves imports that belong to the current module (i.e. start
    with ``go_module.module_path``).  Test files (``_test.go``) are
    excluded.

    Args:
        import_path: The Go import path (e.g.
            ``"github.com/user/repo/pkg/util"``).
        go_module: The loaded Go module configuration.
        normalized_file_list: Normalised file paths.
        all_file_list: Original file paths.

    Returns:
        List of matching ``.go`` file paths.
    """
    if not import_path.startswith(go_module.module_path):
        return []

    relative_pkg = import_path[len(go_module.module_path) + 1 :]
    if not relative_pkg:
        return []

    pkg_suffix = "/" + relative_pkg + "/"
    matches: list[str] = []

    for i, normalized in enumerate(normalized_file_list):
        if (
            pkg_suffix in normalized
            and normalized.endswith(".go")
            and not normalized.endswith("_test.go")
        ):
            after_pkg_idx = normalized.index(pkg_suffix) + len(pkg_suffix)
            after_pkg = normalized[after_pkg_idx:]
            if "/" not in after_pkg:
                matches.append(all_file_list[i])

    return matches


# ---------------------------------------------------------------------------
# PHP resolution
# ---------------------------------------------------------------------------


def resolve_php_import(
    import_path: str,
    composer_config: ComposerConfig | None,
    all_files: set[str],
    normalized_file_list: list[str],
    all_file_list: list[str],
    index: SuffixIndex,
) -> str | None:
    """Resolve a PHP namespace import to a file path.

    Uses PSR-4 autoloading rules from ``composer.json`` when available,
    then falls back to suffix-based resolution.

    Args:
        import_path: The PHP namespace import (e.g.
            ``"App\\Models\\User"``).
        composer_config: Loaded Composer configuration, or ``None``.
        all_files: Set of all known file paths.
        normalized_file_list: Normalised file paths.
        all_file_list: Original file paths.
        index: Pre-built suffix index.

    Returns:
        The resolved file path, or ``None``.
    """
    normalized = import_path.replace("\\", "/")

    if composer_config is not None:
        # Sort by namespace prefix length descending for longest match.
        sorted_psr4 = sorted(
            composer_config.psr4.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for ns_prefix, dir_prefix in sorted_psr4:
            ns_prefix_slash = ns_prefix.replace("\\", "/")
            if (
                normalized.startswith(ns_prefix_slash + "/")
                or normalized == ns_prefix_slash
            ):
                remainder = normalized[len(ns_prefix_slash) :]
                if remainder.startswith("/"):
                    remainder = remainder[1:]
                file_path = dir_prefix + ("/" + remainder if remainder else "") + ".php"
                if file_path in all_files:
                    return file_path
                result = index.get_insensitive(file_path)
                if result is not None:
                    return result

    path_parts = [p for p in normalized.split("/") if p]
    return suffix_resolve(path_parts, normalized_file_list, all_file_list, index)


# ---------------------------------------------------------------------------
# Core single-file resolver
# ---------------------------------------------------------------------------


def resolve_import_path(
    current_file: str,
    import_path: str,
    all_files: set[str],
    all_file_list: list[str],
    normalized_file_list: list[str],
    resolve_cache: dict[str, str | None],
    language: str,
    tsconfig_paths: TsconfigPaths | None,
    index: SuffixIndex,
) -> str | None:
    """Resolve a single import path to a concrete file path.

    This is the core resolver that handles path aliases (TypeScript),
    Rust module paths, relative imports, and generic suffix-based
    resolution.  Results are memoised in *resolve_cache* with LRU-style
    eviction when the cache reaches ``RESOLVE_CACHE_CAP``.

    Args:
        current_file: The file containing the import statement.
        import_path: The raw import path to resolve.
        all_files: Set of all known file paths.
        all_file_list: Sorted list of all file paths.
        normalized_file_list: Normalised versions of *all_file_list*.
        resolve_cache: Mutable cache for memoisation.
        language: Language key of the importing file.
        tsconfig_paths: TypeScript path-alias config, or ``None``.
        index: Pre-built suffix index.

    Returns:
        The resolved file path, or ``None``.
    """
    cache_key = f"{current_file}::{import_path}"

    if cache_key in resolve_cache:
        return resolve_cache[cache_key]

    def _cache(result: str | None) -> str | None:
        if len(resolve_cache) >= RESOLVE_CACHE_CAP:
            evict_count = int(RESOLVE_CACHE_CAP * 0.2)
            keys_iter = iter(resolve_cache)
            keys_to_evict = []
            for _ in range(evict_count):
                try:
                    keys_to_evict.append(next(keys_iter))
                except StopIteration:
                    break
            for k in keys_to_evict:
                del resolve_cache[k]
        resolve_cache[cache_key] = result
        return result

    # TS/JS: rewrite path aliases
    if (
        language in {"typescript", "javascript", "tsx"}
        and tsconfig_paths is not None
        and not import_path.startswith(".")
    ):
        for alias_prefix, target_prefix in tsconfig_paths.aliases.items():
            if import_path.startswith(alias_prefix):
                remainder = import_path[len(alias_prefix) :]
                if tsconfig_paths.base_url == ".":
                    rewritten = target_prefix + remainder
                else:
                    rewritten = (
                        tsconfig_paths.base_url + "/" + target_prefix + remainder
                    )
                resolved = try_resolve_with_extensions(rewritten, all_files)
                if resolved is not None:
                    return _cache(resolved)
                parts = [p for p in rewritten.split("/") if p]
                suffix_result = suffix_resolve(
                    parts,
                    normalized_file_list,
                    all_file_list,
                    index,
                )
                if suffix_result is not None:
                    return _cache(suffix_result)

    # Rust: convert module path syntax
    if language == "rust":
        rust_result = resolve_rust_import(current_file, import_path, all_files)
        if rust_result is not None:
            return _cache(rust_result)

    # Generic relative import resolution
    current_dir = current_file.split("/")[:-1]
    parts = import_path.split("/")
    for part in parts:
        if part == ".":
            continue
        if part == "..":
            if current_dir:
                current_dir.pop()
        else:
            current_dir.append(part)
    base_path = "/".join(current_dir)

    if import_path.startswith("."):
        resolved = try_resolve_with_extensions(base_path, all_files)
        return _cache(resolved)

    # Generic package/absolute import (suffix matching)
    if import_path.endswith(".*"):
        return _cache(None)

    path_like = import_path if "/" in import_path else import_path.replace(".", "/")
    path_parts = [p for p in path_like.split("/") if p]
    resolved = suffix_resolve(path_parts, normalized_file_list, all_file_list, index)
    return _cache(resolved)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_imports(
    parse_result: ParseResult,
    *,
    project_root: str = "",
) -> dict[str, set[str]]:
    """Resolve import statements across 12 languages.

    Iterates over ``parse_result.imports`` (pre-extracted
    ``ExtractedImport`` entries), resolves each to a concrete file path,
    and appends ``ParsedRelationship`` edges (type ``"IMPORTS"``,
    confidence ``1.0``) to ``parse_result.relationships``.

    Args:
        parse_result: Aggregate parse result with pre-extracted imports.
        project_root: Path to the repository root (for config file
            loading).

    Returns:
        Import map: ``{file_path: {resolved_import_path, ...}}``.
    """
    import_map: dict[str, set[str]] = {}

    if not parse_result.imports:
        return import_map

    # -- Collect all file paths -------------------------------------------
    import_file_paths = {imp.file_path for imp in parse_result.imports}
    all_file_list: list[str] = sorted(
        {node.properties.file_path for node in parse_result.nodes} | import_file_paths
    )

    # Normalised paths (forward slashes).
    normalized_file_list: list[str] = [fp.replace("\\", "/") for fp in all_file_list]

    all_files: set[str] = set(all_file_list)

    # -- Build suffix index -----------------------------------------------
    index = build_suffix_index(normalized_file_list, all_file_list)

    # -- Load config files ------------------------------------------------
    tsconfig_paths = load_tsconfig_paths(project_root) if project_root else None
    go_module = load_go_module_path(project_root) if project_root else None
    composer_config = load_composer_config(project_root) if project_root else None
    swift_package_config = (
        load_swift_package_config(project_root) if project_root else None
    )

    logger.debug(
        "Import resolution: %d imports, %d files, tsconfig=%s, "
        "go_mod=%s, composer=%s, swift=%s",
        len(parse_result.imports),
        len(all_file_list),
        tsconfig_paths is not None,
        go_module is not None,
        composer_config is not None,
        swift_package_config is not None,
    )

    # -- Resolve cache ----------------------------------------------------
    resolve_cache: dict[str, str | None] = {}

    # -- Helper to add an import edge -------------------------------------
    def add_import_edge(file_path: str, resolved_path: str) -> None:
        source_id = generate_id("File", file_path)
        target_id = generate_id("File", resolved_path)
        rel_id = generate_id("IMPORTS", f"{file_path}->{resolved_path}")
        parse_result.relationships.append(
            ParsedRelationship(
                id=rel_id,
                source_id=source_id,
                target_id=target_id,
                type="IMPORTS",
                confidence=1.0,
                reason="",
            )
        )
        if file_path not in import_map:
            import_map[file_path] = set()
        import_map[file_path].add(resolved_path)

    # -- Group imports by file --------------------------------------------
    imports_by_file: dict[str, list[ExtractedImport]] = {}
    for imp in parse_result.imports:
        imports_by_file.setdefault(imp.file_path, []).append(imp)

    # -- Resolve each import ----------------------------------------------
    for file_path, file_imports in imports_by_file.items():
        for imp in file_imports:
            raw_import_path = imp.raw_import_path
            language = imp.language

            # JVM (Java + Kotlin)
            if language in {"java", "kotlin"}:
                exts: list[str] = [".java"] if language == "java" else KOTLIN_EXTENSIONS

                if raw_import_path.endswith(".*"):
                    matched_files = resolve_jvm_wildcard(
                        raw_import_path,
                        normalized_file_list,
                        all_file_list,
                        exts,
                        index,
                    )
                    if len(matched_files) == 0 and language == "kotlin":
                        java_matches = resolve_jvm_wildcard(
                            raw_import_path,
                            normalized_file_list,
                            all_file_list,
                            [".java"],
                            index,
                        )
                        for m in java_matches:
                            add_import_edge(file_path, m)
                        if java_matches:
                            continue
                    for m in matched_files:
                        add_import_edge(file_path, m)
                    continue

                member_resolved = resolve_jvm_member_import(
                    raw_import_path,
                    normalized_file_list,
                    all_file_list,
                    exts,
                    index,
                )
                if member_resolved is None and language == "kotlin":
                    member_resolved = resolve_jvm_member_import(
                        raw_import_path,
                        normalized_file_list,
                        all_file_list,
                        [".java"],
                        index,
                    )
                if member_resolved is not None:
                    add_import_edge(file_path, member_resolved)
                    continue

            # Go
            if (
                language == "go"
                and go_module is not None
                and raw_import_path.startswith(go_module.module_path)
            ):
                pkg_files = resolve_go_package(
                    raw_import_path,
                    go_module,
                    normalized_file_list,
                    all_file_list,
                )
                if pkg_files:
                    for f in pkg_files:
                        add_import_edge(file_path, f)
                    continue

            # PHP — always continues (never falls through to generic)
            if language == "php":
                resolved = resolve_php_import(
                    raw_import_path,
                    composer_config,
                    all_files,
                    normalized_file_list,
                    all_file_list,
                    index,
                )
                if resolved is not None:
                    add_import_edge(file_path, resolved)
                continue

            # Swift — always continues (never falls through to generic)
            if language == "swift":
                if swift_package_config is not None:
                    target_dir = swift_package_config.targets.get(raw_import_path)
                    if target_dir is not None:
                        dir_prefix = target_dir + "/"
                        for fp in all_file_list:
                            if fp.startswith(dir_prefix) and fp.endswith(".swift"):
                                add_import_edge(file_path, fp)
                continue

            # Standard single-file resolution
            resolved_path = resolve_import_path(
                file_path,
                raw_import_path,
                all_files,
                all_file_list,
                normalized_file_list,
                resolve_cache,
                language,
                tsconfig_paths,
                index,
            )
            if resolved_path is not None:
                add_import_edge(file_path, resolved_path)

    logger.debug(
        "Import resolution complete: %d edges created across %d files",
        sum(len(v) for v in import_map.values()),
        len(import_map),
    )

    return import_map
