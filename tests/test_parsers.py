"""Tests for the tree-sitter parsing infrastructure.

Covers:
- qode.core.parsers.parser  (parsing engine, ID generation, helpers)
- qode.core.parsers.queries  (query strings for 12 languages)
- qode.data.schemas           (Pydantic models for parse results)
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from qode.core.parsers.parser import (
    _CAPTURE_LABEL_MAP,
    _MAX_FILE_BYTES,
    BUILT_INS,
    DEFINITION_CAPTURE_KEYS,
    FUNCTION_NODE_TYPES,
    _get_language,
    _language_cache,
    find_enclosing_function_id,
    generate_id,
    get_definition_node,
    get_label_from_captures,
    is_node_exported,
    parse_batch,
    parse_file,
)
from qode.core.parsers.queries import LANGUAGE_QUERIES
from qode.data.schemas import (
    ExtractedCall,
    ExtractedHeritage,
    ExtractedImport,
    ParsedNode,
    ParsedNodeProperties,
    ParsedRelationship,
    ParsedSymbol,
    ParseResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_node(
    *,
    text: bytes = b"mock",
    node_type: str = "identifier",
    parent: object | None = None,
    children: list | None = None,
    start_point: tuple[int, int] = (0, 0),
    end_point: tuple[int, int] = (0, 4),
    child_fields: dict[str, object] | None = None,
) -> MagicMock:
    """Build a lightweight mock that quacks like a ``tree_sitter.Node``."""
    node = MagicMock()
    node.text = text
    node.type = node_type
    node.parent = parent
    node.children = children or []
    node.start_point = start_point
    node.end_point = end_point
    node.child_by_field_name = lambda name: (child_fields or {}).get(name)
    return node


# ---------------------------------------------------------------------------
# 1. generate_id() tests
# ---------------------------------------------------------------------------


class TestGenerateId:
    """Tests for deterministic ID generation."""

    def test_determinism(self):
        """Same inputs must always produce the same output."""
        a = generate_id("Function", "src/main.py:greet:10")
        b = generate_id("Function", "src/main.py:greet:10")
        assert a == b

    def test_format(self):
        """ID must be ``{label_lower}_{16 hex chars}``."""
        result = generate_id("Class", "some:key")
        assert re.fullmatch(r"class_[0-9a-f]{16}", result), result

    def test_label_lowered(self):
        """The label portion is always lower-cased."""
        result = generate_id("Interface", "k")
        assert result.startswith("interface_")

    def test_different_labels_differ(self):
        """Different labels with the same key still produce different IDs
        (because the label prefix differs)."""
        a = generate_id("Function", "same_key")
        b = generate_id("Method", "same_key")
        assert a != b

    def test_different_keys_differ(self):
        """Same label but different keys must produce different hashes."""
        a = generate_id("Function", "key_a")
        b = generate_id("Function", "key_b")
        assert a != b


# ---------------------------------------------------------------------------
# 2. get_label_from_captures() tests
# ---------------------------------------------------------------------------


class TestGetLabelFromCaptures:
    """Tests for capture-map → label resolution."""

    @pytest.mark.parametrize(
        "capture_key, expected_label",
        list(_CAPTURE_LABEL_MAP.items()),
    )
    def test_each_capture_key(self, capture_key, expected_label):
        """Every key in _CAPTURE_LABEL_MAP must return its mapped label."""
        node = _mock_node()
        result = get_label_from_captures({capture_key: node})
        assert result == expected_label

    def test_empty_dict_returns_none(self):
        """An empty capture map should return None."""
        assert get_label_from_captures({}) is None

    def test_unknown_key_returns_none(self):
        """Keys not in the map should yield None."""
        node = _mock_node()
        assert get_label_from_captures({"unknown.key": node}) is None

    def test_first_match_wins(self):
        """When multiple definition keys are present, the first match in
        iteration order is returned."""
        node = _mock_node()
        # Both are valid; whichever the dict iteration returns first wins.
        captures = {"definition.class": node, "definition.function": node}
        result = get_label_from_captures(captures)
        assert result in ("Class", "Function")


# ---------------------------------------------------------------------------
# 3. get_definition_node() tests
# ---------------------------------------------------------------------------


class TestGetDefinitionNode:
    """Tests for extracting the definition node from captures."""

    def test_returns_node_for_known_keys(self):
        """Each DEFINITION_CAPTURE_KEYS entry should yield the node."""
        for key in DEFINITION_CAPTURE_KEYS:
            node = _mock_node()
            result = get_definition_node({key: node})
            assert result is node, f"Failed for key {key}"

    def test_empty_captures(self):
        """An empty map must return None."""
        assert get_definition_node({}) is None

    def test_unknown_key(self):
        """Non-definition keys must return None."""
        node = _mock_node()
        assert get_definition_node({"call.name": node}) is None


# ---------------------------------------------------------------------------
# 4. is_node_exported() tests
# ---------------------------------------------------------------------------


class TestIsNodeExported:
    """Tests for per-language export/visibility detection."""

    # -- Python --

    def test_python_public_name(self):
        """Python names not starting with _ are public."""
        node = _mock_node()
        assert is_node_exported(node, "greet", "python") is True

    def test_python_private_name(self):
        """Python names starting with _ are private."""
        node = _mock_node()
        assert is_node_exported(node, "_helper", "python") is False

    def test_python_dunder_private(self):
        """Python dunder names are private (start with _)."""
        node = _mock_node()
        assert is_node_exported(node, "__init__", "python") is False

    # -- JavaScript / TypeScript / TSX -- (mock-based) --

    def test_js_not_exported(self):
        """JS node without export_statement ancestor is not exported."""
        node = _mock_node(parent=None)
        assert is_node_exported(node, "helper", "javascript") is False

    def test_js_exported(self):
        """JS node wrapped in export_statement is exported."""
        export_parent = _mock_node(node_type="export_statement", parent=None)
        node = _mock_node(parent=export_parent)
        assert is_node_exported(node, "helper", "javascript") is True

    def test_ts_not_exported(self):
        """TS node without export_statement ancestor is not exported."""
        node = _mock_node(parent=None)
        assert is_node_exported(node, "helper", "typescript") is False

    def test_ts_exported(self):
        """TS node wrapped in export_statement is exported."""
        export_parent = _mock_node(node_type="export_statement", parent=None)
        node = _mock_node(parent=export_parent)
        assert is_node_exported(node, "helper", "typescript") is True

    def test_tsx_exported(self):
        """TSX node wrapped in export_statement is exported."""
        export_parent = _mock_node(node_type="export_statement", parent=None)
        node = _mock_node(parent=export_parent)
        assert is_node_exported(node, "Comp", "tsx") is True

    # -- Go --

    def test_go_exported_upper(self):
        """Go names starting with uppercase are exported."""
        node = _mock_node()
        assert is_node_exported(node, "Serve", "go") is True

    def test_go_unexported_lower(self):
        """Go names starting with lowercase are unexported."""
        node = _mock_node()
        assert is_node_exported(node, "serve", "go") is False

    def test_go_empty_name(self):
        """Go empty name is not exported."""
        node = _mock_node()
        assert is_node_exported(node, "", "go") is False

    # -- C / C++ --

    def test_c_always_false(self):
        """C has no native export concept → always False."""
        node = _mock_node()
        assert is_node_exported(node, "main", "c") is False

    def test_cpp_always_false(self):
        """C++ has no native export concept → always False."""
        node = _mock_node()
        assert is_node_exported(node, "main", "cpp") is False

    # -- Rust --

    def test_rust_not_pub(self):
        """Rust without visibility modifier is not exported."""
        node = _mock_node(children=[])
        assert is_node_exported(node, "helper", "rust") is False

    def test_rust_pub(self):
        """Rust with ``pub`` visibility modifier is exported."""
        vis = _mock_node(node_type="visibility_modifier", text=b"pub")
        node = _mock_node(children=[vis])
        assert is_node_exported(node, "helper", "rust") is True

    # -- Kotlin --

    def test_kotlin_default_public(self):
        """Kotlin defaults to public."""
        node = _mock_node(children=[])
        assert is_node_exported(node, "greet", "kotlin") is True

    def test_kotlin_private(self):
        """Kotlin with private modifier is not exported."""
        mod = _mock_node(node_type="modifiers", text=b"private")
        node = _mock_node(children=[mod])
        assert is_node_exported(node, "helper", "kotlin") is False

    # -- Unknown language --

    def test_unknown_language_returns_false(self):
        """An unrecognised language falls through to False."""
        node = _mock_node()
        assert is_node_exported(node, "x", "brainfuck") is False


# -- Real AST is_node_exported tests via parse_file --------------------


class TestIsNodeExportedRealAST:
    """Use parse_file to generate real AST nodes and verify export logic."""

    def test_python_exported_via_parse(self):
        """Public Python functions have is_exported=True."""
        pytest.importorskip("tree_sitter_python")
        code = b"def greet(): pass\n"
        result = parse_file("test.py", code, "python")
        assert len(result.nodes) == 1
        assert result.nodes[0].properties.is_exported is True

    def test_python_private_via_parse(self):
        """Private Python functions have is_exported=False."""
        pytest.importorskip("tree_sitter_python")
        code = b"def _helper(): pass\n"
        result = parse_file("test.py", code, "python")
        assert len(result.nodes) == 1
        assert result.nodes[0].properties.is_exported is False

    def test_js_exported_via_parse(self):
        """JavaScript exported arrow function has is_exported=True."""
        pytest.importorskip("tree_sitter_javascript")
        code = b"export const greet = () => {};\n"
        result = parse_file("test.js", code, "javascript")
        exported = [n for n in result.nodes if n.properties.name == "greet"]
        # The JS query has both a lexical_declaration pattern and an
        # export_statement>lexical_declaration pattern, so exported
        # arrow functions may match twice.
        assert len(exported) >= 1
        assert all(n.properties.is_exported for n in exported)

    def test_js_not_exported_via_parse(self):
        """JavaScript non-exported function has is_exported=False."""
        pytest.importorskip("tree_sitter_javascript")
        code = b"function helper() {}\n"
        result = parse_file("test.js", code, "javascript")
        funcs = [n for n in result.nodes if n.properties.name == "helper"]
        assert len(funcs) == 1
        assert funcs[0].properties.is_exported is False

    def test_ts_exported_via_parse(self):
        """TypeScript exported function has is_exported=True."""
        pytest.importorskip("tree_sitter_typescript")
        code = b"export function greet(): void {}\n"
        result = parse_file("test.ts", code, "typescript")
        exported = [n for n in result.nodes if n.properties.name == "greet"]
        assert len(exported) == 1
        assert exported[0].properties.is_exported is True


# ---------------------------------------------------------------------------
# 5. Query compilation tests
# ---------------------------------------------------------------------------


class TestQueryCompilation:
    """Verify that query strings compile against installed languages."""

    @pytest.mark.parametrize(
        "lang_key",
        ["python", "javascript", "typescript", "tsx"],
    )
    def test_installed_language_query_compiles(self, lang_key):
        """Queries for installed languages must compile without error."""
        if lang_key == "python":
            pytest.importorskip("tree_sitter_python")
        elif lang_key == "javascript":
            pytest.importorskip("tree_sitter_javascript")
        else:
            pytest.importorskip("tree_sitter_typescript")

        lang_obj = _get_language(lang_key)
        assert lang_obj is not None

        query_lang = "typescript" if lang_key == "tsx" else lang_key
        query_str = LANGUAGE_QUERIES[query_lang]
        # Must not raise
        lang_obj.query(query_str)

    @pytest.mark.parametrize(
        "lang_key",
        ["java", "go", "rust", "c", "cpp", "csharp", "php", "kotlin", "swift"],
    )
    def test_uninstalled_language_returns_none(self, lang_key):
        """_get_language returns None for languages whose packages are
        not installed."""
        # Clear any cached entry so we actually try loading
        _language_cache.pop(lang_key, None)
        assert _get_language(lang_key) is None


# ---------------------------------------------------------------------------
# 6. parse_file() end-to-end tests
# ---------------------------------------------------------------------------


class TestParseFilePython:
    """End-to-end parsing of Python source code."""

    @pytest.fixture(autouse=True)
    def _require_python(self):
        pytest.importorskip("tree_sitter_python")

    CODE = b"""\
