"""py-tree-sitter parsing engine.

Ported from GitNexus ``workers/parse-worker.ts`` (~1316 lines → Python).
Parses source files into CSTs and extracts all entities using S-expression
queries.  Runs in parallel via ``multiprocessing.Pool``.

The public surface consists of:

* ``parse_file``  - parse a single file and return a ``ParseResult``
* ``parse_batch`` - parse many files, grouping by language for efficiency
* ``generate_id`` - deterministic SHA-256 ID generator

Internal helpers are prefixed with ``_``.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

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

if TYPE_CHECKING:
    from tree_sitter import Language, Node


class QueryProtocol(Protocol):
    def matches(self, node: Node) -> list[tuple[int, dict[str, list[Any]]]]: ...


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES = 512 * 1024  # 512 KB — skip files larger than this

# ---------------------------------------------------------------------------
# Language registry  (GitNexus parse-worker.ts lines ~90-143)
# ---------------------------------------------------------------------------


def _load(module_name: str, func_name: str) -> Language:
    """Dynamically import a tree-sitter language package.

    Args:
        module_name: Python module name (e.g. ``tree_sitter_python``).
        func_name: Attribute on the module that returns the raw
            language pointer (e.g. ``language``, ``language_typescript``).

    Returns:
        A ``tree_sitter.Language`` instance.

    Raises:
        ImportError: If the language package is not installed.
    """
    import importlib

    from tree_sitter import Language

    mod = importlib.import_module(module_name)
    factory = getattr(mod, func_name)
    return Language(factory())


_LANGUAGE_LOADERS: dict[str, Callable[[], Language]] = {
    "python": lambda: _load("tree_sitter_python", "language"),
    "javascript": lambda: _load("tree_sitter_javascript", "language"),
    "typescript": lambda: _load("tree_sitter_typescript", "language_typescript"),
    "tsx": lambda: _load("tree_sitter_typescript", "language_tsx"),
    "java": lambda: _load("tree_sitter_java", "language"),
    "go": lambda: _load("tree_sitter_go", "language"),
    "rust": lambda: _load("tree_sitter_rust", "language"),
    "c": lambda: _load("tree_sitter_c", "language"),
    "cpp": lambda: _load("tree_sitter_cpp", "language"),
    "csharp": lambda: _load("tree_sitter_c_sharp", "language"),
    "php": lambda: _load("tree_sitter_php", "language"),
    "kotlin": lambda: _load("tree_sitter_kotlin", "language"),
    "swift": lambda: _load("tree_sitter_swift", "language"),
}

# Cache of already-loaded Language objects.
_language_cache: dict[str, Language] = {}


def _get_language(name: str) -> Language | None:
    """Return a cached ``Language`` object, or load and cache it.

    Args:
        name: Language key (e.g. ``"python"``, ``"tsx"``).

    Returns:
        The ``Language`` instance, or ``None`` if the package is missing.
    """
    if name in _language_cache:
        return _language_cache[name]

    loader = _LANGUAGE_LOADERS.get(name)
    if loader is None:
        return None

    try:
        lang = loader()
    except (ImportError, AttributeError, OSError) as exc:
        logger.debug("Language %r unavailable: %s", name, exc)
        return None

    _language_cache[name] = lang
    return lang


# ---------------------------------------------------------------------------
# ID generation  (GitNexus parse-worker.ts ``generateId``)
# ---------------------------------------------------------------------------


def generate_id(label: str, key: str) -> str:
    """Generate a deterministic unique ID from *label* and *key*.

    Uses SHA-256, truncated to the first 16 hex characters, and prefixed
    with the lowered *label*.

    Args:
        label: Entity label (e.g. ``"Function"``).
        key: Distinguishing key (e.g. ``"src/main.py:my_func:10"``).

    Returns:
        A string like ``function_a1b2c3d4e5f67890``.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"{label.lower()}_{digest}"


# ---------------------------------------------------------------------------
# Built-in names to exclude from call graphs
# (GitNexus parse-worker.ts lines 338-448)
# ---------------------------------------------------------------------------

