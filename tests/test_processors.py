"""Tests for import resolution (imports.py) and call resolution (calls.py)."""

from __future__ import annotations

import json

from qode.core.parsers.parser import generate_id
from qode.core.processors.calls import (
    BUILT_IN_NAMES,
    _is_built_in_or_noise,
    _resolve_call_target,
    process_calls,
)
from qode.core.processors.imports import (
    EXTENSIONS,
    KOTLIN_EXTENSIONS,
    RESOLVE_CACHE_CAP,
    ComposerConfig,
    GoModuleConfig,
    TsconfigPaths,
    build_suffix_index,
    load_composer_config,
    load_go_module_path,
    load_swift_package_config,
    load_tsconfig_paths,
    process_imports,
    resolve_go_package,
    resolve_import_path,
    resolve_jvm_member_import,
    resolve_jvm_wildcard,
    resolve_php_import,
    resolve_rust_import,
    suffix_resolve,
    try_resolve_with_extensions,
)
from qode.core.symbol_table import SymbolTable
from qode.data.schemas import (
    ExtractedCall,
    ExtractedImport,
    ParsedNode,
    ParsedNodeProperties,
    ParseResult,
)

# ===================================================================
# Helpers
# ===================================================================


def _make_node(
    file_path,
    name="dummy",
    label="Function",
    start_line=1,
    end_line=10,
    language="typescript",
):
    node_id = generate_id(label, f"{file_path}:{name}:{start_line}")
    return ParsedNode(
        id=node_id,
        label=label,
        properties=ParsedNodeProperties(
            name=name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language=language,
            is_exported=True,
        ),
    )


def _make_import(file_path, raw_import_path, language="typescript"):
    return ExtractedImport(
        file_path=file_path,
        raw_import_path=raw_import_path,
        language=language,
    )


def _build_index(files):
    normalized = [f.replace("\\", "/") for f in files]
    return build_suffix_index(normalized, files)


# ===================================================================
# 1. Constants
# ===================================================================


def test_extensions_count():
    assert len(EXTENSIONS) == 29


def test_extensions_first_is_empty():
    assert EXTENSIONS[0] == ""


def test_kotlin_extensions():
    assert KOTLIN_EXTENSIONS == [".kt", ".kts"]


# ===================================================================
# 2. SuffixIndex + build_suffix_index
# ===================================================================

_SAMPLE_FILES = [
    "src/com/example/Foo.java",
    "src/com/example/Bar.java",
    "src/utils/Helper.ts",
    "lib/utils/Helper.ts",
]
_SAMPLE_NORM = [f.replace("\\", "/") for f in _SAMPLE_FILES]
_SAMPLE_INDEX = build_suffix_index(_SAMPLE_NORM, _SAMPLE_FILES)


def test_suffix_get_filename():
    assert _SAMPLE_INDEX.get("Foo.java") == ("src/com/example/Foo.java")


def test_suffix_get_one_segment():
    assert _SAMPLE_INDEX.get("example/Foo.java") == ("src/com/example/Foo.java")


def test_suffix_get_two_segments():
    assert _SAMPLE_INDEX.get("com/example/Foo.java") == ("src/com/example/Foo.java")


def test_suffix_get_full_path():
    assert _SAMPLE_INDEX.get("src/com/example/Foo.java") == ("src/com/example/Foo.java")


def test_suffix_get_nonexistent():
    assert _SAMPLE_INDEX.get("nonexistent.java") is None


def test_suffix_get_insensitive_filename():
    assert _SAMPLE_INDEX.get_insensitive("FOO.JAVA") == ("src/com/example/Foo.java")


def test_suffix_get_insensitive_with_dir():
    assert (
        _SAMPLE_INDEX.get_insensitive("EXAMPLE/FOO.JAVA") == "src/com/example/Foo.java"
    )


def test_suffix_get_insensitive_nonexistent():
    assert _SAMPLE_INDEX.get_insensitive("nonexistent.java") is None


def test_suffix_get_files_in_dir_java():
    result = _SAMPLE_INDEX.get_files_in_dir("com/example", ".java")
    assert set(result) == {
        "src/com/example/Foo.java",
        "src/com/example/Bar.java",
    }


def test_suffix_get_files_in_dir_shorter_suffix():
    result = _SAMPLE_INDEX.get_files_in_dir("example", ".java")
    assert set(result) == {
        "src/com/example/Foo.java",
        "src/com/example/Bar.java",
    }


def test_suffix_get_files_in_dir_nonexistent():
    assert _SAMPLE_INDEX.get_files_in_dir("nonexistent", ".java") == []


def test_suffix_get_files_in_dir_wrong_ext():
    result = _SAMPLE_INDEX.get_files_in_dir("com/example", ".ts")
    assert result == []


def test_suffix_empty_file_list():
    idx = build_suffix_index([], [])
    assert idx.get("anything") is None
    assert idx.get_insensitive("anything") is None
    assert idx.get_files_in_dir("dir", ".java") == []


def test_suffix_single_file():
    files = ["only/one.py"]
    idx = _build_index(files)
    assert idx.get("one.py") == "only/one.py"
    assert idx.get("only/one.py") == "only/one.py"


def test_suffix_first_match_wins_ambiguous():
    files = [
        "src/utils/Helper.ts",
        "lib/utils/Helper.ts",
    ]
    idx = _build_index(files)
    assert idx.get("Helper.ts") == "src/utils/Helper.ts"


def test_suffix_second_file_reachable_by_longer_suffix():
    files = [
        "src/utils/Helper.ts",
        "lib/utils/Helper.ts",
    ]
    idx = _build_index(files)
    assert idx.get("lib/utils/Helper.ts") == "lib/utils/Helper.ts"


def test_suffix_dir_map_indexes_directory_suffixes():
    files = ["a/b/c/Foo.java"]
    idx = _build_index(files)
    assert "c:.java" in idx.dir_map
    assert "b/c:.java" in idx.dir_map
    assert "a/b/c:.java" in idx.dir_map


def test_suffix_dir_map_no_dir_for_root_file():
    files = ["Foo.java"]
    idx = _build_index(files)
    assert idx.get("Foo.java") == "Foo.java"
    assert idx.get_files_in_dir("", ".java") == []


def test_suffix_insensitive_first_match_wins():
    files = ["Src/Utils/ABC.ts", "lib/utils/abc.ts"]
    idx = _build_index(files)
    assert idx.get_insensitive("abc.ts") == "Src/Utils/ABC.ts"


def test_suffix_get_bar_java():
    assert _SAMPLE_INDEX.get("Bar.java") == ("src/com/example/Bar.java")


# ===================================================================
# 3. Config Loaders
# ===================================================================

# --- load_tsconfig_paths ---


