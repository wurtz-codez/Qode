"""Tree-sitter S-expression queries for 12 supported languages.

Ported from GitNexus ``tree-sitter-queries.ts`` (~546 lines → Python).
Languages: Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, Ruby,
           PHP, Swift, Kotlin.
"""

from __future__ import annotations

# TODO(phase-1): port S-expression queries for all 12 languages

LANGUAGE_QUERIES: dict[str, str] = {}