BUILT_INS: frozenset[str] = frozenset(
    # -- JavaScript / TypeScript ------------------------------------------
    {
        "console",
        "log",
        "warn",
        "error",
        "info",
        "debug",
        "trace",
        "dir",
        "table",
        "assert",
        "count",
        "group",
        "groupEnd",
        "time",
        "timeEnd",
        "require",
        "import",
        "export",
        "module",
        "exports",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "encodeURI",
        "decodeURI",
        "encodeURIComponent",
        "decodeURIComponent",
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "setImmediate",
        "clearImmediate",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "fetch",
        "then",
        "catch",
        "finally",
        "resolve",
        "reject",
        "all",
        "allSettled",
        "race",
        "any",
        "keys",
        "values",
        "entries",
        "assign",
        "freeze",
        "seal",
        "create",
        "defineProperty",
        "getOwnPropertyDescriptor",
        "getPrototypeOf",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "toString",
        "valueOf",
        "toLocaleString",
        "constructor",
        "push",
        "pop",
        "shift",
        "unshift",
        "splice",
        "slice",
        "concat",
        "join",
        "reverse",
        "sort",
        "filter",
        "map",
        "reduce",
        "reduceRight",
        "forEach",
        "some",
        "every",
        "find",
        "findIndex",
        "includes",
        "indexOf",
        "lastIndexOf",
        "flat",
        "flatMap",
        "fill",
        "copyWithin",
        "from",
        "of",
        "isArray",
        "charAt",
        "charCodeAt",
        "codePointAt",
        "startsWith",
        "endsWith",
        "repeat",
        "padStart",
        "padEnd",
        "trim",
        "trimStart",
        "trimEnd",
        "toLowerCase",
        "toUpperCase",
        "split",
        "replace",
        "replaceAll",
        "match",
        "matchAll",
        "search",
        "substring",
        "normalize",
        "localeCompare",
        "test",
        "exec",
        "stringify",
        "parse",
        "now",
        "getTime",
        "toISOString",
        "toJSON",
        "getFullYear",
        "getMonth",
        "getDate",
        "getDay",
        "getHours",
        "getMinutes",
        "getSeconds",
        "abs",
        "ceil",
        "floor",
        "round",
        "max",
        "min",
        "pow",
        "sqrt",
        "random",
        "trunc",
        "sign",
        "log2",
        "log10",
        "clz32",
        "imul",
        "fround",
        "cbrt",
        "hypot",
        "set",
        "get",
        "has",
        "delete",
        "clear",
        "add",
        "next",
        "done",
        "return",
        "throw",
        "Symbol",
        "iterator",
        "asyncIterator",
        "hasInstance",
        "toPrimitive",
        "toStringTag",
        "species",
        "typeof",
        "instanceof",
        "void",
        "apply",
        "call",
        "bind",
        "proxy",
        "Proxy",
        "Reflect",
        "construct",
        "ownKeys",
        "emit",
        "on",
        "once",
        "removeListener",
        "addEventListener",
        "removeEventListener",
        "dispatchEvent",
        "preventDefault",
        "stopPropagation",
        "querySelector",
        "querySelectorAll",
        "getElementById",
        "createElement",
        "getAttribute",
        "setAttribute",
        "removeAttribute",
        "classList",
        "appendChild",
        "removeChild",
        "insertBefore",
        "replaceChild",
    }
    # -- Python -----------------------------------------------------------
    | {
        "print",
        "len",
        "range",
        "enumerate",
        "zip",
        "type",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "bin",
        "bool",
        "bytes",
        "callable",
        "chr",
        "complex",
        "dict",
        "divmod",
        "float",
        "format",
        "frozenset",
        "globals",
        "hash",
        "hex",
        "id",
        "input",
        "int",
        "iter",
        "list",
        "locals",
        "memoryview",
        "object",
        "oct",
        "open",
        "ord",
        "repr",
        "reversed",
        "sorted",
        "str",
        "sum",
        "tuple",
        "vars",
        "append",
        "extend",
        "insert",
        "remove",
        "copy",
        "update",
        "items",
        "strip",
        "lstrip",
        "rstrip",
        "upper",
        "lower",
        "title",
        "capitalize",
        "swapcase",
        "center",
        "ljust",
        "rjust",
        "zfill",
        "encode",
        "decode",
        "rsplit",
        "splitlines",
        "startswith",
        "endswith",
        "rfind",
        "index",
        "rindex",
        "isalpha",
        "isdigit",
        "isalnum",
        "isspace",
        "isupper",
        "islower",
        "expandtabs",
        "maketrans",
        "translate",
    }
    # -- Kotlin -----------------------------------------------------------
    | {
        "println",
        "readLine",
        "readln",
        "arrayOf",
        "listOf",
        "mutableListOf",
        "setOf",
        "mutableSetOf",
        "mapOf",
        "mutableMapOf",
        "hashMapOf",
        "hashSetOf",
        "linkedMapOf",
        "linkedSetOf",
        "sortedMapOf",
        "sortedSetOf",
        "emptyList",
        "emptySet",
        "emptyMap",
        "emptyArray",
        "arrayOfNulls",
        "intArrayOf",
        "doubleArrayOf",
        "floatArrayOf",
        "longArrayOf",
        "shortArrayOf",
        "byteArrayOf",
        "charArrayOf",
        "booleanArrayOf",
        "sequenceOf",
        "generateSequence",
        "buildList",
        "buildSet",
        "buildMap",
        "buildString",
        "requireNotNull",
        "check",
        "checkNotNull",
        "TODO",
        "run",
        "with",
        "let",
        "also",
        "takeIf",
        "takeUnless",
        "lazy",
        "to",
        "compareTo",
        "equals",
        "hashCode",
        "toInt",
        "toLong",
        "toFloat",
        "toDouble",
        "toShort",
        "toByte",
        "toChar",
        "toBoolean",
        "toList",
        "toMutableList",
        "toSet",
        "toMutableSet",
        "toMap",
        "toMutableMap",
        "toSortedSet",
        "toSortedMap",
        "toTypedArray",
        "toIntArray",
        "toLongArray",
        "toFloatArray",
        "toDoubleArray",
        "toByteArray",
        "toCharArray",
        "toShortArray",
        "toBooleanArray",
        "forEachIndexed",
        "mapIndexed",
        "mapNotNull",
        "filterNot",
        "filterNotNull",
        "filterIsInstance",
        "first",
        "firstOrNull",
        "last",
        "lastOrNull",
        "single",
        "singleOrNull",
        "none",
        "sumOf",
        "maxOf",
        "minOf",
        "maxByOrNull",
        "minByOrNull",
        "sortedBy",
        "sortedByDescending",
        "groupBy",
        "associate",
        "associateBy",
        "associateWith",
        "partition",
        "unzip",
        "chunked",
        "windowed",
        "distinct",
        "distinctBy",
        "drop",
        "dropLast",
        "take",
        "takeLast",
        "asReversed",
        "shuffled",
        "contains",
        "containsAll",
        "indexOfFirst",
        "indexOfLast",
        "elementAt",
        "elementAtOrNull",
        "getOrElse",
        "getOrDefault",
        "getOrPut",
        "getValue",
        "orEmpty",
        "ifEmpty",
        "isNullOrEmpty",
        "isNullOrBlank",
        "isNotEmpty",
        "isNotBlank",
        "isEmpty",
        "isBlank",
        "trimIndent",
        "trimMargin",
        "removeSuffix",
        "removePrefix",
        "removeSurrounding",
        "substringBefore",
        "substringAfter",
        "substringBeforeLast",
        "substringAfterLast",
        "toRegex",
        "matches",
    }
    # -- C / C++ ----------------------------------------------------------
    | {
        "printf",
        "fprintf",
        "sprintf",
        "snprintf",
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
        "strtok",
        "strtol",
        "strtod",
        "atoi",
        "atof",
        "atol",
        "fopen",
        "fclose",
        "fread",
        "fwrite",
        "fgets",
        "fputs",
        "fseek",
        "ftell",
        "rewind",
        "fflush",
        "perror",
        "exit",
        "abort",
        "atexit",
        "system",
        "getenv",
        "qsort",
        "bsearch",
        "labs",
        "div",
        "ldiv",
        "rand",
        "srand",
        "clock",
        "difftime",
        "mktime",
        "localtime",
        "gmtime",
        "strftime",
        "sizeof",
        "static_assert",
        # C++ specific
        "cout",
        "cin",
        "cerr",
        "clog",
        "endl",
        "getline",
        "push_back",
        "pop_back",
        "emplace_back",
        "emplace",
        "begin",
        "end",
        "rbegin",
        "rend",
        "cbegin",
        "cend",
        "size",
        "empty",
        "resize",
        "reserve",
        "capacity",
        "shrink_to_fit",
        "front",
        "back",
        "data",
        "at",
        "erase",
        "swap",
        "make_shared",
        "make_unique",
        "make_pair",
        "make_tuple",
        "move",
        "forward",
        "static_cast",
        "dynamic_cast",
        "const_cast",
        "reinterpret_cast",
        "stable_sort",
        "partial_sort",
        "nth_element",
        "lower_bound",
        "upper_bound",
        "binary_search",
        "accumulate",
        "transform",
        "unique",
        "rotate",
        "shuffle",
        "min_element",
        "max_element",
        "distance",
        "advance",
        "prev",
        "stoi",
        "stol",
        "stoll",
        "stof",
        "stod",
        "to_string",
    }
    # -- PHP --------------------------------------------------------------
    | {
        "echo",
        "print_r",
        "var_dump",
        "var_export",
        "isset",
        "unset",
        "is_null",
        "is_array",
        "is_string",
        "is_int",
        "is_float",
        "is_bool",
        "is_numeric",
        "is_callable",
        "is_object",
        "array_push",
        "array_pop",
        "array_shift",
        "array_unshift",
        "array_merge",
        "array_slice",
        "array_splice",
        "array_keys",
        "array_values",
        "array_map",
        "array_filter",
        "array_reduce",
        "array_walk",
        "array_search",
        "array_unique",
        "array_reverse",
        "array_flip",
        "array_combine",
        "array_diff",
        "array_intersect",
        "array_key_exists",
        "in_array",
        "strpos",
        "strrpos",
        "substr",
        "str_replace",
        "str_pad",
        "str_repeat",
        "str_split",
        "strtolower",
        "strtoupper",
        "ucfirst",
        "lcfirst",
        "ucwords",
        "ltrim",
        "rtrim",
        "explode",
        "implode",
        "number_format",
        "json_encode",
        "json_decode",
        "date",
        "strtotime",
        "file_get_contents",
        "file_put_contents",
        "file_exists",
        "is_file",
        "is_dir",
        "mkdir",
        "rmdir",
        "unlink",
        "rename",
        "glob",
        "preg_match",
        "preg_match_all",
        "preg_replace",
        "preg_split",
        "intval",
        "floatval",
        "strval",
        "boolval",
        "settype",
        "gettype",
        "class_exists",
        "method_exists",
        "property_exists",
        "function_exists",
        "get_class",
        "get_parent_class",
        "is_a",
    }
    # -- Swift -------------------------------------------------------------
    | {
        "debugPrint",
        "dump",
        "fatalError",
        "precondition",
        "preconditionFailure",
        "assertionFailure",
        "stride",
        "sequence",
        "repeatElement",
        "unsafeBitCast",
        "withUnsafePointer",
        "withUnsafeMutablePointer",
        "withUnsafeBytes",
        "MemoryLayout",
        "numericCast",
        "removeAll",
        "removeFirst",
        "removeLast",
        "firstIndex",
        "lastIndex",
        "compactMap",
        "enumerated",
        "prefix",
        "suffix",
        "dropFirst",
        "joined",
        "components",
        "lowercased",
        "uppercased",
        "capitalized",
        "hasPrefix",
        "hasSuffix",
        "replacingOccurrences",
        "trimmingCharacters",
        "string",
    }
)