import os
from pathlib import Path

class Animal:
    def speak(self):
        pass

class Dog(Animal):
    def bark(self):
        greet()
"""

    def test_extracts_classes(self):
        """Two classes (Animal, Dog) should be extracted."""
        r = parse_file("test.py", self.CODE, "python")
        classes = [n for n in r.nodes if n.label == "Class"]
        names = {c.properties.name for c in classes}
        assert names == {"Animal", "Dog"}

    def test_extracts_functions(self):
        """Two methods (speak, bark) should be extracted as functions
        (Python query uses @definition.function for all function_definition)."""
        r = parse_file("test.py", self.CODE, "python")
        funcs = [n for n in r.nodes if n.label == "Function"]
        names = {f.properties.name for f in funcs}
        assert "speak" in names
        assert "bark" in names

    def test_extracts_imports(self):
        """Two imports (os, pathlib) should be extracted."""
        r = parse_file("test.py", self.CODE, "python")
        paths = {imp.raw_import_path for imp in r.imports}
        assert "os" in paths
        assert "pathlib" in paths

    def test_extracts_calls(self):
        """greet() call should be extracted (not a built-in)."""
        r = parse_file("test.py", self.CODE, "python")
        call_names = {c.called_name for c in r.calls}
        assert "greet" in call_names

    def test_filters_builtin_calls(self):
        """Built-in calls like pass are not captured; print would be
        filtered."""
        code = b"print('hello')\ngreet()\n"
        r = parse_file("test.py", code, "python")
        call_names = {c.called_name for c in r.calls}
        assert "print" not in call_names
        assert "greet" in call_names

    def test_extracts_heritage(self):
        """Dog extends Animal should appear in heritage."""
        r = parse_file("test.py", self.CODE, "python")
        heritages = [
            h for h in r.heritage if h.class_name == "Dog" and h.parent_name == "Animal"
        ]
        assert len(heritages) >= 1
        assert heritages[0].kind == "extends"

    def test_file_count(self):
        """file_count should be 1 after parsing one file."""
        r = parse_file("test.py", self.CODE, "python")
        assert r.file_count == 1

    def test_relationships_created(self):
        """Each node should have a corresponding DEFINES relationship."""
        r = parse_file("test.py", self.CODE, "python")
        assert len(r.relationships) == len(r.nodes)
        for rel in r.relationships:
            assert rel.type == "DEFINES"

    def test_symbols_created(self):
        """Each node should have a corresponding symbol table entry."""
        r = parse_file("test.py", self.CODE, "python")
        assert len(r.symbols) == len(r.nodes)

    def test_start_end_lines(self):
        """Start and end lines should be positive 1-indexed integers."""
        r = parse_file("test.py", self.CODE, "python")
        for node in r.nodes:
            assert node.properties.start_line >= 1
            assert node.properties.end_line >= node.properties.start_line


class TestParseFileJavaScript:
    """End-to-end parsing of JavaScript source code."""

    @pytest.fixture(autouse=True)
    def _require_js(self):
        pytest.importorskip("tree_sitter_javascript")

    CODE = b"""\
