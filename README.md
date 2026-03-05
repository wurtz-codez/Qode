# Qode

> **Local-first, multi-agent code archaeology and intelligence system.**

Qode ingests entire codebases — including massive, undocumented, or legacy systems — and reverse-engineers the complete architecture into an interactive, multi-dimensional knowledge graph. It runs **entirely on your machine**, never sending code to external servers.

---

## Features

- 🔍 **Structural Mapping** — discovers every file, class, function, and their relationships
- 📝 **Semantic Documentation** — generates natural language explanations for undocumented code
- 🔬 **Code Quality Forensics** — detects anti-patterns, calculates technical debt score (0–100)
- 🔒 **Security Analysis** — OWASP Top 10, secrets detection, taint analysis
- 💥 **Impact Prediction** — answers "if I change X, what breaks?" via graph traversal
- 🌐 **Interactive Visualization** — Sigma.js WebGL graph handles 50K+ nodes
- 🔒 **Privacy-first** — 100% local; Ollama support for fully offline analysis

---

## Quick Start

```bash
pip install qode
cd /path/to/your-project
qode analyze .
```

---

## Installation (Development)

```bash
git clone https://github.com/koustubhpande/qode
cd qode
make install          # creates .venv, installs deps + pre-commit hooks
cp .env.example .env  # add your API keys
```

---

## CLI Commands

| Command | Description |
|---|---|
| `qode analyze <path>` | Full analysis (Explorer → Analyst → Security → Test → Documenter) |
| `qode docs <path>` | Documentation generation only |
| `qode security <path>` | Security analysis only |
| `qode graph <path>` | Build knowledge graph + open visualization |
| `qode gate <path>` | CI/CD mode: pass/fail with thresholds |
| `qode audit <path>` | CI/CD mode: full report, no gating |
| `qode config` | Open `.qode.toml` in default editor |

---

## Technology Stack

| Layer | Technology |
|---|---|
| CLI | Python (Typer + Rich) |
| Parser | py-tree-sitter (12 languages) |
| Core Engine | Python (multiprocessing + asyncio) |
| Agent Orchestration | LangGraph |
| LLM (default) | Gemini 2.0 Flash |
| Embeddings | all-MiniLM-L6-v2 (local) |
| Database | KuzuDB (graph + vectors + FTS) |
| Backend API | FastAPI |
| Frontend | Vite + React 18 + Sigma.js + Tailwind v4 |

---

## Development

```bash
make lint        # ruff check
make format      # black + ruff --fix
make typecheck   # pyright
make test        # pytest
make pre-commit  # run all pre-commit hooks
make audit       # pip-audit security check
```

---

## Project Status

**Phase 1 — Foundation (In Progress)**

- [x] Project skeleton: `pyproject.toml`, `src/qode/`, `tests/`, pre-commit hooks
- [ ] Core parsers + ingestion pipeline
- [ ] KuzuDB schema + adapter
- [ ] CLI skeleton (`qode analyze`)

See [Qode-documentation.md](Qode-documentation.md) for the full PRD.

---

## License

MIT © Koustubh Pande