# ---------------------------------------------------------------------------
# Function node types  (GitNexus parse-worker.ts lines 269-281)
# ---------------------------------------------------------------------------

FUNCTION_NODE_TYPES: frozenset[str] = frozenset(
    {
        # JavaScript / TypeScript
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function_declaration",
        "generator_function",
        # Python / C / C++ / PHP
        "function_definition",
        # Java / C# / Go / PHP
        "method_declaration",
        "constructor_declaration",
        "local_function_statement",
        # Rust
        "function_item",
        # Swift
        "protocol_function_declaration",
        "init_declaration",
    }
)


# ---------------------------------------------------------------------------
# Capture → label mapping  (GitNexus parse-worker.ts lines 454-482)
# ---------------------------------------------------------------------------

_CAPTURE_LABEL_MAP: dict[str, str] = {
    "definition.class": "Class",
    "definition.interface": "Interface",
    "definition.function": "Function",
    "definition.method": "Method",
    "definition.struct": "Struct",
    "definition.enum": "Enum",
    "definition.namespace": "Namespace",
    "definition.module": "Module",
    "definition.trait": "Trait",
    "definition.impl": "Impl",
    "definition.type": "TypeAlias",
    "definition.const": "Const",
    "definition.static": "Static",
    "definition.typedef": "Typedef",
    "definition.macro": "Macro",
    "definition.union": "Union",
    "definition.property": "Property",
    "definition.record": "Record",
    "definition.delegate": "Delegate",
    "definition.annotation": "Annotation",
    "definition.constructor": "Constructor",
    "definition.template": "Template",
}


