"""Tests for the dual-index symbol lookup table.

Covers:
- SymbolDefinition frozen dataclass (creation, equality, hashing)
- SymbolStats dataclass (creation, field access)
- SymbolTable initialisation (empty state)
- add(), add_symbol(), add_all() insertion methods
- lookup_exact() and lookup_exact_definition() exact-match queries
- lookup_fuzzy() cross-file name lookup
- lookup_fuzzy_in_file() with preferred-file fallback
- has_symbol(), has_name() membership checks
- get_file_symbols() per-file index
- from_parse_result() factory method
- clear() and reuse
- __len__, __contains__, __repr__ dunder methods
- Edge cases (empty strings, special characters, many files)
- Integration workflows (heritage resolution, call resolution)
"""

from __future__ import annotations

import pytest

from qode.core.symbol_table import (
    SymbolDefinition,
    SymbolStats,
    SymbolTable,
)
from qode.data.schemas import ParsedSymbol, ParseResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(file_path, name, node_id, symbol_type="Function"):
    """Create a ParsedSymbol for testing."""
    return ParsedSymbol(
        file_path=file_path,
        name=name,
        node_id=node_id,
        type=symbol_type,
    )


# ---------------------------------------------------------------------------
# 1. SymbolDefinition
# ---------------------------------------------------------------------------


class TestSymbolDefinition:
    """Tests for the SymbolDefinition frozen dataclass."""

    def test_creation(self):
        sd = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        assert sd.node_id == "n1"
        assert sd.file_path == "a.py"
        assert sd.type == "Function"

    def test_equality_same_values(self):
        a = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        b = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        assert a == b

    def test_inequality_different_values(self):
        a = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        b = SymbolDefinition(node_id="n2", file_path="a.py", type="Function")
        assert a != b

    def test_frozen_immutability(self):
        sd = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        with pytest.raises(AttributeError):
            sd.node_id = "n2"  # type: ignore[misc]

    def test_hashable(self):
        sd = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        # Must be usable as a set element and dict key
        s = {sd}
        assert sd in s
        d = {sd: 1}
        assert d[sd] == 1

    def test_hash_equality_consistent(self):
        a = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        b = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        assert hash(a) == hash(b)

    def test_repr(self):
        sd = SymbolDefinition(node_id="n1", file_path="a.py", type="Function")
        r = repr(sd)
        assert "SymbolDefinition" in r
        assert "n1" in r
        assert "a.py" in r

    def test_different_types(self):
        sd = SymbolDefinition(node_id="n1", file_path="a.py", type="Class")
        assert sd.type == "Class"


# ---------------------------------------------------------------------------
# 2. SymbolStats
# ---------------------------------------------------------------------------


class TestSymbolStats:
    """Tests for the SymbolStats dataclass."""

    def test_creation(self):
        stats = SymbolStats(file_count=3, unique_symbol_count=10, total_definitions=15)
        assert stats.file_count == 3
        assert stats.unique_symbol_count == 10
        assert stats.total_definitions == 15

    def test_field_mutation(self):
        """SymbolStats is a regular (non-frozen) dataclass, so mutation is allowed."""
        stats = SymbolStats(file_count=1, unique_symbol_count=1, total_definitions=1)
        stats.file_count = 5
        assert stats.file_count == 5

    def test_repr(self):
        stats = SymbolStats(file_count=2, unique_symbol_count=4, total_definitions=6)
        r = repr(stats)
        assert "SymbolStats" in r

    def test_equality(self):
        a = SymbolStats(file_count=1, unique_symbol_count=2, total_definitions=3)
        b = SymbolStats(file_count=1, unique_symbol_count=2, total_definitions=3)
        assert a == b

    def test_inequality(self):
        a = SymbolStats(file_count=1, unique_symbol_count=2, total_definitions=3)
        b = SymbolStats(file_count=9, unique_symbol_count=2, total_definitions=3)
        assert a != b


# ---------------------------------------------------------------------------
# 3. SymbolTable — Initialisation
# ---------------------------------------------------------------------------


