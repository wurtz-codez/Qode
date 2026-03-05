# Architecture

## System Overview

Qode is a local-first, multi-agent code intelligence system with five stages:

1. **Ingestion** — filesystem discovery + ignore pattern handling
2. **Parsing** — Tree-sitter CST parsing across 12 languages (parallel via `multiprocessing`)
3. **Graph Construction** — KuzuDB nodes/edges + HNSW vector index + BM25 FTS
4. **Agent Analysis** — LangGraph swarm (Explorer → Analyst + Security + Test → Documenter)
5. **Visualization** — FastAPI + Sigma.js WebGL dashboard

See the [full PRD](../Qode-documentation.md) for detailed specifications.