def get_label_from_captures(
    capture_map: dict[str, Node],
) -> str | None:
    """Determine the entity label from a query-match capture map.

    Iterates the capture names and returns the first matching label
    from the ``_CAPTURE_LABEL_MAP``.

    Args:
        capture_map: Flattened ``{capture_name: Node}`` dict from a
            tree-sitter query match.

    Returns:
        The label string (e.g. ``"Function"``) or ``None`` when no
        definition capture is present.
    """
    for key in capture_map:
        if key in _CAPTURE_LABEL_MAP:
            return _CAPTURE_LABEL_MAP[key]
    return None


# ---------------------------------------------------------------------------
# Definition capture keys  (GitNexus parse-worker.ts lines 484-507)
# ---------------------------------------------------------------------------

DEFINITION_CAPTURE_KEYS: tuple[str, ...] = (
    "definition.class",
    "definition.interface",
    "definition.function",
    "definition.method",
    "definition.struct",
    "definition.enum",
    "definition.namespace",
    "definition.module",
    "definition.trait",
    "definition.impl",
    "definition.type",
    "definition.const",
    "definition.static",
    "definition.typedef",
    "definition.macro",
    "definition.union",
    "definition.property",
    "definition.record",
    "definition.delegate",
    "definition.annotation",
    "definition.constructor",
    "definition.template",
)


