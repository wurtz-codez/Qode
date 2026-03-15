"""Dual-index symbol lookup table (FQN + suffix).

Ported from GitNexus ``symbol-table.ts`` (~80 lines TypeScript → ~250 lines
Python), enhanced with Python best practices, thorough typing, docstrings,
and a dual-index design:

1. **FQN index** — ``{file_path}::{name}`` → :class:`SymbolDefinition`
   High-confidence exact lookup when both file path and symbol name are known.

2. **Suffix index** — ``{name}`` → ``list[SymbolDefinition]``
   Lower-confidence fuzzy lookup when only the symbol name is known.

The symbol table is populated during the parsing phase and consumed by
resolution processors (imports, calls, heritage) in subsequent phases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qode.data.schemas import ParsedSymbol, ParseResult

__all__ = [
    "SymbolDefinition",
    "SymbolStats",
    "SymbolTable",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolDefinition:
    """A single symbol definition with its location and type.

    Attributes:
        node_id: Deterministic node ID produced by the parser (e.g.
            ``Function::src/utils.py::helper::42``).
        file_path: Absolute or repo-relative path to the file that
            defines this symbol.
        type: Node label string that mirrors :data:`~qode.data.schemas.NodeLabel`
            (``'Function'``, ``'Class'``, ``'Method'``, etc.).
    """

    node_id: str
    file_path: str
    type: str  # mirrors NodeLabel: 'Function', 'Class', etc.


@dataclass
class SymbolStats:
    """Statistics about the symbol table contents.

    Attributes:
        file_count: Number of distinct files that contribute at least
            one symbol definition.
        unique_symbol_count: Number of unique symbol *names* in the
            suffix index (different files may define the same name).
        total_definitions: Total number of :class:`SymbolDefinition`
            entries across all names and files.
    """

    file_count: int
    unique_symbol_count: int  # unique names in suffix index
    total_definitions: int  # total entries (a name can have multiple defs)


# ---------------------------------------------------------------------------
# Symbol table
# ---------------------------------------------------------------------------


class SymbolTable:
    """Dual-index symbol lookup table.

    Maintains two complementary indexes:

    1. **FQN (fully-qualified name) index** — ``{file_path}::{name}`` →
       :class:`SymbolDefinition`.
       Used for high-confidence exact lookups when both file path and symbol
       name are known (e.g., resolving imports where the source file is
       known).

    2. **Suffix (name-only) index** — ``{name}`` →
       ``list[SymbolDefinition]``.
       Used for lower-confidence fuzzy lookups when only the symbol name is
       known (e.g., resolving call-sites where the defining file is unknown,
       or framework magic like dependency injection).

    The ``::`` separator used in FQN keys is intentional — file paths use
    ``/`` or ``\\``, so ``::`` is unambiguous.

    The symbol table is populated during parsing (Phase 3) and consumed by
    resolution processors (imports, calls, heritage) in Phase 4.

    Example::

        table = SymbolTable()
        table.add("src/utils.py", "helper", "Fn::utils.py::helper::42", "Function")

        # Exact lookup (high confidence)
        node_id = table.lookup_exact("src/utils.py", "helper")

        # Fuzzy lookup (lower confidence)
        defs = table.lookup_fuzzy("helper")
    """

    __slots__ = ("_fqn_index", "_suffix_index")

    def __init__(self) -> None:
        # FQN index: "filepath::name" -> SymbolDefinition
        self._fqn_index: dict[str, SymbolDefinition] = {}
        # Suffix index: "name" -> [SymbolDefinition, ...]
        self._suffix_index: dict[str, list[SymbolDefinition]] = {}

    # -- Internal helpers -----------------------------------------------------

    @staticmethod
    def _make_fqn(file_path: str, name: str) -> str:
        """Build a fully-qualified name key.

        The key format is ``{file_path}::{name}``.  The ``::`` separator
        is chosen because file paths only contain ``/`` or ``\\``, making
        the key unambiguous and trivially splittable.
        """
        return f"{file_path}::{name}"

    # -- Registration methods -------------------------------------------------

    def add(
        self,
        file_path: str,
        name: str,
        node_id: str,
        symbol_type: str,
    ) -> None:
        """Register a symbol definition in both indexes.

        If a symbol with the same *file_path* and *name* already exists in
        the FQN index, the new definition silently overwrites it
        (last-write-wins semantics — mirrors the TypeScript original).  In
        the suffix index the definition is always appended, so multiple
        files defining the same name are all retained.

        Args:
            file_path: Absolute or repo-relative path to the defining file.
            name: Symbol name (function, class, method, etc.).
            node_id: Deterministic node ID from the parser.
            symbol_type: Node label string (``'Function'``, ``'Class'``,
                etc.) — mirrors :data:`~qode.data.schemas.NodeLabel`.
        """
        defn = SymbolDefinition(
            node_id=node_id,
            file_path=file_path,
            type=symbol_type,
        )

        # FQN index — last-write-wins for duplicate names in same file
        fqn_key = self._make_fqn(file_path, name)
        self._fqn_index[fqn_key] = defn

        # Suffix index — append (a name can exist in multiple files)
        self._suffix_index.setdefault(name, []).append(defn)

    def add_symbol(self, symbol: ParsedSymbol) -> None:
        """Register a :class:`~qode.data.schemas.ParsedSymbol` from parser output.

        Convenience method that unpacks a ``ParsedSymbol`` into the
        :meth:`add` call.
        """
        self.add(symbol.file_path, symbol.name, symbol.node_id, symbol.type)

    def add_all(self, symbols: Sequence[ParsedSymbol]) -> None:
        """Bulk-register all symbols from a parser output.

        Typically called after each chunk's ``parse_batch()`` result is
        merged into the aggregate :class:`~qode.data.schemas.ParseResult`.
        """
        for sym in symbols:
            self.add_symbol(sym)

    @classmethod
    def from_parse_result(cls, parse_result: ParseResult) -> SymbolTable:
        """Factory: build a symbol table from a :class:`~qode.data.schemas.ParseResult`.

        Convenience constructor for building a fully-populated table
        from the aggregate result of the parsing phase.

        Args:
            parse_result: The aggregate output of the parsing engine
                containing all discovered symbols.

        Returns:
            A new :class:`SymbolTable` populated with every symbol from
            *parse_result*.
        """
        table = cls()
        if parse_result.symbols:
            table.add_all(parse_result.symbols)
            return table

        for node in parse_result.nodes:
            table.add(
                node.properties.file_path,
                node.properties.name,
                node.id,
                node.label,
            )
        return table

    # -- Lookup methods -------------------------------------------------------

    def lookup_exact(self, file_path: str, name: str) -> str | None:
        """High-confidence lookup: find a symbol by file path AND name.

        Returns the ``node_id`` if the symbol exists in the specified file,
        or ``None`` if not found.  This is the preferred lookup method when
        the defining file is known (e.g., resolved import).

        Args:
            file_path: Path of the file that is expected to define the symbol.
            name: Symbol name to look up.

        Returns:
            The deterministic node ID, or ``None`` if the symbol is not
            registered under the given file path.
        """
        fqn_key = self._make_fqn(file_path, name)
        defn = self._fqn_index.get(fqn_key)
        return defn.node_id if defn is not None else None

    def lookup_exact_definition(
        self,
        file_path: str,
        name: str,
    ) -> SymbolDefinition | None:
        """High-confidence lookup returning the full :class:`SymbolDefinition`.

        Identical to :meth:`lookup_exact` but returns the entire definition
        object instead of just the ``node_id``.

        Args:
            file_path: Path of the file that is expected to define the symbol.
            name: Symbol name to look up.

        Returns:
            The :class:`SymbolDefinition`, or ``None`` if not found.
        """
        fqn_key = self._make_fqn(file_path, name)
        return self._fqn_index.get(fqn_key)

    def lookup_fuzzy(self, name: str) -> list[SymbolDefinition]:
        """Low-confidence lookup: find all definitions of a symbol name.

        Returns all :class:`SymbolDefinition` objects across all files that
        define a symbol with the given *name*.  Used when only the name is
        known (e.g., call-sites, framework magic, heritage resolution).

        Args:
            name: Symbol name to search for across all files.

        Returns:
            A (possibly empty) list of :class:`SymbolDefinition` objects.
        """
        return self._suffix_index.get(name, [])

    def lookup_fuzzy_in_file(
        self,
        name: str,
        preferred_file: str,
    ) -> SymbolDefinition | None:
        """Fuzzy lookup with file preference.

        First tries an exact lookup in *preferred_file*.  If not found,
        falls back to fuzzy lookup and returns the first match (if any).
        This mirrors the pattern used extensively in call/heritage
        resolution in the TypeScript original::

            symbolTable.lookupExact(file, name) ||
            symbolTable.lookupFuzzy(name)[0]?.nodeId

        Args:
            name: Symbol name to resolve.
            preferred_file: File path to try first (exact lookup).

        Returns:
            The best-matching :class:`SymbolDefinition`, or ``None`` if
            the symbol cannot be found anywhere.
        """
        # Try exact first
        exact = self.lookup_exact_definition(preferred_file, name)
        if exact is not None:
            return exact
        # Fall back to fuzzy
        defs = self.lookup_fuzzy(name)
        return defs[0] if defs else None

    # -- Membership queries ---------------------------------------------------

    def has_symbol(self, file_path: str, name: str) -> bool:
        """Check if a specific symbol exists in a specific file.

        Args:
            file_path: File path to check.
            name: Symbol name to check.

        Returns:
            ``True`` if the FQN index contains an entry for
            ``{file_path}::{name}``.
        """
        return self._make_fqn(file_path, name) in self._fqn_index

    def has_name(self, name: str) -> bool:
        """Check if any definition exists for a symbol name.

        Args:
            name: Symbol name to check.

        Returns:
            ``True`` if the suffix index contains at least one definition
            for *name*.
        """
        return name in self._suffix_index

    def get_file_symbols(self, file_path: str) -> dict[str, SymbolDefinition]:
        """Get all symbols defined in a specific file.

        Returns a dict mapping ``symbol_name`` → :class:`SymbolDefinition`
        for every symbol whose FQN key starts with *file_path*.

        Note:
            This is *O(n)* over the FQN index.  For frequent per-file
            queries consider caching the result externally.

        Args:
            file_path: The file whose symbols should be retrieved.

        Returns:
            A dict of symbol name → definition for all symbols in the file.
        """
        prefix = file_path + "::"
        prefix_len = len(prefix)
        result: dict[str, SymbolDefinition] = {}
        for fqn_key, defn in self._fqn_index.items():
            if fqn_key.startswith(prefix):
                name = fqn_key[prefix_len:]
                result[name] = defn
        return result

    # -- Stats & lifecycle ----------------------------------------------------

    def get_stats(self) -> SymbolStats:
        """Compute statistics about the current symbol table contents.

        Returns:
            A :class:`SymbolStats` instance with file count, unique symbol
            count, and total definition count.
        """
        file_paths: set[str] = set()
        total_defs = 0
        for defs in self._suffix_index.values():
            total_defs += len(defs)
            for d in defs:
                file_paths.add(d.file_path)
        return SymbolStats(
            file_count=len(file_paths),
            unique_symbol_count=len(self._suffix_index),
            total_definitions=total_defs,
        )

    def clear(self) -> None:
        """Remove all entries from both indexes."""
        self._fqn_index.clear()
        self._suffix_index.clear()

    # -- Dunder methods -------------------------------------------------------

    def __len__(self) -> int:
        """Return the total number of definitions across all symbols.

        This is the sum of all suffix index entry lengths, which equals
        the total number of :meth:`add` calls (minus overwrites in the
        FQN index, which do not affect the suffix index).
        """
        return sum(len(defs) for defs in self._suffix_index.values())

    def __contains__(self, name: object) -> bool:
        """Check if a symbol name exists in the suffix index.

        Supports the ``name in table`` idiom.
        """
        return name in self._suffix_index

    def __repr__(self) -> str:
        """Return a concise summary representation of the symbol table."""
        stats = self.get_stats()
        return (
            f"SymbolTable(files={stats.file_count}, "
            f"symbols={stats.unique_symbol_count}, "
            f"definitions={stats.total_definitions})"
        )
