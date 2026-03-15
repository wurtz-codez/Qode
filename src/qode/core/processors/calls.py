"""3-tier call resolution processor with confidence scoring.

Resolves pre-extracted ``ExtractedCall`` objects to ``CALLS`` relationship
edges using a three-tier strategy against the symbol table:

1. **Tier 1 -- Same-file** (confidence 0.85): The called name is defined in
   the same file as the call site.  Uses ``SymbolTable.lookup_exact`` for a
   single O(1) dict lookup.

2. **Tier 2 -- Import-resolved** (confidence 0.9): The called name has at
   least one definition whose file path appears in the import map for the
   calling file.  Uses ``SymbolTable.lookup_fuzzy`` + import-map membership
   check.

3. **Tier 3 -- Fuzzy global** (confidence 0.5 unique / 0.3 ambiguous):
   Falls back to the first global definition found by
   ``SymbolTable.lookup_fuzzy``.  When only one definition exists the
   confidence is higher (0.5) than when multiple candidates are present
   (0.3).

Built-in and noise names (standard library functions, common methods, etc.)
are filtered before resolution to avoid polluting the call graph.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from qode.core.parsers.parser import generate_id
from qode.core.symbol_table import SymbolTable
from qode.data.schemas import ExtractedCall, ParsedRelationship, ParseResult

__all__ = ["process_calls"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in / noise filter
# ---------------------------------------------------------------------------

BUILT_IN_NAMES: frozenset[str] = frozenset(
    [
        # JavaScript/TypeScript built-ins
        "console",
        "log",
        "warn",
        "error",
        "info",
        "debug",
        "setTimeout",
        "setInterval",
        "clearTimeout",
        "clearInterval",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "encodeURI",
        "decodeURI",
        "encodeURIComponent",
        "decodeURIComponent",
        "JSON",
        "parse",
        "stringify",
        "Object",
        "Array",
        "String",
        "Number",
        "Boolean",
        "Symbol",
        "BigInt",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "Promise",
        "resolve",
        "reject",
        "then",
        "catch",
        "finally",
        "Math",
        "Date",
        "RegExp",
        "Error",
        "require",
        "import",
        "export",
        "fetch",
        "Response",
        "Request",
        # React hooks and common functions
        "useState",
        "useEffect",
        "useCallback",
        "useMemo",
        "useRef",
        "useContext",
        "useReducer",
        "useLayoutEffect",
        "useImperativeHandle",
        "useDebugValue",
        "createElement",
        "createContext",
        "createRef",
        "forwardRef",
        "memo",
        "lazy",
        # Common array/object methods
        "map",
        "filter",
        "reduce",
        "forEach",
        "find",
        "findIndex",
        "some",
        "every",
        "includes",
        "indexOf",
        "slice",
        "splice",
        "concat",
        "join",
        "split",
        "push",
        "pop",
        "shift",
        "unshift",
        "sort",
        "reverse",
        "keys",
        "values",
        "entries",
        "assign",
        "freeze",
        "seal",
        "hasOwnProperty",
        "toString",
        "valueOf",
        # Python built-ins
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "open",
        "read",
        "write",
        "close",
        "append",
        "extend",
        "update",
        "super",
        "type",
        "isinstance",
        "issubclass",
        "getattr",
        "setattr",
        "hasattr",
        "enumerate",
        "zip",
        "sorted",
        "reversed",
        "min",
        "max",
        "sum",
        "abs",
        # Kotlin stdlib
        "println",
        "print",
        "readLine",
        "require",
        "requireNotNull",
        "check",
        "assert",
        "lazy",
        "error",
        "listOf",
        "mapOf",
        "setOf",
        "mutableListOf",
        "mutableMapOf",
        "mutableSetOf",
        "arrayOf",
        "sequenceOf",
        "also",
        "apply",
        "run",
        "with",
        "takeIf",
        "takeUnless",
        "TODO",
        "buildString",
        "buildList",
        "buildMap",
        "buildSet",
        "repeat",
        "synchronized",
        # Kotlin coroutine builders & scope functions
        "launch",
        "async",
        "runBlocking",
        "withContext",
        "coroutineScope",
        "supervisorScope",
        "delay",
        # Kotlin Flow operators
        "flow",
        "flowOf",
        "collect",
        "emit",
        "onEach",
        "catch",
        "buffer",
        "conflate",
        "distinctUntilChanged",
        "flatMapLatest",
        "flatMapMerge",
        "combine",
        "stateIn",
        "shareIn",
        "launchIn",
        # Kotlin infix stdlib functions
        "to",
        "until",
        "downTo",
        "step",
        # C/C++ standard library and common kernel helpers
        "printf",
        "fprintf",
        "sprintf",
        "snprintf",
        "vprintf",
        "vfprintf",
        "vsprintf",
        "vsnprintf",
        "scanf",
        "fscanf",
        "sscanf",
        "malloc",
        "calloc",
        "realloc",
        "free",
        "memcpy",
        "memmove",
        "memset",
        "memcmp",
        "strlen",
        "strcpy",
        "strncpy",
        "strcat",
        "strncat",
        "strcmp",
        "strncmp",
        "strstr",
        "strchr",
        "strrchr",
        "atoi",
        "atol",
        "atof",
        "strtol",
        "strtoul",
        "strtoll",
        "strtoull",
        "strtod",
        "sizeof",
        "offsetof",
        "typeof",
        "assert",
        "abort",
        "exit",
        "_exit",
        "fopen",
        "fclose",
        "fread",
        "fwrite",
        "fseek",
        "ftell",
        "rewind",
        "fflush",
        "fgets",
        "fputs",
        # Linux kernel common macros/helpers (not real call targets)
        "likely",
        "unlikely",
        "BUG",
        "BUG_ON",
        "WARN",
        "WARN_ON",
        "WARN_ONCE",
        "IS_ERR",
        "PTR_ERR",
        "ERR_PTR",
        "IS_ERR_OR_NULL",
        "ARRAY_SIZE",
        "container_of",
        "list_for_each_entry",
        "list_for_each_entry_safe",
        "min",
        "max",
        "clamp",
        "abs",
        "swap",
        "pr_info",
        "pr_warn",
        "pr_err",
        "pr_debug",
        "pr_notice",
        "pr_crit",
        "pr_emerg",
        "printk",
        "dev_info",
        "dev_warn",
        "dev_err",
        "dev_dbg",
        "GFP_KERNEL",
        "GFP_ATOMIC",
        "spin_lock",
        "spin_unlock",
        "spin_lock_irqsave",
        "spin_unlock_irqrestore",
        "mutex_lock",
        "mutex_unlock",
        "mutex_init",
        "kfree",
        "kmalloc",
        "kzalloc",
        "kcalloc",
        "krealloc",
        "kvmalloc",
        "kvfree",
        "get",
        "put",
        # Swift/iOS built-ins and standard library
        "print",
        "debugPrint",
        "dump",
        "fatalError",
        "precondition",
        "preconditionFailure",
        "assert",
        "assertionFailure",
        "NSLog",
        "abs",
        "min",
        "max",
        "zip",
        "stride",
        "sequence",
        "repeatElement",
        "swap",
        "withUnsafePointer",
        "withUnsafeMutablePointer",
        "withUnsafeBytes",
        "autoreleasepool",
        "unsafeBitCast",
        "unsafeDowncast",
        "numericCast",
        "type",
        "MemoryLayout",
        # Swift collection/string methods (common noise)
        "map",
        "flatMap",
        "compactMap",
        "filter",
        "reduce",
        "forEach",
        "contains",
        "first",
        "last",
        "prefix",
        "suffix",
        "dropFirst",
        "dropLast",
        "sorted",
        "reversed",
        "enumerated",
        "joined",
        "split",
        "append",
        "insert",
        "remove",
        "removeAll",
        "removeFirst",
        "removeLast",
        "isEmpty",
        "count",
        "index",
        "startIndex",
        "endIndex",
        # UIKit/Foundation common methods (noise in call graph)
        "addSubview",
        "removeFromSuperview",
        "layoutSubviews",
        "setNeedsLayout",
        "layoutIfNeeded",
        "setNeedsDisplay",
        "invalidateIntrinsicContentSize",
        "addTarget",
        "removeTarget",
        "addGestureRecognizer",
        "addConstraint",
        "addConstraints",
        "removeConstraint",
        "removeConstraints",
        "NSLocalizedString",
        "Bundle",
        "reloadData",
        "reloadSections",
        "reloadRows",
        "performBatchUpdates",
        "register",
        "dequeueReusableCell",
        "dequeueReusableSupplementaryView",
        "beginUpdates",
        "endUpdates",
        "insertRows",
        "deleteRows",
        "insertSections",
        "deleteSections",
        "present",
        "dismiss",
        "pushViewController",
        "popViewController",
        "popToRootViewController",
        "performSegue",
        "prepare",
        # GCD / async
        "DispatchQueue",
        "async",
        "sync",
        "asyncAfter",
        "Task",
        "withCheckedContinuation",
        "withCheckedThrowingContinuation",
        # Combine
        "sink",
        "store",
        "assign",
        "receive",
        "subscribe",
        # Notification / KVO
        "addObserver",
        "removeObserver",
        "post",
        "NotificationCenter",
    ]
)


def _is_built_in_or_noise(name: str) -> bool:
    """Return ``True`` if *name* is a known built-in or noise symbol."""
    return name in BUILT_IN_NAMES


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ResolveResult:
    """Internal value object for a successful call-target resolution.

    Attributes:
        node_id: The deterministic node ID of the resolved target.
        confidence: Confidence score in the range ``[0, 1]``.
        reason: Human-readable label for the resolution tier
            (``'same-file'``, ``'import-resolved'``, or ``'fuzzy-global'``).
    """

    node_id: str
    confidence: float
    reason: str


def _resolve_call_target(
    called_name: str,
    current_file: str,
    symbol_table: SymbolTable,
    import_map: dict[str, set[str]],
) -> _ResolveResult | None:
    """Resolve a call to its target definition using a 3-tier strategy.

    The tiers are tried in order of cost (cheapest first), not in order
    of confidence:

    * **Tier 1 -- Same-file** (confidence 0.85): single dict lookup via
      ``symbol_table.lookup_exact``.
    * **Tier 2 -- Import-resolved** (confidence 0.9): fuzzy lookup +
      import-map membership check.
    * **Tier 3 -- Fuzzy-global** (confidence 0.5 unique / 0.3 ambiguous):
      first result from ``symbol_table.lookup_fuzzy``.

    Args:
        called_name: The unqualified name of the called function/method.
        current_file: File path where the call site occurs.
        symbol_table: Populated symbol table for the repository.
        import_map: Mapping of ``file_path`` -> set of file paths that it
            imports (resolved to absolute/repo-relative paths).

    Returns:
        A :class:`_ResolveResult` if the call can be resolved, or ``None``
        if no matching definition is found in the symbol table.
    """
    # Tier 1: Same-file (cheapest -- single map lookup)
    local_node_id = symbol_table.lookup_exact(current_file, called_name)
    if local_node_id is not None:
        return _ResolveResult(
            node_id=local_node_id,
            confidence=0.85,
            reason="same-file",
        )

    # Tier 2 & 3 both need the fuzzy results
    all_defs = symbol_table.lookup_fuzzy(called_name)
    if not all_defs:
        return None

    # Tier 2: Import-resolved (check if any definition is in an imported file)
    imported_files = import_map.get(current_file)
    if imported_files is not None:
        for defn in all_defs:
            if defn.file_path in imported_files:
                return _ResolveResult(
                    node_id=defn.node_id,
                    confidence=0.9,
                    reason="import-resolved",
                )

    # Tier 3: Fuzzy global (no import match found)
    confidence = 0.5 if len(all_defs) == 1 else 0.3
    return _ResolveResult(
        node_id=all_defs[0].node_id,
        confidence=confidence,
        reason="fuzzy-global",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_calls(
    parse_result: ParseResult,
    *,
    symbol_table: SymbolTable,
    import_map: dict[str, set[str]],
) -> None:
    """Resolve extracted call-sites and append ``CALLS`` edges to *parse_result*.

    Iterates over ``parse_result.calls``, skips built-in / noise names,
    resolves each remaining call via the 3-tier strategy, and appends the
    resulting :class:`~qode.data.schemas.ParsedRelationship` edges (type
    ``"CALLS"``) to ``parse_result.relationships``.

    Args:
        parse_result: The mutable aggregate parse result.  ``calls`` is
            read; ``relationships`` is appended to.
        symbol_table: Populated symbol table for the repository.
        import_map: Mapping of ``file_path`` -> set of imported file paths.
    """
    calls: list[ExtractedCall] = parse_result.calls

    resolved_count = 0
    skipped_builtin = 0
    unresolved_count = 0

    for call in calls:
        # Filter built-in / noise names
        if _is_built_in_or_noise(call.called_name):
            skipped_builtin += 1
            continue

        # Resolve the call target
        resolved = _resolve_call_target(
            call.called_name,
            call.file_path,
            symbol_table,
            import_map,
        )

        if resolved is None:
            unresolved_count += 1
            continue

        # Build the CALLS relationship edge
        rel_id = generate_id(
            "CALLS",
            f"{call.source_id}:{call.called_name}->{resolved.node_id}",
        )

        parse_result.relationships.append(
            ParsedRelationship(
                id=rel_id,
                source_id=call.source_id,
                target_id=resolved.node_id,
                type="CALLS",
                confidence=resolved.confidence,
                reason=resolved.reason,
            )
        )
        resolved_count += 1

    logger.info(
        "Call resolution complete: %d resolved, %d skipped (built-in), "
        "%d unresolved out of %d total calls",
        resolved_count,
        skipped_builtin,
        unresolved_count,
        len(calls),
    )