# ---------------------------------------------------------------------------
# Definition node extractor  (GitNexus parse-worker.ts lines 509-514)
# ---------------------------------------------------------------------------


def get_definition_node(
    capture_map: dict[str, Node],
) -> Node | None:
    """Return the AST node captured as a definition.

    Args:
        capture_map: Flattened capture map from a query match.

    Returns:
        The ``Node`` captured under a ``definition.*`` key, or ``None``.
    """
    for key in DEFINITION_CAPTURE_KEYS:
        if key in capture_map:
            return capture_map[key]
    return None


# ---------------------------------------------------------------------------
# Export detection  (GitNexus parse-worker.ts lines 145-263)
# ---------------------------------------------------------------------------


def is_node_exported(
    node: Node,
    name: str,
    language: str,
) -> bool:
    """Determine whether a definition node is exported / publicly visible.

    The heuristic is language-specific:

    * **JavaScript / TypeScript / TSX** - walk up looking for
      ``export_statement``.
    * **Python** - names not starting with ``_`` are considered public.
    * **Java** - look for a ``public`` modifier among siblings.
    * **Go** - first character of *name* is uppercase.
    * **Rust** - look for a ``visibility_modifier`` child containing
      ``pub``.
    * **Kotlin** - default is public; look for ``private``,
      ``internal``, or ``protected`` modifiers.
    * **C / C++** - always ``False`` (no native export concept at the
      language level).
    * **PHP** - top-level classes/functions are accessible; methods
      need an explicit ``public`` modifier.
    * **Swift** - look for ``public`` or ``open`` modifier.
    * **C#** - look for ``public`` modifier.

    Args:
        node: The AST node for the definition.
        name: The symbol name.
        language: Language key (e.g. ``"python"``).

    Returns:
        ``True`` if the symbol is considered exported / public.
    """
    lang = language.lower()

    # -- JavaScript / TypeScript / TSX ------------------------------------
    if lang in {"javascript", "typescript", "tsx"}:
        current = node
        while current is not None:
            if current.type == "export_statement":
                return True
            current = current.parent
        return False

    # -- Python -----------------------------------------------------------
    if lang == "python":
        return not name.startswith("_")

    # -- Java -------------------------------------------------------------
    if lang == "java":
        return _has_modifier(node, "public")

    # -- Go ---------------------------------------------------------------
    if lang == "go":
        return len(name) > 0 and name[0].isupper()

    # -- Rust -------------------------------------------------------------
    if lang == "rust":
        for child in node.children:
            if child.type == "visibility_modifier":
                text = child.text.decode("utf-8") if child.text else ""
                if "pub" in text:
                    return True
        return False

    # -- Kotlin -----------------------------------------------------------
    if lang == "kotlin":
        # Kotlin defaults to public; only return False when an
        # explicit private/internal/protected modifier is present.
        for child in node.children:
            if child.type == "modifiers":
                mod_text = child.text.decode("utf-8") if child.text else ""
                if any(kw in mod_text for kw in ("private", "internal", "protected")):
                    return False
        return True

    # -- C / C++ ----------------------------------------------------------
    if lang in {"c", "cpp"}:
        return False

    # -- PHP --------------------------------------------------------------
    if lang == "php":
        # Top-level classes/functions/interfaces are accessible
        parent = node.parent
        if parent is not None and parent.type in {
            "program",
            "namespace_definition",
            "declaration_list",
        }:
            # Methods inside classes need public modifier
            if node.type in {"method_declaration", "property_declaration"}:
                return _has_modifier(node, "public")
            return True
        if node.type in {"method_declaration", "property_declaration"}:
            return _has_modifier(node, "public")
        return True

    # -- Swift ------------------------------------------------------------
    if lang == "swift":
        for child in node.children:
            if child.type == "modifiers":
                mod_text = child.text.decode("utf-8") if child.text else ""
                if "public" in mod_text or "open" in mod_text:
                    return True
        return False

    # -- C# ---------------------------------------------------------------
    if lang == "csharp":
        return _has_modifier(node, "public")

    return False


