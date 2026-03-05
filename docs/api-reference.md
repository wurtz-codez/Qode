# API Reference

Full REST and WebSocket API specification is in [Qode-documentation.md](../Qode-documentation.md) — Section 21.

## Base URL

```
http://localhost:3000
```

## Key Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/analyze` | Start new analysis |
| GET | `/api/v1/analyze/{id}` | Get analysis status |
| GET | `/api/v1/graph/nodes` | List graph nodes |
| POST | `/api/v1/graph/query` | Execute Cypher query |
| POST | `/api/v1/search/semantic` | Hybrid semantic search |
| GET | `/api/v1/reports/security` | Security findings |
| GET | `/api/v1/reports/debt` | Technical debt report |

## WebSocket

```
ws://localhost:3000/ws/analysis/{id}   # Agent progress streaming
ws://localhost:3000/ws/chat             # AI chat
```