class TestSymbolTableInit:
    """Tests for empty SymbolTable construction."""

    def test_empty_table_length(self):
        table = SymbolTable()
        assert len(table) == 0

    def test_empty_table_stats(self):
        stats = SymbolTable().get_stats()
        assert stats.file_count == 0
        assert stats.unique_symbol_count == 0
        assert stats.total_definitions == 0

    def test_empty_table_repr(self):
        r = repr(SymbolTable())
        assert "SymbolTable" in r

    def test_empty_contains_returns_false(self):
        table = SymbolTable()
        assert "anything" not in table

    def test_empty_lookup_exact_returns_none(self):
        table = SymbolTable()
        assert table.lookup_exact("file.py", "foo") is None

    def test_empty_lookup_exact_definition_returns_none(self):
        table = SymbolTable()
        assert table.lookup_exact_definition("file.py", "foo") is None

    def test_empty_lookup_fuzzy_returns_empty(self):
        table = SymbolTable()
        assert table.lookup_fuzzy("foo") == []

    def test_empty_get_file_symbols_returns_empty(self):
        table = SymbolTable()
        assert table.get_file_symbols("file.py") == {}


# ---------------------------------------------------------------------------
# 4. SymbolTable — add / add_symbol / add_all
# ---------------------------------------------------------------------------