def _has_modifier(node: Node, modifier: str) -> bool:
    """Check whether *node* or its immediate children contain *modifier*.

    Walks the direct children looking for ``modifiers`` or the modifier
    keyword directly.

    Args:
        node: AST node to inspect.
        modifier: Keyword to search for (e.g. ``"public"``).

    Returns:
        ``True`` if the modifier is found.
    """
    for child in node.children:
        if child.type == "modifiers" or child.type == modifier:
            text = child.text.decode("utf-8") if child.text else ""
            if modifier in text:
                return True
    return False


# ---------------------------------------------------------------------------
# Enclosing function lookup  (GitNexus parse-worker.ts lines 284-336)
# ---------------------------------------------------------------------------


def find_enclosing_function_id(
    node: Node,
    file_path: str,
) -> str | None:
    """Walk up the AST from *node* to find the nearest enclosing function.

    If found, generates and returns a deterministic ID for that function.
    Returns ``None`` when the call is at the top level (no enclosing
    function).

    Args:
        node: The AST node whose ancestor chain is inspected.
        file_path: Source file path (used in ID generation).

    Returns:
        The enclosing function's ID, or ``None``.
    """
    current = node.parent
    while current is not None:
        if current.type in FUNCTION_NODE_TYPES:
            # Try to extract the function name
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                func_name = name_node.text.decode("utf-8") if name_node.text else ""
                start_line = current.start_point[0] + 1
                label = (
                    "Method"
                    if current.type
                    in {
                        "method_definition",
                        "method_declaration",
                    }
                    else "Function"
                )
                key = f"{file_path}:{func_name}:{start_line}"
                return generate_id(label, key)
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# Single-file parse  (GitNexus parse-worker.ts ``processFileGroup``
#   lines 1089-1257)
# ---------------------------------------------------------------------------