import { foo } from './utils';

function greet(name) {
    return name;
}

class Animal {
    constructor(name) {
        this.name = name;
    }
}

const helper = () => {
    customFunc();
};

export const exported = (x) => x;
"""

    def test_extracts_function_greet(self):
        """function greet should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        names = {n.properties.name for n in r.nodes}
        assert "greet" in names

    def test_extracts_class_animal(self):
        """class Animal should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        classes = [n for n in r.nodes if n.label == "Class"]
        assert any(c.properties.name == "Animal" for c in classes)

    def test_extracts_constructor(self):
        """constructor method should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        methods = [n for n in r.nodes if n.label == "Method"]
        assert any(m.properties.name == "constructor" for m in methods)

    def test_extracts_arrow_functions(self):
        """Arrow functions helper and exported should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        names = {n.properties.name for n in r.nodes}
        assert "helper" in names
        assert "exported" in names

    def test_extracts_import(self):
        """Import from './utils' should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        paths = {imp.raw_import_path for imp in r.imports}
        assert "./utils" in paths

    def test_extracts_calls(self):
        """customFunc call should be extracted."""
        r = parse_file("test.js", self.CODE, "javascript")
        call_names = {c.called_name for c in r.calls}
        assert "customFunc" in call_names

    def test_export_detection(self):
        """exported arrow function should have is_exported=True."""
        r = parse_file("test.js", self.CODE, "javascript")
        exp = [n for n in r.nodes if n.properties.name == "exported"]
        # The JS query has both a lexical_declaration pattern and an
        # export_statement>lexical_declaration pattern, so exported
        # arrow functions may match twice.
        assert len(exp) >= 1
        assert all(n.properties.is_exported for n in exp)

    def test_non_exported_function(self):
        """greet function should have is_exported=False."""
        r = parse_file("test.js", self.CODE, "javascript")
        greet = [n for n in r.nodes if n.properties.name == "greet"]
        assert len(greet) == 1
        assert greet[0].properties.is_exported is False