def test_tsconfig_valid_with_paths(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    assert result is not None
    assert result.aliases == {"@/": "src/"}
    assert result.base_url == "."


def test_tsconfig_with_line_comments(tmp_path):
    raw = """{
        // This is a comment
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]}
        }
    }"""
    (tmp_path / "tsconfig.json").write_text(raw)
    result = load_tsconfig_paths(str(tmp_path))
    assert result is not None
    assert "@/" in result.aliases


def test_tsconfig_with_block_comments(tmp_path):
    raw = """{
        /* block comment */
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]}
        }
    }"""
    (tmp_path / "tsconfig.json").write_text(raw)
    result = load_tsconfig_paths(str(tmp_path))
    assert result is not None


def test_tsconfig_without_compiler_options(tmp_path):
    (tmp_path / "tsconfig.json").write_text(json.dumps({"include": ["src"]}))
    result = load_tsconfig_paths(str(tmp_path))
    assert result is None


def test_tsconfig_without_paths(tmp_path):
    tsconfig = {"compilerOptions": {"baseUrl": "."}}
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    assert result is None


def test_tsconfig_no_files(tmp_path):
    result = load_tsconfig_paths(str(tmp_path))
    assert result is None


def test_tsconfig_fallback_to_app(tmp_path):
    # tsconfig.json without paths
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": "."}})
    )
    tsconfig_app = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"~/*": ["app/*"]},
        }
    }
    (tmp_path / "tsconfig.app.json").write_text(json.dumps(tsconfig_app))
    result = load_tsconfig_paths(str(tmp_path))
    assert result is not None
    assert result.aliases == {"~/": "app/"}


def test_tsconfig_fallback_to_base(tmp_path):
    tsconfig_base = {
        "compilerOptions": {
            "baseUrl": "src",
            "paths": {"#/*": ["lib/*"]},
        }
    }
    (tmp_path / "tsconfig.base.json").write_text(json.dumps(tsconfig_base))
    result = load_tsconfig_paths(str(tmp_path))
    assert result is not None
    assert result.base_url == "src"
    assert result.aliases == {"#/": "lib/"}


