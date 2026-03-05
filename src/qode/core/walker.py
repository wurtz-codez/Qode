"""Filesystem discovery with ignore-pattern support.

Ported from GitNexus ``filesystem-walker.ts`` (~121 lines → Python).
Implements recursive directory walk, respecting .gitignore and .qodeignore.
"""

from __future__ import annotations

# TODO(phase-1): implement filesystem walker