class TestParseFileTypeScript:
    """End-to-end parsing of TypeScript source code."""

    @pytest.fixture(autouse=True)
    def _require_ts(self):
        pytest.importorskip("tree_sitter_typescript")

    CODE = b"""\
import { Service } from './service';

interface Serializable {
    serialize(): string;
}

class UserService implements Serializable {
    serialize(): string {
        return '';
    }

    getUser(id: number): void {
        fetchData();
    }
}

export function createService(): UserService {
    return new UserService();
}
"""

    def test_extracts_interface(self):
        """interface Serializable should be extracted."""
        r = parse_file("test.ts", self.CODE, "typescript")
        ifaces = [n for n in r.nodes if n.label == "Interface"]
        assert any(i.properties.name == "Serializable" for i in ifaces)

    def test_extracts_class(self):
        """class UserService should be extracted."""
        r = parse_file("test.ts", self.CODE, "typescript")
        classes = [n for n in r.nodes if n.label == "Class"]
        assert any(c.properties.name == "UserService" for c in classes)

    def test_extracts_methods(self):
        """Methods serialize and getUser should be extracted."""
        r = parse_file("test.ts", self.CODE, "typescript")
        methods = [n for n in r.nodes if n.label == "Method"]
        method_names = {m.properties.name for m in methods}
        assert "serialize" in method_names
        assert "getUser" in method_names

    def test_extracts_exported_function(self):
        """export function createService should be extracted and exported."""
        r = parse_file("test.ts", self.CODE, "typescript")
        funcs = [n for n in r.nodes if n.properties.name == "createService"]
        assert len(funcs) == 1
        assert funcs[0].properties.is_exported is True

    def test_extracts_import(self):
        """Import from './service' should be extracted."""
        r = parse_file("test.ts", self.CODE, "typescript")
        paths = {imp.raw_import_path for imp in r.imports}
        assert "./service" in paths

    def test_extracts_calls(self):
        """fetchData() call should be extracted."""
        r = parse_file("test.ts", self.CODE, "typescript")
        call_names = {c.called_name for c in r.calls}
        assert "fetchData" in call_names

    def test_heritage_implements(self):
        """UserService implements Serializable should be in heritage."""
        r = parse_file("test.ts", self.CODE, "typescript")
        impl = [
            h
            for h in r.heritage
            if h.class_name == "UserService" and h.parent_name == "Serializable"
        ]
        assert len(impl) >= 1
        assert impl[0].kind == "implements"


