<div align="center">
  <img src="https://qode-beta.vercel.app/logo.png" alt="Qode Logo" width="120" height="120" />
  <h1>Qode</h1>
  <p>
    <strong>Visual codebase intelligence — explore any codebase as an interactive knowledge graph, directly in your browser.</strong>
  </p>
  <p>
    <a href="https://qode-beta.vercel.app" target="_blank">
      <img src="https://img.shields.io/badge/Try%20the%20Live%20App-qode--beta.vercel.app-blue?style=for-the-badge&logo=vercel" alt="Live App" />
    </a>
    <a href="https://www.npmjs.com/package/qode">
      <img src="https://img.shields.io/npm/v/qode.svg?style=for-the-badge" alt="npm version" />
    </a>
    <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/">
      <img src="https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg?style=for-the-badge" alt="License" />
    </a>
  </p>
</div>

---

## What is Qode?

Qode turns any codebase into a **visual knowledge graph**. Drop in a `.zip` of your repository (or point it at a GitHub repo), and Qode parses every file, maps every function call, import, and class dependency, and renders it all as an interactive 2D graph — right in your browser, with **zero code ever leaving your machine**.

It's code search, but smarter. Instead of grepping for text, you can:
- **See** the full architecture as a navigable graph
- **Trace** execution flows from entry points through call chains
- **Search** across symbols, files, and relationships with hybrid BM25 + semantic search
- **Chat** with an AI agent that has full awareness of your codebase structure

---

## Two Ways to Use

### 1. Web UI (No Install) — [qode-beta.vercel.app](https://qode-beta.vercel.app)

The browser app runs 100% client-side — no uploads, no servers. Drag & drop a `.zip` or connect a GitHub repo and start exploring instantly.

### 2. CLI / MCP (For AI Agents)

```bash
# Install globally
npm install -g qode

# Index any repository
qode analyze

# Or run without installing
npx qode analyze
```

Works with **Cursor**, **Claude Code**, **Windsurf**, **Cline**, **OpenCode**, and any MCP-compatible AI agent.

---

## Quick Start — Web UI

| Step | Action |
|------|--------|
| 1 | Open **[qode-beta.vercel.app](https://qode-beta.vercel.app)** |
| 2 | Drop a `.zip` of your codebase (or clone via GitHub URL) |
| 3 | Wait seconds — Qode indexes locally in your browser via WebAssembly |
| 4 | Explore the interactive graph, search symbols, trace flows, chat with AI |

## Quick Start — CLI

```bash
# Index your current repository
npx qode analyze

# Start the MCP server for AI agent integration
npx qode mcp
```

```bash
# Or serve a local HTTP API + UI
qode serve
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Knowledge Graph** | Full dependency graph of functions, classes, imports, and call chains |
| **Visual Explorer** | Interactive 2D graph with pan, zoom, filter, and cluster navigation |
| **Execution Flows** | Trace entry-point-to-exit call chains across files |
| **Hybrid Search** | BM25 + semantic embeddings + RRF fusion for pinpoint symbol lookup |
| **AI Chat** | LangChain ReAct agent with full graph context — ask questions about your code |
| **Multi-Language** | TypeScript, JavaScript, Python, Java, Kotlin, C, C++, C#, Go, Rust, PHP, Swift |
| **100% Local** | WebAssembly-powered parsing — your code never touches a server |

---

## Tech Stack

| Category | Technology |
|----------|-----------|
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS v4 |
| **Graph Rendering** | Sigma.js + Graphology (WebGL) |
| **Parsing** | Tree-sitter (WASM) |
| **Database** | KuzuDB WASM (embedded graph database) |
| **Embeddings** | HuggingFace Transformers.js (WebGPU / WASM) |
| **AI Agent** | LangChain ReAct agent |
| **Clustering** | Louvain / Leiden community detection |
| **Concurrency** | Web Workers + Comlink |

---

## Demo

```
[ Drag & drop a codebase → instant graph visualization ]

     ┌─────────────────────────────────┐
     │         Your Codebase           │
     │  ┌───┐  ┌───┐  ┌───┐  ┌───┐   │
     │  │ F │──│ G │──│ H │──│ I │   │
     │  └───┘  └───┘  └───┘  └───┘   │
     │    │      │              │      │
     │  ┌───┐  ┌───┐          ┌───┐   │
     │  │ J │  │ K │          │ L │   │
     │  └───┘  └───┘          └───┘   │
     └─────────────────────────────────┘
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `qode analyze [path]` | Index a repository |
| `qode analyze --force` | Force full re-index |
| `qode mcp` | Start MCP server (stdio) |
| `qode serve` | Start HTTP server + web UI |
| `qode list` | List all indexed repositories |
| `qode status` | Show index status |
| `qode clean` | Delete current index |
| `qode wiki [path]` | Generate docs from knowledge graph |

---

## Requirements

- **Web UI:** Any modern browser (Chrome, Firefox, Safari, Edge)
- **CLI:** Node.js >= 18, Git repository

---

## Privacy & Security

- **100% client-side** in the Web UI — your code never leaves your browser
- All parsing, indexing, and graph building happens locally via WebAssembly
- The CLI stores indexes locally in `.qode/` (automatically gitignored)
- No telemetry, no analytics, no data collection

---

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) — free for non-commercial use.

<p align="center">
  <a href="https://qode-beta.vercel.app" target="_blank"><strong>Try Qode now →</strong></a>
</p>