def parse_file(
    file_path: str,
    content: bytes,
    language: str,
) -> ParseResult:
    """Parse a single source file and extract all code entities.

    This is the main parsing entry point.  It:

    1. Loads the ``Language`` for *language* (handling TSX variant).
    2. Creates a ``Parser`` and parses *content* into a tree.
    3. Skips files exceeding 512 KB.
    4. Compiles the appropriate tree-sitter query.
    5. Runs ``query.matches`` and iterates matches.
    6. Extracts imports, calls, heritage, and definitions.

    Args:
        file_path: Logical path of the file (used in IDs and metadata).
        content: Raw source bytes.
        language: Language key (e.g. ``"python"``, ``"typescript"``).

    Returns:
        A ``ParseResult`` containing all extracted artefacts.
    """
    from tree_sitter import Parser

    result = ParseResult()

    # --- guard: file size ------------------------------------------------
    if len(content) > _MAX_FILE_BYTES:
        logger.debug(
            "Skipping %s (%d bytes > %d limit)",
            file_path,
            len(content),
            _MAX_FILE_BYTES,
        )
        return result

    # --- resolve language (handle .tsx) ----------------------------------
    effective_lang = language
    if language == "typescript" and file_path.endswith(".tsx"):
        effective_lang = "tsx"

    lang_obj = _get_language(effective_lang)
    if lang_obj is None:
        logger.debug(
            "No tree-sitter grammar for %r; skipping %s",
            effective_lang,
            file_path,
        )
        return result

    # --- query string ----------------------------------------------------
    query_lang = language  # queries keyed by base language
    if effective_lang == "tsx":
        query_lang = "typescript"

    query_str = LANGUAGE_QUERIES.get(query_lang)
    if query_str is None:
        logger.debug(
            "No query defined for language %r; skipping %s",
            query_lang,
            file_path,
        )
        return result

    # --- parse -----------------------------------------------------------
    parser = Parser(lang_obj)
    tree = parser.parse(content)

    # --- compile & run query ---------------------------------------------
    try:
        query = cast(QueryProtocol, lang_obj.query(query_str))
    except Exception:
        logger.warning(
            "Failed to compile query for %s (%s); skipping",
            file_path,
            language,
            exc_info=True,
        )
        return result

    raw_matches: list[tuple[int, dict[str, list[Any]]]] = query.matches(tree.root_node)

    # --- iterate matches -------------------------------------------------
    file_id = generate_id("File", file_path)
    result.file_count = 1

    for _pattern_idx, raw_captures in raw_matches:
        # Flatten list[Node] → single Node (take first element)
        capture_map: dict[str, Node] = {k: v[0] for k, v in raw_captures.items() if v}

        # ---- imports ----------------------------------------------------
        if "import" in capture_map or "import.source" in capture_map:
            _extract_import(capture_map, file_path, language, result)

        # ---- calls ------------------------------------------------------
        if "call" in capture_map or "call.name" in capture_map:
            _extract_call(capture_map, file_path, file_id, result)

        # ---- heritage ---------------------------------------------------
        if "heritage" in capture_map or "heritage.impl" in capture_map:
            _extract_heritage(capture_map, file_path, result)

        # ---- definitions ------------------------------------------------
        label = get_label_from_captures(capture_map)
        if label is not None:
            _extract_definition(
                capture_map,
                label,
                file_path,
                file_id,
                language,
                effective_lang,
                result,
            )

    return result


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_import(
    capture_map: dict[str, Node],
    file_path: str,
    language: str,
    result: ParseResult,
) -> None:
    """Extract an import artefact from the capture map.

    Handles Kotlin wildcard imports (``import foo.bar.*``).

    Args:
        capture_map: Flattened capture map from a single match.
        file_path: Source file path.
        language: Language key.
        result: Mutable ``ParseResult`` to append to.
    """
    source_node = capture_map.get("import.source")
    if source_node is None:
        return

    raw_path = source_node.text.decode("utf-8") if source_node.text else ""
    if not raw_path:
        return

    # Strip surrounding quotes (common in JS/TS/Go imports)
    raw_path = raw_path.strip("'\"")

    # Kotlin: check for wildcard import (import foo.bar.*)
    if language == "kotlin":
        import_node = capture_map.get("import")
        if import_node is not None:
            full_text = import_node.text.decode("utf-8") if import_node.text else ""
            if full_text.rstrip().endswith(".*"):
                raw_path = raw_path + ".*"

    result.imports.append(
        ExtractedImport(
            file_path=file_path,
            raw_import_path=raw_path,
            language=language,
        )
    )


def _extract_call(
    capture_map: dict[str, Node],
    file_path: str,
    file_id: str,
    result: ParseResult,
) -> None:
    """Extract a function/method call from the capture map.

    Filters out calls to built-in names (``BUILT_INS``).

    Args:
        capture_map: Flattened capture map from a single match.
        file_path: Source file path.
        file_id: The file's deterministic ID (fallback source for
            top-level calls).
        result: Mutable ``ParseResult`` to append to.
    """
    name_node = capture_map.get("call.name")
    if name_node is None:
        return

    called_name = name_node.text.decode("utf-8") if name_node.text else ""
    if not called_name or called_name in BUILT_INS:
        return

    # Determine the enclosing function
    call_node = capture_map.get("call", name_node)
    source_id = find_enclosing_function_id(call_node, file_path)
    if source_id is None:
        source_id = file_id

    result.calls.append(
        ExtractedCall(
            file_path=file_path,
            called_name=called_name,
            source_id=source_id,
        )
    )


def _extract_heritage(
    capture_map: dict[str, Node],
    file_path: str,
    result: ParseResult,
) -> None:
    """Extract a heritage (inheritance) relationship.

    Handles ``extends``, ``implements``, and ``trait-impl`` patterns.

    Args:
        capture_map: Flattened capture map from a single match.
        file_path: Source file path.
        result: Mutable ``ParseResult`` to append to.
    """
    class_node = capture_map.get("heritage.class")
    if class_node is None:
        return

    class_name = class_node.text.decode("utf-8") if class_node.text else ""
    if not class_name:
        return

    # Extends
    extends_node = capture_map.get("heritage.extends")
    if extends_node is not None:
        parent_name = extends_node.text.decode("utf-8") if extends_node.text else ""
        if parent_name:
            result.heritage.append(
                ExtractedHeritage(
                    file_path=file_path,
                    class_name=class_name,
                    parent_name=parent_name,
                    kind="extends",
                )
            )

    # Implements
    impl_node = capture_map.get("heritage.implements")
    if impl_node is not None:
        parent_name = impl_node.text.decode("utf-8") if impl_node.text else ""
        if parent_name:
            result.heritage.append(
                ExtractedHeritage(
                    file_path=file_path,
                    class_name=class_name,
                    parent_name=parent_name,
                    kind="implements",
                )
            )

    # Trait impl (Rust)
    trait_node = capture_map.get("heritage.trait")
    if trait_node is not None:
        trait_name = trait_node.text.decode("utf-8") if trait_node.text else ""
        if trait_name:
            result.heritage.append(
                ExtractedHeritage(
                    file_path=file_path,
                    class_name=class_name,
                    parent_name=trait_name,
                    kind="trait-impl",
                )
            )