class TestParseFileTSX:
    """TSX detection: .tsx files should use the TSX grammar."""

    @pytest.fixture(autouse=True)
    def _require_ts(self):
        pytest.importorskip("tree_sitter_typescript")

    def test_tsx_file_parsed(self):
        """parse_file with .tsx extension and language='typescript' should
        use the TSX grammar variant."""
        code = b"""\
export function Component() {
    return <div>Hello</div>;
}
"""
        r = parse_file("component.tsx", code, "typescript")
        # Should successfully parse (not crash) and extract the function
        names = {n.properties.name for n in r.nodes}
        assert "Component" in names

    def test_tsx_file_language_metadata(self):
        """Parsed nodes from .tsx files should still report 'typescript'
        as their language (the base language key)."""
        code = b"export function App() { return null; }\n"
        r = parse_file("app.tsx", code, "typescript")
        assert len(r.nodes) >= 1
        assert r.nodes[0].properties.language == "typescript"


# ---------------------------------------------------------------------------
# 7. Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty files, oversized files, unsupported languages."""

    @pytest.fixture(autouse=True)
    def _require_python(self):
        pytest.importorskip("tree_sitter_python")

    def test_empty_file(self):
        """An empty file should produce an empty ParseResult with
        file_count=1."""
        r = parse_file("empty.py", b"", "python")
        assert r.nodes == []
        assert r.imports == []
        assert r.calls == []
        assert r.heritage == []
        assert r.file_count == 1

    def test_large_file_skipped(self):
        """Files exceeding 512 KB should be skipped (file_count=0)."""
        big = b"x" * (_MAX_FILE_BYTES + 1)
        r = parse_file("big.py", big, "python")
        assert r.nodes == []
        assert r.file_count == 0

    def test_unsupported_language(self):
        """A language with no loader or query → empty result."""
        r = parse_file("test.xyz", b"code", "nonexistent_lang")
        assert r.nodes == []
        assert r.file_count == 0

    def test_missing_language_package_graceful(self):
        """A language whose package is not installed → empty result."""
        _language_cache.pop("java", None)
        r = parse_file("Test.java", b"class Foo {}", "java")
        assert r.nodes == []
        assert r.file_count == 0

    def test_syntax_error_still_parses(self):
        """Tree-sitter is error-tolerant; malformed code should still
        produce partial results without crashing."""
        code = b"def foo(\n  class Bar: pass\n"
        r = parse_file("bad.py", code, "python")
        # May or may not extract entities, but must not raise
        assert isinstance(r, ParseResult)