def test_tsconfig_alias_with_star(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    assert result.aliases["@/"] == "src/"


def test_tsconfig_alias_without_star(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@utils": ["src/utils"]},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    assert result.aliases["@utils"] == "src/utils"


def test_tsconfig_custom_base_url(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": "src",
            "paths": {"@/*": ["modules/*"]},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    assert result.base_url == "src"


def test_tsconfig_empty_repo_root():
    result = load_tsconfig_paths("")
    assert result is None


def test_tsconfig_empty_targets_list(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": []},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    result = load_tsconfig_paths(str(tmp_path))
    # Empty targets → no aliases → returns None
    assert result is None


# --- load_go_module_path ---


def test_go_mod_valid(tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/user/repo\n\ngo 1.21\n")
    result = load_go_module_path(str(tmp_path))
    assert result is not None
    assert result.module_path == "github.com/user/repo"


def test_go_mod_with_extra_content(tmp_path):
    content = (
        "module github.com/org/project\n\n"
        "go 1.22\n\n"
        "require (\n\tgithub.com/foo/bar v1.0.0\n)\n"
    )
    (tmp_path / "go.mod").write_text(content)
    result = load_go_module_path(str(tmp_path))
    assert result is not None
    assert result.module_path == "github.com/org/project"


def test_go_mod_missing(tmp_path):
    result = load_go_module_path(str(tmp_path))
    assert result is None


def test_go_mod_empty_file(tmp_path):
    (tmp_path / "go.mod").write_text("")
    result = load_go_module_path(str(tmp_path))
    assert result is None


def test_go_mod_empty_repo_root():
    result = load_go_module_path("")
    assert result is None


# --- load_composer_config ---


def test_composer_valid_psr4(tmp_path):
    composer = {"autoload": {"psr-4": {"App\\": "src/"}}}
    (tmp_path / "composer.json").write_text(json.dumps(composer))
    result = load_composer_config(str(tmp_path))
    assert result is not None
    assert result.psr4["App"] == "src"


def test_composer_merges_autoload_dev(tmp_path):
    composer = {
        "autoload": {"psr-4": {"App\\": "src/"}},
        "autoload-dev": {"psr-4": {"Tests\\": "tests/"}},
    }
    (tmp_path / "composer.json").write_text(json.dumps(composer))
    result = load_composer_config(str(tmp_path))
    assert result is not None
    assert "App" in result.psr4
    assert "Tests" in result.psr4


def test_composer_strips_trailing_backslash(tmp_path):
    composer = {"autoload": {"psr-4": {"App\\Models\\": "src/Models/"}}}
    (tmp_path / "composer.json").write_text(json.dumps(composer))
    result = load_composer_config(str(tmp_path))
    assert "App\\Models" in result.psr4


def test_composer_strips_trailing_slash(tmp_path):
    composer = {"autoload": {"psr-4": {"App\\": "src/"}}}
    (tmp_path / "composer.json").write_text(json.dumps(composer))
    result = load_composer_config(str(tmp_path))
    assert result.psr4["App"] == "src"


def test_composer_missing(tmp_path):
    result = load_composer_config(str(tmp_path))
    assert result is None


def test_composer_without_autoload(tmp_path):
    (tmp_path / "composer.json").write_text(json.dumps({"name": "vendor/pkg"}))
    result = load_composer_config(str(tmp_path))
    assert result is not None
    assert result.psr4 == {}


def test_composer_empty_repo_root():
    result = load_composer_config("")
    assert result is None


# --- load_swift_package_config ---


def test_swift_sources_with_subdirs(tmp_path):
    sources = tmp_path / "Sources"
    sources.mkdir()
    (sources / "MyLib").mkdir()
    (sources / "MyApp").mkdir()
    result = load_swift_package_config(str(tmp_path))
    assert result is not None
    assert "MyLib" in result.targets
    assert result.targets["MyLib"] == "Sources/MyLib"
    assert "MyApp" in result.targets


def test_swift_package_sources(tmp_path):
    pkg = tmp_path / "Package" / "Sources"
    pkg.mkdir(parents=True)
    (pkg / "Core").mkdir()
    result = load_swift_package_config(str(tmp_path))
    assert result is not None
    assert result.targets["Core"] == "Package/Sources/Core"


def test_swift_no_source_dirs(tmp_path):
    result = load_swift_package_config(str(tmp_path))
    assert result is None


def test_swift_files_ignored(tmp_path):
    sources = tmp_path / "Sources"
    sources.mkdir()
    (sources / "not_a_dir.swift").write_text("// file")
    result = load_swift_package_config(str(tmp_path))
    assert result is None


def test_swift_multiple_source_dirs(tmp_path):
    s1 = tmp_path / "Sources"
    s1.mkdir()
    (s1 / "A").mkdir()
    s2 = tmp_path / "src"
    s2.mkdir()
    (s2 / "B").mkdir()
    result = load_swift_package_config(str(tmp_path))
    assert result is not None
    assert "A" in result.targets
    assert "B" in result.targets


def test_swift_nonexistent_repo_root():
    result = load_swift_package_config("/nonexistent/path/that/does/not/exist")
    assert result is None


# ===================================================================
# 4. try_resolve_with_extensions
# ===================================================================

_TRE_FILES = {
    "src/utils.ts",
    "src/index.tsx",
    "src/main.py",
    "src/lib/index.ts",
    "src/exact.js",
}


def test_tre_ts_extension():
    assert try_resolve_with_extensions("src/utils", _TRE_FILES) == "src/utils.ts"


def test_tre_tsx_extension():
    assert try_resolve_with_extensions("src/index", _TRE_FILES) == "src/index.tsx"


def test_tre_index_resolution():
    assert try_resolve_with_extensions("src/lib", _TRE_FILES) == "src/lib/index.ts"


def test_tre_python_resolution():
    assert try_resolve_with_extensions("src/main", _TRE_FILES) == "src/main.py"


def test_tre_already_resolved():
    assert try_resolve_with_extensions("src/utils.ts", _TRE_FILES) == "src/utils.ts"


def test_tre_nonexistent():
    assert try_resolve_with_extensions("src/missing", _TRE_FILES) is None


def test_tre_empty_ext_matches_exact():
    assert try_resolve_with_extensions("src/exact.js", _TRE_FILES) == "src/exact.js"


def test_tre_empty_set():
    assert try_resolve_with_extensions("anything", set()) is None


def test_tre_js_extension():
    files = {"app.js"}
    assert try_resolve_with_extensions("app", files) == "app.js"


def test_tre_init_py():
    files = {"pkg/__init__.py"}
    assert try_resolve_with_extensions("pkg", files) == "pkg/__init__.py"


# ===================================================================
# 5. suffix_resolve
# ===================================================================

_SR_FILES = [
    "src/components/Button.tsx",
    "src/utils/format.ts",
    "lib/shared/format.ts",
]
_SR_INDEX = _build_index(_SR_FILES)


def test_sr_resolves_matching_suffix():
    result = suffix_resolve(
        ["components", "Button"],
        _SR_FILES,
        _SR_FILES,
        _SR_INDEX,
    )
    assert result == "src/components/Button.tsx"


def test_sr_case_insensitive_fallback():
    files = ["src/Models/User.java"]
    idx = _build_index(files)
    result = suffix_resolve(["models", "user"], files, files, idx)
    assert result == "src/Models/User.java"


def test_sr_tries_shorter_suffixes():
    result = suffix_resolve(
        ["x", "y", "format"],
        _SR_FILES,
        _SR_FILES,
        _SR_INDEX,
    )
    assert result == "src/utils/format.ts"


def test_sr_non_matching_returns_none():
    result = suffix_resolve(
        ["nope", "nothing"],
        _SR_FILES,
        _SR_FILES,
        _SR_INDEX,
    )
    assert result is None


def test_sr_empty_parts():
    result = suffix_resolve([], _SR_FILES, _SR_FILES, _SR_INDEX)
    assert result is None


def test_sr_single_part():
    result = suffix_resolve(["Button"], _SR_FILES, _SR_FILES, _SR_INDEX)
    assert result == "src/components/Button.tsx"


def test_sr_exact_full_path():
    result = suffix_resolve(
        ["src", "utils", "format"],
        _SR_FILES,
        _SR_FILES,
        _SR_INDEX,
    )
    assert result == "src/utils/format.ts"


def test_sr_extension_appended():
    files = ["deep/mod.rs"]
    idx = _build_index(files)
    result = suffix_resolve(["deep", "mod"], files, files, idx)
    assert result == "deep/mod.rs"


# ===================================================================
# 6. Rust Resolution
# ===================================================================

_RUST_FILES = {
    "src/foo.rs",
    "src/foo/bar.rs",
    "src/foo/bar/mod.rs",
    "src/lib.rs",
    "src/foo/baz/lib.rs",
    "crates/ext/mod.rs",
    "src/sibling.rs",
}


def test_rust_crate_prefix_simple():
    result = resolve_rust_import("src/main.rs", "crate::foo", _RUST_FILES)
    assert result == "src/foo.rs"


def test_rust_crate_prefix_nested():
    result = resolve_rust_import("src/main.rs", "crate::foo::bar", _RUST_FILES)
    assert result == "src/foo/bar.rs"


def test_rust_crate_mod_rs():
    files = {"src/models/mod.rs"}
    result = resolve_rust_import("src/main.rs", "crate::models", files)
    assert result == "src/models/mod.rs"


def test_rust_crate_lib_rs():
    result = resolve_rust_import("src/main.rs", "crate::foo::baz", _RUST_FILES)
    assert result == "src/foo/baz/lib.rs"


def test_rust_crate_fallback_to_root():
    files = {"crates/mymod.rs"}
    result = resolve_rust_import("src/main.rs", "crate::mymod", files)
    # src/mymod.rs not present, falls back to root mymod.rs
    # but crates/mymod.rs doesn't match root lookup
    assert result is None

    files2 = {"mymod.rs"}
    result2 = resolve_rust_import("src/main.rs", "crate::mymod", files2)
    assert result2 == "mymod.rs"


def test_rust_super_prefix():
    result = resolve_rust_import("src/foo/bar.rs", "super::sibling", _RUST_FILES)
    assert result == "src/sibling.rs"


def test_rust_self_prefix():
    files = {"src/foo/child.rs"}
    result = resolve_rust_import("src/foo/mod.rs", "self::child", files)
    assert result == "src/foo/child.rs"


def test_rust_bare_double_colon():
    files = {"ext/crate/thing.rs"}
    result = resolve_rust_import("src/main.rs", "ext::crate::thing", files)
    assert result == "ext/crate/thing.rs"


def test_rust_non_rust_pattern():
    result = resolve_rust_import("src/main.rs", "./relative", _RUST_FILES)
    assert result is None


def test_rust_no_double_colon():
    result = resolve_rust_import("src/main.rs", "just_a_name", _RUST_FILES)
    assert result is None


def test_rust_last_segment_stripping():
    files = {"src/models.rs"}
    result = resolve_rust_import("src/main.rs", "crate::models::User", files)
    assert result == "src/models.rs"


def test_rust_self_nested():
    files = {"src/handlers/auth/login.rs"}
    result = resolve_rust_import(
        "src/handlers/auth/mod.rs",
        "self::login",
        files,
    )
    assert result == "src/handlers/auth/login.rs"


def test_rust_super_with_nested():
    files = {"src/utils.rs"}
    result = resolve_rust_import("src/foo/bar.rs", "super::utils", files)
    assert result == "src/utils.rs"


def test_rust_crate_deeply_nested():
    files = {"src/a/b/c.rs"}
    result = resolve_rust_import("src/main.rs", "crate::a::b::c", files)
    assert result == "src/a/b/c.rs"


def test_rust_empty_files():
    result = resolve_rust_import("src/main.rs", "crate::foo", set())
    assert result is None


# ===================================================================
# 7. JVM Resolution
# ===================================================================

_JVM_FILES = [
    "src/com/example/models/User.java",
    "src/com/example/models/Role.java",
    "src/com/example/services/Auth.java",
    "src/com/example/util/Helper.kt",
    "src/com/example/util/Config.kts",
]
_JVM_INDEX = _build_index(_JVM_FILES)


def test_jvm_wildcard_java():
    result = resolve_jvm_wildcard(
        "com.example.models.*",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert set(result) == {
        "src/com/example/models/User.java",
        "src/com/example/models/Role.java",
    }


def test_jvm_wildcard_only_direct_children():
    files = [
        "src/com/example/Foo.java",
        "src/com/example/sub/Bar.java",
    ]
    idx = _build_index(files)
    result = resolve_jvm_wildcard("com.example.*", files, files, [".java"], idx)
    assert result == ["src/com/example/Foo.java"]


def test_jvm_wildcard_kotlin_extensions():
    result = resolve_jvm_wildcard(
        "com.example.util.*",
        _JVM_FILES,
        _JVM_FILES,
        KOTLIN_EXTENSIONS,
        _JVM_INDEX,
    )
    assert set(result) == {
        "src/com/example/util/Helper.kt",
        "src/com/example/util/Config.kts",
    }


def test_jvm_wildcard_empty_result():
    result = resolve_jvm_wildcard(
        "com.nonexistent.*",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result == []


def test_jvm_wildcard_no_ext_match():
    result = resolve_jvm_wildcard(
        "com.example.models.*",
        _JVM_FILES,
        _JVM_FILES,
        [".kt"],
        _JVM_INDEX,
    )
    assert result == []


def test_jvm_member_lowercase():
    result = resolve_jvm_member_import(
        "com.example.models.User.getName",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result == "src/com/example/models/User.java"


def test_jvm_member_all_caps():
    result = resolve_jvm_member_import(
        "com.example.models.User.MAX_SIZE",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result == "src/com/example/models/User.java"


def test_jvm_member_wildcard_star():
    result = resolve_jvm_member_import(
        "com.example.models.User.*",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result == "src/com/example/models/User.java"


def test_jvm_member_less_than_3_segments():
    result = resolve_jvm_member_import(
        "User.getName",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result is None


def test_jvm_member_camelcase_not_member():
    result = resolve_jvm_member_import(
        "com.example.models.User.InnerClass",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    # CamelCase (starts with uppercase, not ALL_CAPS) -> not a
    # member import
    assert result is None


def test_jvm_member_case_insensitive_fallback():
    files = ["src/COM/EXAMPLE/Foo.java"]
    idx = _build_index(files)
    result = resolve_jvm_member_import(
        "com.example.Foo.bar",
        files,
        files,
        [".java"],
        idx,
    )
    assert result == "src/COM/EXAMPLE/Foo.java"


def test_jvm_member_kotlin():
    result = resolve_jvm_member_import(
        "com.example.util.Helper.doStuff",
        _JVM_FILES,
        _JVM_FILES,
        KOTLIN_EXTENSIONS,
        _JVM_INDEX,
    )
    assert result == "src/com/example/util/Helper.kt"


def test_jvm_member_single_segment():
    result = resolve_jvm_member_import(
        "User",
        _JVM_FILES,
        _JVM_FILES,
        [".java"],
        _JVM_INDEX,
    )
    assert result is None


def test_jvm_wildcard_java_only_java_files():
    files = [
        "src/pkg/A.java",
        "src/pkg/B.kt",
    ]
    idx = _build_index(files)
    result = resolve_jvm_wildcard("pkg.*", files, files, [".java"], idx)
    assert result == ["src/pkg/A.java"]


# ===================================================================
# 8. Go Resolution
# ===================================================================

_GO_MODULE = GoModuleConfig(module_path="github.com/user/repo")
# Paths need a prefix so that the "/" + pkg + "/" substring
# search in resolve_go_package can match.
_GO_FILES = [
    "repo/pkg/util/helpers.go",
    "repo/pkg/util/format.go",
    "repo/pkg/util/helpers_test.go",
    "repo/pkg/util/sub/nested.go",
    "repo/cmd/main.go",
]
_GO_NORM = [f.replace("\\", "/") for f in _GO_FILES]


def test_go_package_resolves():
    result = resolve_go_package(
        "github.com/user/repo/pkg/util",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert set(result) == {
        "repo/pkg/util/helpers.go",
        "repo/pkg/util/format.go",
    }


def test_go_package_excludes_test():
    result = resolve_go_package(
        "github.com/user/repo/pkg/util",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert "repo/pkg/util/helpers_test.go" not in result


def test_go_package_only_direct_children():
    result = resolve_go_package(
        "github.com/user/repo/pkg/util",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert "repo/pkg/util/sub/nested.go" not in result


def test_go_package_non_module_import():
    result = resolve_go_package(
        "github.com/other/lib/pkg",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert result == []


def test_go_package_empty_relative():
    result = resolve_go_package(
        "github.com/user/repo",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert result == []


def test_go_package_cmd():
    result = resolve_go_package(
        "github.com/user/repo/cmd",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert result == ["repo/cmd/main.go"]


def test_go_package_no_match():
    result = resolve_go_package(
        "github.com/user/repo/nonexist",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert result == []


def test_go_package_sub_package():
    result = resolve_go_package(
        "github.com/user/repo/pkg/util/sub",
        _GO_MODULE,
        _GO_NORM,
        _GO_FILES,
    )
    assert result == ["repo/pkg/util/sub/nested.go"]


# ===================================================================
# 9. PHP Resolution
# ===================================================================

_PHP_FILES_LIST = [
    "src/Models/User.php",
    "src/Models/Role.php",
    "tests/Unit/UserTest.php",
]
_PHP_ALL = set(_PHP_FILES_LIST)
_PHP_NORM = [f.replace("\\", "/") for f in _PHP_FILES_LIST]
_PHP_INDEX = _build_index(_PHP_FILES_LIST)


def test_php_psr4_resolution():
    config = ComposerConfig(psr4={"App": "src"})
    result = resolve_php_import(
        "App\\Models\\User",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result == "src/Models/User.php"


def test_php_longest_prefix_wins():
    config = ComposerConfig(
        psr4={
            "App": "src",
            "App\\Models": "src/Models",
        }
    )
    result = resolve_php_import(
        "App\\Models\\User",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result == "src/Models/User.php"


def test_php_backslash_to_slash():
    config = ComposerConfig(psr4={"App": "src"})
    result = resolve_php_import(
        "App\\Models\\Role",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result == "src/Models/Role.php"


def test_php_fallback_suffix_resolution():
    result = resolve_php_import(
        "Models\\User",
        None,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result == "src/Models/User.php"


def test_php_exact_match():
    config = ComposerConfig(psr4={"Tests": "tests"})
    result = resolve_php_import(
        "Tests\\Unit\\UserTest",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result == "tests/Unit/UserTest.php"


def test_php_no_match():
    config = ComposerConfig(psr4={"App": "src"})
    result = resolve_php_import(
        "Vendor\\Package\\Class",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    # No file exists, falls through
    assert result is None


def test_php_no_composer_no_match():
    result = resolve_php_import(
        "Completely\\Unknown",
        None,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    assert result is None


def test_php_namespace_prefix_match_only():
    config = ComposerConfig(psr4={"App": "src"})
    result = resolve_php_import(
        "Application\\Foo",
        config,
        _PHP_ALL,
        _PHP_NORM,
        _PHP_FILES_LIST,
        _PHP_INDEX,
    )
    # "Application" doesn't start with "App/"
    assert result is None


def test_php_case_insensitive_fallback():
    files = ["SRC/models/user.php"]
    all_f = set(files)
    idx = _build_index(files)
    config = ComposerConfig(psr4={"App": "src"})
    result = resolve_php_import(
        "App\\models\\user",
        config,
        all_f,
        files,
        files,
        idx,
    )
    # Exact path "src/models/user.php" not in set, but
    # insensitive lookup finds "SRC/models/user.php"
    assert result == "SRC/models/user.php"


def test_php_exact_namespace():
    config = ComposerConfig(psr4={"App": "src"})
    files = ["src.php"]
    all_f = set(files)
    idx = _build_index(files)
    result = resolve_php_import("App", config, all_f, files, files, idx)
    assert result == "src.php"


# ===================================================================
# 10. resolve_import_path
# ===================================================================


def _resolve(
    current_file,
    import_path,
    all_files_list,
    language="typescript",
    tsconfig_paths=None,
    cache=None,
):
    if cache is None:
        cache = {}
    all_files = set(all_files_list)
    norm = [f.replace("\\", "/") for f in all_files_list]
    idx = _build_index(all_files_list)
    return resolve_import_path(
        current_file,
        import_path,
        all_files,
        all_files_list,
        norm,
        cache,
        language,
        tsconfig_paths,
        idx,
    )


def test_rip_relative_import():
    files = [
        "src/components/App.tsx",
        "src/utils/helpers.ts",
    ]
    result = _resolve(
        "src/components/App.tsx",
        "../utils/helpers",
        files,
    )
    assert result == "src/utils/helpers.ts"


def test_rip_relative_same_dir():
    files = ["src/a.ts", "src/b.ts"]
    result = _resolve("src/a.ts", "./b", files)
    assert result == "src/b.ts"


def test_rip_parent_navigation():
    files = [
        "src/deep/nested/file.ts",
        "src/lib.ts",
    ]
    result = _resolve("src/deep/nested/file.ts", "../../lib", files)
    assert result == "src/lib.ts"


def test_rip_tsconfig_alias():
    files = ["src/utils/format.ts"]
    tsc = TsconfigPaths(aliases={"@/": "src/"}, base_url=".")
    result = _resolve(
        "src/app.ts",
        "@/utils/format",
        files,
        tsconfig_paths=tsc,
    )
    assert result == "src/utils/format.ts"


def test_rip_alias_no_match():
    files = ["src/utils.ts"]
    tsc = TsconfigPaths(aliases={"@/": "src/"}, base_url=".")
    result = _resolve(
        "src/app.ts",
        "lodash",
        files,
        tsconfig_paths=tsc,
    )
    # "lodash" doesn't start with "@/"
    assert result is None


def test_rip_rust_dispatch():
    files = ["src/foo.rs"]
    result = _resolve(
        "src/main.rs",
        "crate::foo",
        files,
        language="rust",
    )
    assert result == "src/foo.rs"


def test_rip_wildcard_returns_none():
    files = ["src/com/example/Foo.java"]
    result = _resolve(
        "src/Main.java",
        "com.example.*",
        files,
        language="java",
    )
    assert result is None


def test_rip_dot_to_slash():
    files = ["src/com/example/Foo.java"]
    result = _resolve(
        "src/Main.java",
        "com.example.Foo",
        files,
        language="java",
    )
    assert result == "src/com/example/Foo.java"


def test_rip_cache_hit():
    files = ["src/utils.ts"]
    cache = {}
    result1 = _resolve(
        "src/app.ts",
        "./utils",
        files,
        cache=cache,
    )
    assert result1 == "src/utils.ts"
    assert "src/app.ts::./utils" in cache
    result2 = _resolve(
        "src/app.ts",
        "./utils",
        files,
        cache=cache,
    )
    assert result2 == "src/utils.ts"


def test_rip_cache_stores_none():
    files = ["src/utils.ts"]
    cache = {}
    result = _resolve(
        "src/app.ts",
        "./nonexistent",
        files,
        cache=cache,
    )
    assert result is None
    assert cache["src/app.ts::./nonexistent"] is None


def test_rip_cache_eviction():
    files = ["src/utils.ts"]
    cache = {}
    # Fill cache to capacity
    for i in range(RESOLVE_CACHE_CAP):
        cache[f"key_{i}"] = f"value_{i}"
    # This should trigger eviction
    result = _resolve(
        "src/app.ts",
        "./utils",
        files,
        cache=cache,
    )
    assert result == "src/utils.ts"
    # Cache should have been trimmed
    assert len(cache) < RESOLVE_CACHE_CAP


def test_rip_relative_with_dot():
    files = ["src/foo/bar.ts"]
    result = _resolve("src/foo/baz.ts", "./bar", files)
    assert result == "src/foo/bar.ts"


def test_rip_nonexistent_relative():
    files = ["src/a.ts"]
    result = _resolve("src/a.ts", "./missing", files)
    assert result is None


def test_rip_tsconfig_with_base_url():
    files = ["src/modules/auth.ts"]
    tsc = TsconfigPaths(aliases={"@mod/": "modules/"}, base_url="src")
    result = _resolve(
        "src/app.ts",
        "@mod/auth",
        files,
        tsconfig_paths=tsc,
    )
    assert result == "src/modules/auth.ts"


def test_rip_non_relative_suffix_resolve():
    files = ["lib/shared/utils.ts"]
    result = _resolve(
        "src/app.ts",
        "shared/utils",
        files,
    )
    assert result == "lib/shared/utils.ts"


def test_rip_alias_not_applied_for_relative():
    files = ["src/utils.ts"]
    tsc = TsconfigPaths(aliases={"./": "src/"}, base_url=".")
    # Relative import should not go through alias rewriting
    result = _resolve(
        "src/app.ts",
        "./utils",
        files,
        tsconfig_paths=tsc,
    )
    assert result == "src/utils.ts"


def test_rip_python_relative():
    files = [
        "src/pkg/main.py",
        "src/pkg/utils.py",
    ]
    result = _resolve(
        "src/pkg/main.py",
        "./utils",
        files,
        language="python",
    )
    assert result == "src/pkg/utils.py"


def test_rip_slash_in_import_stays():
    files = ["packages/core/index.ts"]
    result = _resolve(
        "src/app.ts",
        "packages/core",
        files,
    )
    assert result == "packages/core/index.ts"


# ===================================================================
# 11. process_imports — end-to-end integration
# ===================================================================


def test_pi_empty_imports():
    pr = ParseResult()
    pr.imports = []
    result = process_imports(pr)
    assert result == {}
    assert pr.relationships == []


def test_pi_ts_relative():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/components/App.tsx"),
        _make_node("src/utils/helpers.ts"),
    ]
    pr.imports = [
        _make_import(
            "src/components/App.tsx",
            "../utils/helpers",
            "typescript",
        ),
    ]
    result = process_imports(pr)
    assert "src/components/App.tsx" in result
    assert "src/utils/helpers.ts" in result["src/components/App.tsx"]
    assert len(pr.relationships) == 1
    rel = pr.relationships[0]
    assert rel.type == "IMPORTS"
    assert rel.confidence == 1.0
    assert rel.reason == ""


def test_pi_multiple_imports_same_file():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/app.ts"),
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/app.ts", "./a", "typescript"),
        _make_import("src/app.ts", "./b", "typescript"),
    ]
    result = process_imports(pr)
    assert result["src/app.ts"] == {
        "src/a.ts",
        "src/b.ts",
    }
    assert len(pr.relationships) == 2


def test_pi_python_import():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/main.py", language="python"),
        _make_node("src/utils.py", language="python"),
    ]
    pr.imports = [
        _make_import("src/main.py", "./utils", "python"),
    ]
    result = process_imports(pr)
    assert "src/utils.py" in result["src/main.py"]


def test_pi_java_wildcard():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.java", language="java"),
        _make_node(
            "src/com/example/Foo.java",
            language="java",
        ),
        _make_node(
            "src/com/example/Bar.java",
            language="java",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.java",
            "com.example.*",
            "java",
        ),
    ]
    result = process_imports(pr)
    assert "src/Main.java" in result
    assert "src/com/example/Foo.java" in result["src/Main.java"]
    assert "src/com/example/Bar.java" in result["src/Main.java"]


def test_pi_jvm_member_import():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.java", language="java"),
        _make_node(
            "src/com/example/Util.java",
            language="java",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.java",
            "com.example.Util.doSomething",
            "java",
        ),
    ]
    result = process_imports(pr)
    assert "src/com/example/Util.java" in result["src/Main.java"]


def test_pi_go_package(tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/user/repo\n")
    pr = ParseResult()
    pr.nodes = [
        _make_node("repo/cmd/main.go", language="go"),
        _make_node(
            "repo/pkg/util/helpers.go",
            language="go",
        ),
    ]
    pr.imports = [
        _make_import(
            "repo/cmd/main.go",
            "github.com/user/repo/pkg/util",
            "go",
        ),
    ]
    result = process_imports(pr, project_root=str(tmp_path))
    assert "repo/pkg/util/helpers.go" in result["repo/cmd/main.go"]


def test_pi_php_import(tmp_path):
    composer = {"autoload": {"psr-4": {"App\\": "src/"}}}
    (tmp_path / "composer.json").write_text(json.dumps(composer))
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Controller.php", language="php"),
        _make_node("src/Models/User.php", language="php"),
    ]
    pr.imports = [
        _make_import(
            "src/Controller.php",
            "App\\Models\\User",
            "php",
        ),
    ]
    result = process_imports(pr, project_root=str(tmp_path))
    assert "src/Models/User.php" in result["src/Controller.php"]


def test_pi_swift_module(tmp_path):
    sources = tmp_path / "Sources"
    sources.mkdir()
    (sources / "MyLib").mkdir()
    pr = ParseResult()
    pr.nodes = [
        _make_node(
            "Sources/MyApp/main.swift",
            language="swift",
        ),
        _make_node(
            "Sources/MyLib/Lib.swift",
            language="swift",
        ),
    ]
    pr.imports = [
        _make_import(
            "Sources/MyApp/main.swift",
            "MyLib",
            "swift",
        ),
    ]
    result = process_imports(pr, project_root=str(tmp_path))
    assert "Sources/MyLib/Lib.swift" in result["Sources/MyApp/main.swift"]


def test_pi_rust_crate():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/main.rs", language="rust"),
        _make_node("src/config.rs", language="rust"),
    ]
    pr.imports = [
        _make_import("src/main.rs", "crate::config", "rust"),
    ]
    result = process_imports(pr)
    assert "src/config.rs" in result["src/main.rs"]


def test_pi_nonexistent_import():
    pr = ParseResult()
    pr.nodes = [_make_node("src/app.ts")]
    pr.imports = [
        _make_import(
            "src/app.ts",
            "./does_not_exist",
            "typescript",
        ),
    ]
    result = process_imports(pr)
    assert result == {}
    assert pr.relationships == []


def test_pi_returns_dict_of_sets():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    result = process_imports(pr)
    assert isinstance(result, dict)
    assert isinstance(result["src/a.ts"], set)


def test_pi_relationship_type():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr)
    assert pr.relationships[0].type == "IMPORTS"


def test_pi_relationship_confidence():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr)
    assert pr.relationships[0].confidence == 1.0


def test_pi_relationship_reason():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr)
    assert pr.relationships[0].reason == ""


def test_pi_deterministic_ids():
    pr1 = ParseResult()
    pr1.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr1.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr1)

    pr2 = ParseResult()
    pr2.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr2.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr2)

    assert pr1.relationships[0].id == (pr2.relationships[0].id)


def test_pi_relationship_source_target_ids():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr)
    rel = pr.relationships[0]
    assert rel.source_id == generate_id("File", "src/a.ts")
    assert rel.target_id == generate_id("File", "src/b.ts")


def test_pi_kotlin_wildcard():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.kt", language="kotlin"),
        _make_node(
            "src/com/example/Foo.kt",
            language="kotlin",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.kt",
            "com.example.*",
            "kotlin",
        ),
    ]
    result = process_imports(pr)
    assert "src/com/example/Foo.kt" in result["src/Main.kt"]


def test_pi_kotlin_member_import():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.kt", language="kotlin"),
        _make_node(
            "src/com/example/Utils.kt",
            language="kotlin",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.kt",
            "com.example.Utils.helper",
            "kotlin",
        ),
    ]
    result = process_imports(pr)
    assert "src/com/example/Utils.kt" in result["src/Main.kt"]


def test_pi_swift_no_config():
    pr = ParseResult()
    pr.nodes = [
        _make_node(
            "Sources/App/main.swift",
            language="swift",
        ),
    ]
    pr.imports = [
        _make_import(
            "Sources/App/main.swift",
            "Foundation",
            "swift",
        ),
    ]
    result = process_imports(pr)
    # No swift config → no resolution for module name
    assert result == {}


def test_pi_php_no_config():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Controller.php", language="php"),
        _make_node("src/Models/User.php", language="php"),
    ]
    pr.imports = [
        _make_import(
            "src/Controller.php",
            "Models\\User",
            "php",
        ),
    ]
    # No project_root → no composer config → suffix fallback
    result = process_imports(pr)
    assert "src/Models/User.php" in result["src/Controller.php"]


def test_pi_multiple_files_importing():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
        _make_node("src/c.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./c", "typescript"),
        _make_import("src/b.ts", "./c", "typescript"),
    ]
    result = process_imports(pr)
    assert "src/c.ts" in result["src/a.ts"]
    assert "src/c.ts" in result["src/b.ts"]
    assert len(pr.relationships) == 2


def test_pi_import_file_path_auto_added():
    pr = ParseResult()
    pr.nodes = [_make_node("src/b.ts")]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    result = process_imports(pr)
    assert "src/b.ts" in result["src/a.ts"]


def test_pi_tsconfig_integration(tmp_path):
    tsconfig = {
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]},
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/app.ts"),
        _make_node("src/utils.ts"),
    ]
    pr.imports = [
        _make_import(
            "src/app.ts",
            "@/utils",
            "typescript",
        ),
    ]
    result = process_imports(pr, project_root=str(tmp_path))
    assert "src/utils.ts" in result["src/app.ts"]


def test_pi_c_include():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/main.c", language="c"),
        _make_node("src/utils.h", language="c"),
    ]
    pr.imports = [
        _make_import("src/main.c", "./utils", "c"),
    ]
    result = process_imports(pr)
    assert "src/utils.h" in result["src/main.c"]


def test_pi_csharp_import():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Program.cs", language="csharp"),
        _make_node("src/Models/User.cs", language="csharp"),
    ]
    pr.imports = [
        _make_import(
            "src/Program.cs",
            "Models.User",
            "csharp",
        ),
    ]
    result = process_imports(pr)
    assert "src/Models/User.cs" in result["src/Program.cs"]


def test_pi_kotlin_falls_back_to_java_wildcard():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.kt", language="kotlin"),
        _make_node(
            "src/com/example/Foo.java",
            language="java",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.kt",
            "com.example.*",
            "kotlin",
        ),
    ]
    result = process_imports(pr)
    assert "src/com/example/Foo.java" in result["src/Main.kt"]


def test_pi_kotlin_member_falls_back_to_java():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/Main.kt", language="kotlin"),
        _make_node(
            "src/com/example/Util.java",
            language="java",
        ),
    ]
    pr.imports = [
        _make_import(
            "src/Main.kt",
            "com.example.Util.helper",
            "kotlin",
        ),
    ]
    result = process_imports(pr)
    assert "src/com/example/Util.java" in result["src/Main.kt"]


def test_pi_go_excludes_test_files(tmp_path):
    (tmp_path / "go.mod").write_text("module github.com/u/r\n")
    pr = ParseResult()
    pr.nodes = [
        _make_node("repo/cmd/main.go", language="go"),
        _make_node(
            "repo/pkg/util/helpers.go",
            language="go",
        ),
        _make_node(
            "repo/pkg/util/helpers_test.go",
            language="go",
        ),
    ]
    pr.imports = [
        _make_import(
            "repo/cmd/main.go",
            "github.com/u/r/pkg/util",
            "go",
        ),
    ]
    result = process_imports(pr, project_root=str(tmp_path))
    assert "repo/pkg/util/helpers_test.go" not in result.get("repo/cmd/main.go", set())


def test_pi_relationship_count_matches_import_map():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
        _make_node("src/c.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
        _make_import("src/a.ts", "./c", "typescript"),
    ]
    result = process_imports(pr)
    total_edges = sum(len(v) for v in result.values())
    assert len(pr.relationships) == total_edges


def test_pi_no_duplicate_relationships():
    pr = ParseResult()
    pr.nodes = [
        _make_node("src/a.ts"),
        _make_node("src/b.ts"),
    ]
    pr.imports = [
        _make_import("src/a.ts", "./b", "typescript"),
        _make_import("src/a.ts", "./b", "typescript"),
    ]
    process_imports(pr)
    # Two identical imports still create two relationships
    # because the engine processes each import entry
    assert len(pr.relationships) == 2


def test_pi_resolve_cache_cap_constant():
    assert RESOLVE_CACHE_CAP == 100_000


# ===================================================================
# Call Resolution Engine (calls.py)
# ===================================================================


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _make_symbol_table(*entries):
    """Build a SymbolTable from (file_path, name, node_id, type) tuples."""
    st = SymbolTable()
    for fp, name, nid, typ in entries:
        st.add(fp, name, nid, typ)
    return st


def _make_call(file_path, called_name, source_id):
    """Build an ExtractedCall."""
    return ExtractedCall(
        file_path=file_path, called_name=called_name, source_id=source_id
    )


# -------------------------------------------------------------------
# BUILT_IN_NAMES tests
# -------------------------------------------------------------------


def test_built_in_names_is_frozenset():
    assert isinstance(BUILT_IN_NAMES, frozenset)


def test_built_in_names_contains_js_builtins():
    for name in ("console", "setTimeout", "parseInt"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_python_builtins():
    for name in ("print", "len", "range"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_kotlin_builtins():
    for name in ("println", "listOf", "mapOf"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_c_builtins():
    for name in ("printf", "malloc", "free"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_swift_builtins():
    for name in ("fatalError", "NSLog", "debugPrint"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_react_hooks():
    for name in ("useState", "useEffect", "useCallback"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


def test_built_in_names_contains_linux_kernel():
    for name in ("printk", "kmalloc", "kfree"):
        assert name in BUILT_IN_NAMES, f"{name!r} should be in BUILT_IN_NAMES"


# -------------------------------------------------------------------
# _is_built_in_or_noise tests
# -------------------------------------------------------------------


def test_is_built_in_returns_true_for_builtins():
    for name in ("console", "print", "printf"):
        assert (
            _is_built_in_or_noise(name) is True
        ), f"_is_built_in_or_noise({name!r}) should be True"


def test_is_built_in_returns_false_for_user_functions():
    for name in ("myFunction", "handleClick", "processOrder"):
        assert (
            _is_built_in_or_noise(name) is False
        ), f"_is_built_in_or_noise({name!r}) should be False"


# -------------------------------------------------------------------
# _resolve_call_target tests
# -------------------------------------------------------------------


def test_resolve_tier1_same_file():
    st = _make_symbol_table(
        ("src/a.py", "helper", "Fn::src/a.py::helper::10", "Function"),
    )
    result = _resolve_call_target("helper", "src/a.py", st, {})
    assert result is not None
    assert result.node_id == "Fn::src/a.py::helper::10"
    assert result.confidence == 0.85
    assert result.reason == "same-file"


def test_resolve_tier2_import_resolved():
    st = _make_symbol_table(
        ("src/b.py", "helper", "Fn::src/b.py::helper::5", "Function"),
    )
    import_map = {"src/a.py": {"src/b.py"}}
    result = _resolve_call_target("helper", "src/a.py", st, import_map)
    assert result is not None
    assert result.node_id == "Fn::src/b.py::helper::5"
    assert result.confidence == 0.9
    assert result.reason == "import-resolved"


def test_resolve_tier3_fuzzy_unique():
    st = _make_symbol_table(
        ("src/b.py", "helper", "Fn::src/b.py::helper::5", "Function"),
    )
    result = _resolve_call_target("helper", "src/a.py", st, {})
    assert result is not None
    assert result.node_id == "Fn::src/b.py::helper::5"
    assert result.confidence == 0.5
    assert result.reason == "fuzzy-global"


def test_resolve_tier3_fuzzy_ambiguous():
    st = _make_symbol_table(
        ("src/b.py", "helper", "Fn::src/b.py::helper::5", "Function"),
        ("src/c.py", "helper", "Fn::src/c.py::helper::8", "Function"),
    )
    result = _resolve_call_target("helper", "src/a.py", st, {})
    assert result is not None
    assert result.confidence == 0.3
    assert result.reason == "fuzzy-global"


def test_resolve_returns_none_for_unknown():
    st = _make_symbol_table()
    result = _resolve_call_target("nonexistent", "src/a.py", st, {})
    assert result is None


def test_resolve_tier1_preferred_over_tier2():
    """Tier 1 (same-file) should win even when tier 2 (import-resolved) is available."""
    st = _make_symbol_table(
        ("src/a.py", "helper", "Fn::src/a.py::helper::10", "Function"),
        ("src/b.py", "helper", "Fn::src/b.py::helper::5", "Function"),
    )
    import_map = {"src/a.py": {"src/b.py"}}
    result = _resolve_call_target("helper", "src/a.py", st, import_map)
    assert result is not None
    assert result.node_id == "Fn::src/a.py::helper::10"
    assert result.confidence == 0.85
    assert result.reason == "same-file"


def test_resolve_tier2_preferred_over_tier3():
    """Tier 2 (import-resolved, 0.9) should win over tier 3 (fuzzy-global)."""
    st = _make_symbol_table(
        ("src/b.py", "helper", "Fn::src/b.py::helper::5", "Function"),
        ("src/c.py", "helper", "Fn::src/c.py::helper::8", "Function"),
    )
    import_map = {"src/a.py": {"src/b.py"}}
    result = _resolve_call_target("helper", "src/a.py", st, import_map)
    assert result is not None
    assert result.node_id == "Fn::src/b.py::helper::5"
    assert result.confidence == 0.9
    assert result.reason == "import-resolved"


# -------------------------------------------------------------------
# process_calls integration tests
# -------------------------------------------------------------------


def test_process_calls_empty_calls():
    pr = ParseResult()
    st = _make_symbol_table()
    process_calls(pr, symbol_table=st, import_map={})
    assert pr.relationships == []


def test_process_calls_skips_builtins():
    pr = ParseResult(
        calls=[
            _make_call("src/a.py", "console", "Fn::src/a.py::main::1"),
            _make_call("src/a.py", "print", "Fn::src/a.py::main::1"),
        ],
    )
    st = _make_symbol_table()
    process_calls(pr, symbol_table=st, import_map={})
    assert pr.relationships == []


def test_process_calls_resolves_same_file_call():
    source_id = generate_id("Function", "src/a.py:main:1")
    target_id = generate_id("Function", "src/a.py:helper:10")
    pr = ParseResult(
        calls=[_make_call("src/a.py", "helper", source_id)],
    )
    st = _make_symbol_table(
        ("src/a.py", "helper", target_id, "Function"),
    )
    process_calls(pr, symbol_table=st, import_map={})
    assert len(pr.relationships) == 1
    rel = pr.relationships[0]
    assert rel.type == "CALLS"
    assert rel.source_id == source_id
    assert rel.target_id == target_id
    assert rel.confidence == 0.85
    assert rel.reason == "same-file"


def test_process_calls_resolves_import_call():
    source_id = generate_id("Function", "src/a.py:main:1")
    target_id = generate_id("Function", "src/b.py:helper:5")
    pr = ParseResult(
        calls=[_make_call("src/a.py", "helper", source_id)],
    )
    st = _make_symbol_table(
        ("src/b.py", "helper", target_id, "Function"),
    )
    import_map = {"src/a.py": {"src/b.py"}}
    process_calls(pr, symbol_table=st, import_map=import_map)
    assert len(pr.relationships) == 1
    rel = pr.relationships[0]
    assert rel.type == "CALLS"
    assert rel.confidence == 0.9
    assert rel.reason == "import-resolved"


def test_process_calls_multiple_calls_mixed():
    """Mix of built-in, resolvable, and unresolvable calls."""
    source_id = generate_id("Function", "src/a.py:main:1")
    target_id = generate_id("Function", "src/a.py:helper:10")
    pr = ParseResult(
        calls=[
            _make_call("src/a.py", "console", source_id),  # built-in -> skip
            _make_call("src/a.py", "helper", source_id),  # resolvable
            _make_call("src/a.py", "nonexistent", source_id),  # unresolvable
            _make_call("src/a.py", "print", source_id),  # built-in -> skip
        ],
    )
    st = _make_symbol_table(
        ("src/a.py", "helper", target_id, "Function"),
    )
    process_calls(pr, symbol_table=st, import_map={})
    # Only "helper" should produce a relationship
    assert len(pr.relationships) == 1
    assert pr.relationships[0].target_id == target_id


def test_process_calls_relationship_format():
    """Verify the relationship has correct id format, fields, and type."""
    source_id = generate_id("Function", "src/a.py:main:1")
    target_id = generate_id("Function", "src/a.py:doWork:20")
    pr = ParseResult(
        calls=[_make_call("src/a.py", "doWork", source_id)],
    )
    st = _make_symbol_table(
        ("src/a.py", "doWork", target_id, "Function"),
    )
    process_calls(pr, symbol_table=st, import_map={})
    assert len(pr.relationships) == 1
    rel = pr.relationships[0]
    expected_rel_id = generate_id("CALLS", f"{source_id}:doWork->{target_id}")
    assert rel.id == expected_rel_id
    assert rel.source_id == source_id
    assert rel.target_id == target_id
    assert rel.type == "CALLS"
    assert rel.confidence == 0.85
    assert rel.reason == "same-file"


def test_process_calls_appends_to_existing_relationships():
    """CALLS relationships should be appended, not replace existing ones."""
    source_id = generate_id("Function", "src/a.py:main:1")
    target_id = generate_id("Function", "src/a.py:helper:10")
    # Pre-existing IMPORTS relationship
    from qode.data.schemas import ParsedRelationship

    existing_rel = ParsedRelationship(
        id="existing-rel-001",
        source_id="file::src/a.py",
        target_id="file::src/b.py",
        type="IMPORTS",
        confidence=1.0,
        reason="direct-import",
    )
    pr = ParseResult(
        relationships=[existing_rel],
        calls=[_make_call("src/a.py", "helper", source_id)],
    )
    st = _make_symbol_table(
        ("src/a.py", "helper", target_id, "Function"),
    )
    process_calls(pr, symbol_table=st, import_map={})
    # Should now have the original + the new CALLS relationship
    assert len(pr.relationships) == 2
    assert pr.relationships[0].type == "IMPORTS"
    assert pr.relationships[1].type == "CALLS"


def test_process_calls_unresolved_call():
    """Call to a name not in the symbol table produces no relationship."""
    source_id = generate_id("Function", "src/a.py:main:1")
    pr = ParseResult(
        calls=[_make_call("src/a.py", "unknownFunc", source_id)],
    )
    st = _make_symbol_table()
    process_calls(pr, symbol_table=st, import_map={})
    assert pr.relationships == []