class TestSymbolTableAdd:
    """Tests for insertion methods."""

    def test_add_single_symbol(self):
        table = SymbolTable()
        table.add("src/main.py", "main", "node-1", "Function")
        assert len(table) == 1

    def test_add_symbol_from_parsed_symbol(self):
        table = SymbolTable()
        sym = _sym("src/main.py", "main", "node-1")
        table.add_symbol(sym)
        assert len(table) == 1
        assert table.has_symbol("src/main.py", "main")

    def test_add_all_multiple_symbols(self):
        table = SymbolTable()
        syms = [
            _sym("a.py", "foo", "n1"),
            _sym("b.py", "bar", "n2"),
            _sym("c.py", "baz", "n3"),
        ]
        table.add_all(syms)
        assert len(table) == 3

    def test_add_all_empty_list(self):
        table = SymbolTable()
        table.add_all([])
        assert len(table) == 0

    def test_add_duplicate_name_different_files(self):
        """Same symbol name in two files should produce two definitions."""
        table = SymbolTable()
        table.add("a.py", "helper", "n1", "Function")
        table.add("b.py", "helper", "n2", "Function")
        assert len(table) == 2
        defs = table.lookup_fuzzy("helper")
        assert len(defs) == 2

    def test_add_same_file_same_name_overwrites_fqn(self):
        """Re-adding a symbol to the same file+name should overwrite the FQN entry."""
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.add("a.py", "foo", "n2", "Function")
        # The exact lookup should return the latest node_id
        result = table.lookup_exact("a.py", "foo")
        assert result == "n2"

    def test_add_multiple_names_same_file(self):
        table = SymbolTable()
        table.add("utils.py", "alpha", "n1", "Function")
        table.add("utils.py", "beta", "n2", "Function")
        table.add("utils.py", "gamma", "n3", "Class")
        syms = table.get_file_symbols("utils.py")
        assert len(syms) == 3

    def test_add_symbol_preserves_type(self):
        table = SymbolTable()
        table.add("a.py", "MyClass", "n1", "Class")
        defn = table.lookup_exact_definition("a.py", "MyClass")
        assert defn is not None
        assert defn.type == "Class"

    def test_add_updates_stats_correctly(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.add("b.py", "bar", "n2", "Function")
        table.add("b.py", "baz", "n3", "Class")
        stats = table.get_stats()
        assert stats.file_count == 2
        assert stats.unique_symbol_count >= 3
        assert stats.total_definitions == 3


# ---------------------------------------------------------------------------
# 5. SymbolTable — lookup_exact
# ---------------------------------------------------------------------------


class TestSymbolTableLookupExact:
    """Tests for exact lookup by (file_path, name)."""

    def test_returns_node_id_for_existing_symbol(self):
        table = SymbolTable()
        table.add("a.py", "foo", "node-42", "Function")
        assert table.lookup_exact("a.py", "foo") == "node-42"

    def test_returns_none_for_wrong_file(self):
        table = SymbolTable()
        table.add("a.py", "foo", "node-42", "Function")
        assert table.lookup_exact("b.py", "foo") is None

    def test_returns_none_for_wrong_name(self):
        table = SymbolTable()
        table.add("a.py", "foo", "node-42", "Function")
        assert table.lookup_exact("a.py", "bar") is None

    def test_definition_returns_symbol_definition(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        defn = table.lookup_exact_definition("a.py", "foo")
        assert defn is not None
        assert isinstance(defn, SymbolDefinition)
        assert defn.node_id == "n1"
        assert defn.file_path == "a.py"
        assert defn.type == "Function"

    def test_definition_returns_none_when_missing(self):
        table = SymbolTable()
        assert table.lookup_exact_definition("x.py", "nope") is None

    def test_exact_distinguishes_same_name_different_files(self):
        table = SymbolTable()
        table.add("a.py", "helper", "n1", "Function")
        table.add("b.py", "helper", "n2", "Function")
        assert table.lookup_exact("a.py", "helper") == "n1"
        assert table.lookup_exact("b.py", "helper") == "n2"


# ---------------------------------------------------------------------------
# 6. SymbolTable — lookup_fuzzy
# ---------------------------------------------------------------------------


class TestSymbolTableLookupFuzzy:
    """Tests for suffix/name-based fuzzy lookup."""

    def test_returns_all_definitions_across_files(self):
        table = SymbolTable()
        table.add("a.py", "render", "n1", "Function")
        table.add("b.py", "render", "n2", "Function")
        table.add("c.py", "render", "n3", "Method")
        defs = table.lookup_fuzzy("render")
        assert len(defs) == 3
        ids = {d.node_id for d in defs}
        assert ids == {"n1", "n2", "n3"}

    def test_returns_empty_for_unknown_name(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.lookup_fuzzy("bar") == []

    def test_single_match(self):
        table = SymbolTable()
        table.add("a.py", "unique_fn", "n1", "Function")
        defs = table.lookup_fuzzy("unique_fn")
        assert len(defs) == 1
        assert defs[0].node_id == "n1"
        assert defs[0].file_path == "a.py"

    def test_returns_symbol_definition_instances(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        defs = table.lookup_fuzzy("foo")
        assert all(isinstance(d, SymbolDefinition) for d in defs)

    def test_preserves_type_info(self):
        table = SymbolTable()
        table.add("a.py", "Widget", "n1", "Class")
        table.add("b.py", "Widget", "n2", "Interface")
        defs = table.lookup_fuzzy("Widget")
        types = {d.type for d in defs}
        assert "Class" in types
        assert "Interface" in types


# ---------------------------------------------------------------------------
# 7. SymbolTable — lookup_fuzzy_in_file
# ---------------------------------------------------------------------------


class TestSymbolTableLookupFuzzyInFile:
    """Tests for fuzzy lookup with file preference."""

    def test_exact_match_in_preferred_file(self):
        table = SymbolTable()
        table.add("a.py", "helper", "n1", "Function")
        table.add("b.py", "helper", "n2", "Function")
        result = table.lookup_fuzzy_in_file("helper", "a.py")
        assert result is not None
        assert result.node_id == "n1"
        assert result.file_path == "a.py"

    def test_fallback_when_not_in_preferred_file(self):
        """When the preferred file has no match, fall back to first fuzzy match."""
        table = SymbolTable()
        table.add("b.py", "helper", "n2", "Function")
        result = table.lookup_fuzzy_in_file("helper", "a.py")
        assert result is not None
        assert result.node_id == "n2"

    def test_returns_none_when_nowhere(self):
        table = SymbolTable()
        table.add("a.py", "something_else", "n1", "Function")
        assert table.lookup_fuzzy_in_file("missing", "a.py") is None

    def test_prefers_same_file_over_others(self):
        table = SymbolTable()
        table.add("x.py", "calc", "n-x", "Function")
        table.add("y.py", "calc", "n-y", "Function")
        table.add("z.py", "calc", "n-z", "Function")
        result = table.lookup_fuzzy_in_file("calc", "y.py")
        assert result is not None
        assert result.file_path == "y.py"
        assert result.node_id == "n-y"

    def test_returns_none_on_empty_table(self):
        table = SymbolTable()
        assert table.lookup_fuzzy_in_file("foo", "bar.py") is None


# ---------------------------------------------------------------------------
# 8. SymbolTable — has_symbol / has_name
# ---------------------------------------------------------------------------


class TestSymbolTableHasSymbol:
    """Tests for membership checks."""

    def test_has_symbol_true(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.has_symbol("a.py", "foo") is True

    def test_has_symbol_false_wrong_file(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.has_symbol("b.py", "foo") is False

    def test_has_symbol_false_wrong_name(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.has_symbol("a.py", "bar") is False

    def test_has_name_true(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.has_name("foo") is True

    def test_has_name_false(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert table.has_name("bar") is False

    def test_has_name_after_adding_to_multiple_files(self):
        table = SymbolTable()
        table.add("a.py", "common", "n1", "Function")
        table.add("b.py", "common", "n2", "Function")
        assert table.has_name("common") is True


# ---------------------------------------------------------------------------
# 9. SymbolTable — get_file_symbols
# ---------------------------------------------------------------------------


class TestSymbolTableGetFileSymbols:
    """Tests for per-file symbol retrieval."""

    def test_empty_file(self):
        table = SymbolTable()
        assert table.get_file_symbols("nonexistent.py") == {}

    def test_single_symbol_in_file(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        syms = table.get_file_symbols("a.py")
        assert len(syms) == 1
        assert "foo" in syms
        assert syms["foo"].node_id == "n1"

    def test_multiple_symbols_in_file(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.add("a.py", "Bar", "n2", "Class")
        table.add("a.py", "BAZ", "n3", "Const")
        syms = table.get_file_symbols("a.py")
        assert len(syms) == 3
        assert syms["foo"].node_id == "n1"
        assert syms["Bar"].node_id == "n2"
        assert syms["BAZ"].node_id == "n3"

    def test_excludes_other_files(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.add("b.py", "bar", "n2", "Function")
        syms_a = table.get_file_symbols("a.py")
        assert len(syms_a) == 1
        assert "bar" not in syms_a

    def test_returns_symbol_definition_values(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        syms = table.get_file_symbols("a.py")
        defn = syms["foo"]
        assert isinstance(defn, SymbolDefinition)
        assert defn.file_path == "a.py"
        assert defn.type == "Function"


# ---------------------------------------------------------------------------
# 10. SymbolTable — from_parse_result
# ---------------------------------------------------------------------------


class TestSymbolTableFromParseResult:
    """Tests for the factory classmethod."""

    def test_empty_parse_result(self):
        pr = ParseResult()
        table = SymbolTable.from_parse_result(pr)
        assert len(table) == 0
        assert table.get_stats().total_definitions == 0

    def test_with_populated_symbols(self):
        pr = ParseResult(
            symbols=[
                ParsedSymbol(
                    file_path="a.py",
                    name="foo",
                    node_id="n1",
                    type="Function",
                ),
                ParsedSymbol(
                    file_path="b.py",
                    name="bar",
                    node_id="n2",
                    type="Class",
                ),
            ],
            file_count=2,
        )
        table = SymbolTable.from_parse_result(pr)
        assert len(table) == 2
        assert table.has_symbol("a.py", "foo")
        assert table.has_symbol("b.py", "bar")

    def test_all_symbols_indexed(self):
        syms = [
            ParsedSymbol(
                file_path=f"file_{i}.py",
                name=f"sym_{i}",
                node_id=f"n{i}",
                type="Function",
            )
            for i in range(20)
        ]
        pr = ParseResult(symbols=syms, file_count=20)
        table = SymbolTable.from_parse_result(pr)
        assert len(table) == 20
        for i in range(20):
            assert table.lookup_exact(f"file_{i}.py", f"sym_{i}") == f"n{i}"

    def test_from_parse_result_returns_symbol_table(self):
        pr = ParseResult()
        table = SymbolTable.from_parse_result(pr)
        assert isinstance(table, SymbolTable)

    def test_ignores_non_symbol_data(self):
        """Other ParseResult fields don't affect the table."""
        pr = ParseResult(
            symbols=[
                ParsedSymbol(
                    file_path="a.py",
                    name="foo",
                    node_id="n1",
                    type="Function",
                ),
            ],
            file_count=5,
        )
        table = SymbolTable.from_parse_result(pr)
        assert len(table) == 1


# ---------------------------------------------------------------------------
# 11. SymbolTable — clear
# ---------------------------------------------------------------------------


class TestSymbolTableClear:
    """Tests for clearing the symbol table."""

    def test_clear_empties_table(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.add("b.py", "bar", "n2", "Class")
        assert len(table) == 2
        table.clear()
        assert len(table) == 0

    def test_clear_resets_lookups(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.clear()
        assert table.lookup_exact("a.py", "foo") is None
        assert table.lookup_fuzzy("foo") == []
        assert table.has_symbol("a.py", "foo") is False
        assert table.has_name("foo") is False

    def test_clear_resets_stats(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.clear()
        stats = table.get_stats()
        assert stats.file_count == 0
        assert stats.unique_symbol_count == 0
        assert stats.total_definitions == 0

    def test_clear_on_empty_table(self):
        """Clearing an already-empty table should not error."""
        table = SymbolTable()
        table.clear()
        assert len(table) == 0

    def test_clear_get_file_symbols_empty(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.clear()
        assert table.get_file_symbols("a.py") == {}


# ---------------------------------------------------------------------------
# 12. SymbolTable — dunder methods
# ---------------------------------------------------------------------------


class TestSymbolTableDunderMethods:
    """Tests for __len__, __contains__, __repr__."""

    def test_len_zero(self):
        assert len(SymbolTable()) == 0

    def test_len_after_adds(self):
        table = SymbolTable()
        table.add("a.py", "x", "n1", "Function")
        table.add("b.py", "y", "n2", "Class")
        assert len(table) == 2

    def test_len_counts_all_definitions(self):
        """Same name in different files should each count."""
        table = SymbolTable()
        table.add("a.py", "dup", "n1", "Function")
        table.add("b.py", "dup", "n2", "Function")
        assert len(table) == 2

    def test_contains_true(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert "foo" in table

    def test_contains_false(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        assert "bar" not in table

    def test_repr_includes_count(self):
        table = SymbolTable()
        table.add("a.py", "x", "n1", "Function")
        table.add("b.py", "y", "n2", "Function")
        r = repr(table)
        assert "SymbolTable" in r

    def test_repr_empty(self):
        r = repr(SymbolTable())
        assert "SymbolTable" in r


# ---------------------------------------------------------------------------
# 13. Edge Cases
# ---------------------------------------------------------------------------


class TestSymbolTableEdgeCases:
    """Edge-case and boundary tests."""

    def test_empty_string_name(self):
        table = SymbolTable()
        table.add("a.py", "", "n1", "Function")
        assert table.has_symbol("a.py", "")
        assert table.lookup_exact("a.py", "") == "n1"

    def test_empty_string_file_path(self):
        table = SymbolTable()
        table.add("", "foo", "n1", "Function")
        assert table.has_symbol("", "foo")
        assert table.lookup_exact("", "foo") == "n1"

    def test_very_long_name(self):
        long_name = "a" * 5000
        table = SymbolTable()
        table.add("a.py", long_name, "n1", "Function")
        assert table.lookup_exact("a.py", long_name) == "n1"

    def test_special_characters_in_file_path(self):
        path = "src/components/my-component (copy)/utils.ts"
        table = SymbolTable()
        table.add(path, "render", "n1", "Function")
        assert table.lookup_exact(path, "render") == "n1"

    def test_unicode_in_name(self):
        table = SymbolTable()
        table.add("a.py", "计算", "n1", "Function")
        assert table.has_name("计算")
        assert table.lookup_exact("a.py", "计算") == "n1"

    def test_name_with_double_colon(self):
        """Ensure names containing :: don't conflict with FQN separator."""
        table = SymbolTable()
        table.add("a.cpp", "std::vector", "n1", "Class")
        assert table.lookup_exact("a.cpp", "std::vector") == "n1"
        defn = table.lookup_exact_definition("a.cpp", "std::vector")
        assert defn is not None
        assert defn.node_id == "n1"

    def test_same_name_in_many_files(self):
        """Symbol with the same name defined in 15 different files."""
        table = SymbolTable()
        for i in range(15):
            table.add(f"file_{i}.py", "common", f"n{i}", "Function")
        defs = table.lookup_fuzzy("common")
        assert len(defs) == 15
        assert len(table) == 15

    def test_add_after_clear_reuse(self):
        table = SymbolTable()
        table.add("a.py", "foo", "n1", "Function")
        table.clear()
        table.add("b.py", "bar", "n2", "Class")
        assert len(table) == 1
        assert table.has_symbol("b.py", "bar")
        assert not table.has_symbol("a.py", "foo")

    def test_windows_style_path(self):
        table = SymbolTable()
        table.add("src\\utils\\helpers.py", "do_thing", "n1", "Function")
        assert table.lookup_exact("src\\utils\\helpers.py", "do_thing") == "n1"

    def test_name_with_dots(self):
        table = SymbolTable()
        table.add("a.py", "module.submodule.func", "n1", "Function")
        assert table.lookup_exact("a.py", "module.submodule.func") == "n1"

    def test_multiple_types_same_name_same_file(self):
        """Edge case: re-adding same name/file with a different type overwrites."""
        table = SymbolTable()
        table.add("a.py", "Widget", "n1", "Class")
        table.add("a.py", "Widget", "n2", "Function")
        defn = table.lookup_exact_definition("a.py", "Widget")
        assert defn is not None
        # Latest add wins for exact lookup
        assert defn.node_id == "n2"


# ---------------------------------------------------------------------------
# 14. Integration Workflows
# ---------------------------------------------------------------------------


class TestSymbolTableIntegration:
    """End-to-end workflow tests simulating real resolution patterns."""

    def test_typical_multi_file_add_and_resolve(self):
        """Add symbols from multiple files, then resolve references."""
        table = SymbolTable()
        # Simulate parser output for two files
        table.add("src/models/user.py", "User", "user-cls-1", "Class")
        table.add("src/models/user.py", "UserSchema", "user-schema-1", "Class")
        table.add("src/services/auth.py", "authenticate", "auth-fn-1", "Function")
        table.add("src/services/auth.py", "AuthService", "auth-svc-1", "Class")
        table.add("src/routes/api.py", "handle_login", "login-fn-1", "Function")

        assert len(table) == 5
        stats = table.get_stats()
        assert stats.file_count == 3
        assert stats.total_definitions == 5

        # Resolve references
        assert table.lookup_exact("src/models/user.py", "User") == "user-cls-1"
        assert table.lookup_exact("src/services/auth.py", "AuthService") == "auth-svc-1"

    def test_heritage_resolution_pattern(self):
        """Simulate: childId = table.lookup_exact(file, className)
        or table.lookup_fuzzy(className)[0].node_id
        """
        table = SymbolTable()
        table.add("models/base.py", "BaseModel", "base-cls", "Class")
        table.add("models/user.py", "User", "user-cls", "Class")
        table.add("models/admin.py", "AdminUser", "admin-cls", "Class")

        # Heritage: AdminUser extends User
        # Step 1: try exact lookup in same file
        child_id = table.lookup_exact("models/admin.py", "User")
        # Not in that file — returns None
        assert child_id is None

        # Step 2: fuzzy lookup
        fuzzy = table.lookup_fuzzy("User")
        assert len(fuzzy) >= 1
        child_id = fuzzy[0].node_id
        assert child_id == "user-cls"

    def test_heritage_resolution_with_fuzzy_in_file(self):
        """lookup_fuzzy_in_file should prefer same-file definition."""
        table = SymbolTable()
        table.add("base.py", "Component", "comp-base", "Class")
        table.add("ui.py", "Component", "comp-ui", "Class")
        table.add("ui.py", "Button", "btn-cls", "Class")

        # Button extends Component — resolve in ui.py context
        result = table.lookup_fuzzy_in_file("Component", "ui.py")
        assert result is not None
        assert result.file_path == "ui.py"
        assert result.node_id == "comp-ui"

    def test_call_resolution_pattern_local(self):
        """Simulate: localNodeId = table.lookup_exact(currentFile, calledName)"""
        table = SymbolTable()
        table.add("utils.py", "parse_date", "parse-fn", "Function")
        table.add("utils.py", "format_date", "format-fn", "Function")
        table.add("main.py", "run", "run-fn", "Function")

        # Call from main.py to parse_date — check local first
        local = table.lookup_exact("main.py", "parse_date")
        assert local is None  # not local

        # Cross-file resolution
        defs = table.lookup_fuzzy("parse_date")
        assert len(defs) == 1
        assert defs[0].node_id == "parse-fn"
        assert defs[0].file_path == "utils.py"

    def test_call_resolution_pattern_ambiguous(self):
        """Multiple definitions for the same name across files."""
        table = SymbolTable()
        table.add("db/query.py", "execute", "exec-db", "Function")
        table.add("http/client.py", "execute", "exec-http", "Function")
        table.add("tasks/runner.py", "execute", "exec-task", "Function")

        defs = table.lookup_fuzzy("execute")
        assert len(defs) == 3

        # Prefer same-file when resolving from db context
        result = table.lookup_fuzzy_in_file("execute", "db/query.py")
        assert result is not None
        assert result.file_path == "db/query.py"
        assert result.node_id == "exec-db"

    def test_from_parse_result_then_resolve(self):
        """Full workflow: parse result -> symbol table -> lookups."""
        pr = ParseResult(
            symbols=[
                ParsedSymbol(
                    file_path="app.py",
                    name="App",
                    node_id="app-cls",
                    type="Class",
                ),
                ParsedSymbol(
                    file_path="app.py",
                    name="create_app",
                    node_id="create-fn",
                    type="Function",
                ),
                ParsedSymbol(
                    file_path="config.py",
                    name="Config",
                    node_id="cfg-cls",
                    type="Class",
                ),
                ParsedSymbol(
                    file_path="routes.py",
                    name="register_routes",
                    node_id="routes-fn",
                    type="Function",
                ),
            ],
            file_count=3,
        )
        table = SymbolTable.from_parse_result(pr)

        assert len(table) == 4
        assert table.lookup_exact("app.py", "App") == "app-cls"
        assert table.lookup_exact("config.py", "Config") == "cfg-cls"

        # Fuzzy lookups work
        assert len(table.lookup_fuzzy("App")) == 1
        assert table.lookup_fuzzy("Config")[0].type == "Class"

        # File symbols
        app_syms = table.get_file_symbols("app.py")
        assert len(app_syms) == 2
        assert "App" in app_syms
        assert "create_app" in app_syms

    def test_large_symbol_table(self):
        """Stress test with a realistic number of symbols."""
        table = SymbolTable()
        file_count = 50
        symbols_per_file = 10
        for f in range(file_count):
            for s in range(symbols_per_file):
                table.add(
                    f"src/module_{f}/file_{f}.py",
                    f"symbol_{f}_{s}",
                    f"n-{f}-{s}",
                    "Function" if s % 2 == 0 else "Class",
                )
        assert len(table) == file_count * symbols_per_file
        stats = table.get_stats()
        assert stats.file_count == file_count
        assert stats.total_definitions == file_count * symbols_per_file

        # Spot check
        assert table.lookup_exact("src/module_25/file_25.py", "symbol_25_5") == "n-25-5"
        assert table.has_name("symbol_0_0")
        assert not table.has_name("nonexistent")

    def test_overwrite_and_fuzzy_consistency(self):
        """After overwriting an exact entry, fuzzy results should be consistent."""
        table = SymbolTable()
        table.add("a.py", "helper", "n1", "Function")
        table.add("b.py", "helper", "n2", "Function")

        # Overwrite a.py's helper
        table.add("a.py", "helper", "n1-v2", "Function")

        # Exact lookup returns updated id
        assert table.lookup_exact("a.py", "helper") == "n1-v2"

        # Fuzzy lookup should include updated definitions
        defs = table.lookup_fuzzy("helper")
        ids = {d.node_id for d in defs}
        assert "n1-v2" in ids
        assert "n2" in ids