# ---------------------------------------------------------------------------
# 8. parse_batch() tests
# ---------------------------------------------------------------------------


class TestParseBatch:
    """Tests for multi-file batch parsing."""

    @pytest.fixture(autouse=True)
    def _require_python(self):
        pytest.importorskip("tree_sitter_python")

    def test_multiple_files(self):
        """Batch parsing multiple files merges results."""
        files = [
            ("a.py", b"def foo(): pass\n", "python"),
            ("b.py", b"def bar(): pass\n", "python"),
        ]
        r = parse_batch(files)
        names = {n.properties.name for n in r.nodes}
        assert "foo" in names
        assert "bar" in names
        assert r.file_count == 2

    def test_mixed_languages(self):
        """Batch parsing mixed languages produces correct results."""
        pytest.importorskip("tree_sitter_javascript")
        files = [
            ("a.py", b"def foo(): pass\n", "python"),
            ("b.js", b"function bar() {}\n", "javascript"),
        ]
        r = parse_batch(files)
        names = {n.properties.name for n in r.nodes}
        assert "foo" in names
        assert "bar" in names
        assert r.file_count == 2

    def test_file_count_aggregation(self):
        """file_count should equal the number of successfully parsed files."""
        files = [
            ("a.py", b"x = 1\n", "python"),
            ("b.py", b"y = 2\n", "python"),
            ("c.py", b"z = 3\n", "python"),
        ]
        r = parse_batch(files)
        assert r.file_count == 3

    def test_empty_batch(self):
        """An empty batch should produce a default ParseResult."""
        r = parse_batch([])
        assert r.file_count == 0
        assert r.nodes == []


# ---------------------------------------------------------------------------
# 9. BUILT_INS tests
# ---------------------------------------------------------------------------


class TestBuiltIns:
    """Tests for the BUILT_INS frozenset."""

    @pytest.mark.parametrize(
        "name",
        [
            "print",
            "len",
            "console",
            "log",
            "require",
            "forEach",
            "printf",
            "malloc",
            "println",
            "append",
            "sorted",
        ],
    )
    def test_known_builtins_present(self, name):
        """Well-known built-in names must be in the set."""
        assert name in BUILT_INS

    @pytest.mark.parametrize(
        "name",
        ["myFunction", "customHelper", "processData", "UserService"],
    )
    def test_custom_names_absent(self, name):
        """User-defined function names must NOT be in BUILT_INS."""
        assert name not in BUILT_INS

    def test_builtin_calls_filtered_in_parse(self):
        """Calls to built-in names should not appear in parse results."""
        pytest.importorskip("tree_sitter_python")
        code = b"print('hello')\nlen([1, 2])\ncustomFunc()\n"
        r = parse_file("test.py", code, "python")
        call_names = {c.called_name for c in r.calls}
        assert "print" not in call_names
        assert "len" not in call_names
        assert "customFunc" in call_names

    def test_is_frozenset(self):
        """BUILT_INS should be a frozenset (immutable)."""
        assert isinstance(BUILT_INS, frozenset)