def _extract_definition(
    capture_map: dict[str, Node],
    label: str,
    file_path: str,
    file_id: str,
    language: str,
    effective_lang: str,
    result: ParseResult,
) -> None:
    """Extract a definition (class, function, method, etc.).

    Creates a ``ParsedNode``, a ``ParsedRelationship`` (file → entity),
    and a ``ParsedSymbol`` entry.

    Args:
        capture_map: Flattened capture map from a single match.
        label: Entity label (e.g. ``"Function"``).
        file_path: Source file path.
        file_id: The file's deterministic ID (relationship source).
        language: Base language key.
        effective_lang: Actual language used for parsing (may be ``"tsx"``).
        result: Mutable ``ParseResult`` to append to.
    """
    definition_node = get_definition_node(capture_map)
    if definition_node is None:
        return

    name_node = capture_map.get("name")

    # For constructors (e.g. Swift init_declaration) without a name
    # capture, use the label itself as the name.
    if name_node is not None:
        name = name_node.text.decode("utf-8") if name_node.text else ""
    else:
        name = label.lower()

    if not name:
        return

    start_line = definition_node.start_point[0] + 1  # 1-indexed
    end_line = definition_node.end_point[0] + 1

    key = f"{file_path}:{name}:{start_line}"
    node_id = generate_id(label, key)

    exported = is_node_exported(definition_node, name, language)

    parsed_node = ParsedNode(
        id=node_id,
        label=label,  # type: ignore[arg-type]
        properties=ParsedNodeProperties(
            name=name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language=language,
            is_exported=exported,
        ),
    )
    result.nodes.append(parsed_node)

    # DEFINES relationship
    rel_key = f"{file_id}->{node_id}"
    rel_id = generate_id("Defines", rel_key)
    result.relationships.append(
        ParsedRelationship(
            id=rel_id,
            source_id=file_id,
            target_id=node_id,
            type="DEFINES",
            confidence=1.0,
            reason="tree-sitter query match",
        )
    )

    # Symbol table entry
    result.symbols.append(
        ParsedSymbol(
            file_path=file_path,
            name=name,
            node_id=node_id,
            type=label,
        )
    )


# ---------------------------------------------------------------------------
# Batch parse  (GitNexus parse-worker.ts ``processBatch`` lines 533-612)
# ---------------------------------------------------------------------------


def parse_batch(
    files: Sequence[tuple[str, bytes, str]],
) -> ParseResult:
    """Parse multiple files, returning a merged ``ParseResult``.

    Files are grouped by language so that the tree-sitter ``Parser``
    can be reused across files sharing the same grammar, minimising
    repeated language-loading overhead.

    Args:
        files: Sequence of ``(file_path, content, language)`` tuples.

    Returns:
        An aggregated ``ParseResult`` with results from all files.
    """
    merged = ParseResult()

    # Group files by effective language for parser reuse
    groups: dict[str, list[tuple[str, bytes, str]]] = {}
    for file_path, content, language in files:
        effective = language
        if language == "typescript" and file_path.endswith(".tsx"):
            effective = "tsx"
        groups.setdefault(effective, []).append((file_path, content, language))

    for _effective_lang, group in groups.items():
        for file_path, content, language in group:
            file_result = parse_file(file_path, content, language)
            _merge_results(merged, file_result)

    return merged


def _merge_results(target: ParseResult, source: ParseResult) -> None:
    """Merge *source* into *target* in place.

    Args:
        target: The accumulating result.
        source: New results to append.
    """
    target.nodes.extend(source.nodes)
    target.relationships.extend(source.relationships)
    target.symbols.extend(source.symbols)
    target.imports.extend(source.imports)
    target.calls.extend(source.calls)
    target.heritage.extend(source.heritage)
    target.file_count += source.file_count