# ---------------------------------------------------------------------------
# 10. FUNCTION_NODE_TYPES tests
# ---------------------------------------------------------------------------


class TestFunctionNodeTypes:
    """Tests for the FUNCTION_NODE_TYPES frozenset."""

    @pytest.mark.parametrize(
        "node_type",
        [
            "function_declaration",
            "function_definition",
            "arrow_function",
            "method_definition",
            "method_declaration",
            "function_item",
            "constructor_declaration",
            "init_declaration",
        ],
    )
    def test_known_types_present(self, node_type):
        """Known function node types must be in the set."""
        assert node_type in FUNCTION_NODE_TYPES

    def test_is_frozenset(self):
        """FUNCTION_NODE_TYPES should be a frozenset (immutable)."""
        assert isinstance(FUNCTION_NODE_TYPES, frozenset)


# ---------------------------------------------------------------------------
# 11. find_enclosing_function_id() tests
# ---------------------------------------------------------------------------


class TestFindEnclosingFunctionId:
    """Tests for walking up the AST to find enclosing functions."""

    def test_call_inside_function(self):
        """A call node inside a function_definition should return an ID."""
        name_node = _mock_node(text=b"my_func")
        func_node = _mock_node(
            node_type="function_definition",
            parent=None,
            start_point=(9, 0),
            child_fields={"name": name_node},
        )
        call_node = _mock_node(parent=func_node)
        result = find_enclosing_function_id(call_node, "src/main.py")
        assert result is not None
        assert result.startswith("function_")

    def test_call_at_top_level(self):
        """A call at the top level (no function ancestor) returns None."""
        node = _mock_node(parent=None)
        result = find_enclosing_function_id(node, "src/main.py")
        assert result is None

    def test_call_inside_method(self):
        """A call inside a method_definition should produce a method_ ID."""
        name_node = _mock_node(text=b"do_stuff")
        method_node = _mock_node(
            node_type="method_definition",
            parent=None,
            start_point=(5, 4),
            child_fields={"name": name_node},
        )
        call_node = _mock_node(parent=method_node)
        result = find_enclosing_function_id(call_node, "test.js")
        assert result is not None
        assert result.startswith("method_")

    def test_deterministic_id(self):
        """The returned ID should be deterministic for identical inputs."""
        name_node = _mock_node(text=b"handler")
        func_node = _mock_node(
            node_type="function_definition",
            parent=None,
            start_point=(3, 0),
            child_fields={"name": name_node},
        )
        call_a = _mock_node(parent=func_node)
        call_b = _mock_node(parent=func_node)
        id_a = find_enclosing_function_id(call_a, "f.py")
        id_b = find_enclosing_function_id(call_b, "f.py")
        assert id_a == id_b

    def test_enclosing_function_via_parse(self):
        """In a real parse, calls inside functions should have source_id
        that differs from the file_id (i.e., they found the enclosing fn)."""
        pytest.importorskip("tree_sitter_python")
        code = b"""\
def outer():
    customFunc()
"""
        r = parse_file("test.py", code, "python")
        file_id = generate_id("File", "test.py")
        custom_calls = [c for c in r.calls if c.called_name == "customFunc"]
        assert len(custom_calls) == 1
        # source_id should be the enclosing function, not the file
        assert custom_calls[0].source_id != file_id

    def test_top_level_call_uses_file_id(self):
        """A top-level call should fall back to the file_id as source_id."""
        pytest.importorskip("tree_sitter_python")
        code = b"customFunc()\n"
        r = parse_file("test.py", code, "python")
        file_id = generate_id("File", "test.py")
        custom_calls = [c for c in r.calls if c.called_name == "customFunc"]
        assert len(custom_calls) == 1
        assert custom_calls[0].source_id == file_id


# ---------------------------------------------------------------------------
# 12. Schema model tests
# ---------------------------------------------------------------------------


class TestSchemaModels:
    """Tests for the Pydantic models in qode.data.schemas."""

    def test_parsed_node_properties_creation(self):
        """ParsedNodeProperties can be created with required fields."""
        props = ParsedNodeProperties(
            name="foo",
            file_path="test.py",
            start_line=1,
            end_line=5,
            language="python",
            is_exported=True,
        )
        assert props.name == "foo"
        assert props.start_line == 1
        assert props.is_exported is True

    def test_parsed_node_validates_label(self):
        """ParsedNode requires a valid NodeLabel literal."""
        props = ParsedNodeProperties(
            name="bar",
            file_path="test.py",
            start_line=1,
            end_line=2,
            language="python",
            is_exported=False,
        )
        node = ParsedNode(id="function_abc123", label="Function", properties=props)
        assert node.label == "Function"

    def test_parsed_node_rejects_invalid_label(self):
        """ParsedNode should reject an invalid label."""
        props = ParsedNodeProperties(
            name="bar",
            file_path="test.py",
            start_line=1,
            end_line=2,
            language="python",
            is_exported=False,
        )
        with pytest.raises(ValidationError):
            ParsedNode(id="bad_abc123", label="InvalidLabel", properties=props)

    def test_parse_result_mutable(self):
        """ParseResult is mutable — lists can be appended to."""
        r = ParseResult()
        assert r.nodes == []
        assert r.file_count == 0
        r.file_count = 5
        assert r.file_count == 5

        # Can append to lists
        sym = ParsedSymbol(
            file_path="test.py",
            name="foo",
            node_id="x",
            type="Function",
        )
        r.symbols.append(sym)
        assert len(r.symbols) == 1

    def test_frozen_models_raise_on_mutation(self):
        """Frozen models (ParsedNodeProperties, ParsedNode, etc.) should
        raise on attribute mutation."""
        props = ParsedNodeProperties(
            name="foo",
            file_path="test.py",
            start_line=1,
            end_line=2,
            language="python",
            is_exported=True,
        )
        with pytest.raises(ValidationError):
            props.name = "bar"

        node = ParsedNode(
            id="function_abc123",
            label="Function",
            properties=props,
        )
        with pytest.raises(ValidationError):
            node.id = "changed"

    def test_extracted_import_creation(self):
        """ExtractedImport can be created."""
        imp = ExtractedImport(
            file_path="test.py",
            raw_import_path="os",
            language="python",
        )
        assert imp.raw_import_path == "os"

    def test_extracted_call_creation(self):
        """ExtractedCall can be created."""
        call = ExtractedCall(
            file_path="test.py",
            called_name="foo",
            source_id="function_abc123",
        )
        assert call.called_name == "foo"

    def test_extracted_heritage_creation(self):
        """ExtractedHeritage can be created."""
        h = ExtractedHeritage(
            file_path="test.py",
            class_name="Dog",
            parent_name="Animal",
            kind="extends",
        )
        assert h.kind == "extends"

    def test_extracted_heritage_invalid_kind(self):
        """ExtractedHeritage should reject invalid kind values."""
        with pytest.raises(ValidationError):
            ExtractedHeritage(
                file_path="test.py",
                class_name="Dog",
                parent_name="Animal",
                kind="invalid_kind",
            )

    def test_parsed_relationship_creation(self):
        """ParsedRelationship can be created."""
        rel = ParsedRelationship(
            id="defines_abc",
            source_id="file_abc",
            target_id="function_abc",
            type="DEFINES",
            confidence=1.0,
            reason="tree-sitter query match",
        )
        assert rel.type == "DEFINES"
        assert rel.confidence == 1.0


# ---------------------------------------------------------------------------
# Query coverage tests
# ---------------------------------------------------------------------------


class TestLanguageQueries:
    """Tests for LANGUAGE_QUERIES dictionary."""

    @pytest.mark.parametrize(
        "lang",
        [
            "typescript",
            "javascript",
            "python",
            "java",
            "c",
            "go",
            "cpp",
            "csharp",
            "rust",
            "php",
            "kotlin",
            "swift",
        ],
    )
    def test_all_12_languages_have_queries(self, lang):
        """All 12 supported languages should have query strings."""
        assert lang in LANGUAGE_QUERIES
        assert isinstance(LANGUAGE_QUERIES[lang], str)
        assert len(LANGUAGE_QUERIES[lang]) > 0

    def test_query_count(self):
        """Exactly 12 languages should be defined."""
        assert len(LANGUAGE_QUERIES) == 12
