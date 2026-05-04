"""KuzuDB connection, bulk COPY, and connection pool.

Ported from Qode ``kuzu/kuzu-adapter.ts`` (~500 lines → Python).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import shutil
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

import kuzu

from .csv_generator import stream_all_csvs_to_disk
from .kuzu_schema import (
    EMBEDDING_TABLE_NAME,
    NODE_TABLES,
    REL_TABLE_NAME,
    SCHEMA_QUERIES,
    NodeTableName,
)

logger = logging.getLogger(__name__)

db: Any | None = None
conn: Any | None = None
current_db_path: str | None = None
fts_loaded = False

_session_lock = asyncio.Lock()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _run_with_session_lock(operation: Callable[[], Any]) -> Any:
    async with _session_lock:
        return await _maybe_await(operation())


def _normalize_copy_path(file_path: str) -> str:
    return file_path.replace("\\", "/")


async def init_kuzu(db_path: str) -> dict[str, object | None]:
    return await _run_with_session_lock(lambda: _ensure_kuzu_initialized(db_path))


async def with_kuzu_db(db_path: str, operation: Callable[[], Any]) -> Any:
    async def _wrapped() -> Any:
        await _ensure_kuzu_initialized(db_path)
        return await _maybe_await(operation())

    return await _run_with_session_lock(_wrapped)


async def _ensure_kuzu_initialized(db_path: str) -> dict[str, object | None]:
    if conn is not None and current_db_path == db_path:
        return {"db": db, "conn": conn}
    await _do_init_kuzu(db_path)
    return {"db": db, "conn": conn}


async def _do_init_kuzu(db_path: str) -> dict[str, object | None]:
    global db, conn, current_db_path, fts_loaded

    if conn is not None or db is not None:
        with suppress(Exception):
            if conn is not None:
                await _maybe_await(conn.close())
        with suppress(Exception):
            if db is not None:
                await _maybe_await(db.close())
        conn = None
        db = None
        current_db_path = None
        fts_loaded = False

    with suppress(Exception):
        if os.path.exists(db_path):
            if os.path.isdir(db_path):
                files = os.listdir(db_path)
                if len(files) == 0:
                    os.rmdir(db_path)
                else:
                    shutil.rmtree(db_path, ignore_errors=True)
            else:
                os.remove(db_path)

    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    for schema_query in SCHEMA_QUERIES:
        try:
            await _maybe_await(conn.query(schema_query))
        except Exception as err:
            msg = err.args[0] if err.args else str(err)
            if "already exists" not in str(msg):
                logger.warning("Schema creation warning: %s", str(msg)[:120])

    current_db_path = db_path
    return {"db": db, "conn": conn}


KuzuProgressCallback = Callable[[str], None]


async def load_graph_to_kuzu(
    graph: Any,
    repo_path: str,
    storage_path: str,
    on_progress: KuzuProgressCallback | None = None,
) -> dict[str, Any]:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")

    log = on_progress or (lambda _: None)
    csv_dir = os.path.join(storage_path, "csv")

    log("Streaming CSVs to disk...")
    csv_result = await stream_all_csvs_to_disk(graph, repo_path, csv_dir)

    valid_tables: set[str] = {str(name) for name in NODE_TABLES}

    def get_node_label(node_id: str) -> str:
        if node_id.startswith("comm_"):
            return "Community"
        if node_id.startswith("proc_"):
            return "Process"
        return node_id.split(":")[0]

    node_files = list(csv_result["nodeFiles"].items())
    total_steps = len(node_files) + 1
    for steps_done, (table, payload) in enumerate(node_files, start=1):
        rows = payload["rows"]
        log(f"Loading nodes {steps_done}/{total_steps}: {table} ({rows:,} rows)")

        normalized_path = _normalize_copy_path(payload["csvPath"])
        copy_query = _get_copy_query(table, normalized_path)
        try:
            await _maybe_await(conn.query(copy_query))
        except Exception:
            try:
                retry_query = copy_query.replace(
                    "auto_detect=false)", "auto_detect=false, IGNORE_ERRORS=true)"
                )
                await _maybe_await(conn.query(retry_query))
            except Exception as retry_err:
                retry_msg = retry_err.args[0] if retry_err.args else str(retry_err)
                raise RuntimeError(
                    f"COPY failed for {table}: {str(retry_msg)[:200]}"
                ) from retry_err

    rel_header = ""
    rels_by_pair: dict[str, list[str]] = {}
    skipped_rels = 0
    total_valid_rels = 0

    rel_csv_path = csv_result["relCsvPath"]
    with open(rel_csv_path, encoding="utf-8", errors="replace") as handle:
        is_first = True
        for line in handle:
            line = line.rstrip("\n")
            if is_first:
                rel_header = line
                is_first = False
                continue
            if not line.strip():
                continue
            match = re.match(r'"([^"]*)","([^"]*)"', line)
            if not match:
                skipped_rels += 1
                continue
            from_label = get_node_label(match.group(1))
            to_label = get_node_label(match.group(2))
            if from_label not in valid_tables or to_label not in valid_tables:
                skipped_rels += 1
                continue
            pair_key = f"{from_label}|{to_label}"
            rels_by_pair.setdefault(pair_key, []).append(line)
            total_valid_rels += 1

    inserted_rels = total_valid_rels
    warnings: list[str] = []
    if inserted_rels > 0:
        log(f"Loading edges: {inserted_rels:,} across {len(rels_by_pair)} types")
        failed_pair_edges = 0
        failed_pair_lines: list[str] = []

        for pair_idx, (pair_key, lines) in enumerate(rels_by_pair.items(), start=1):
            from_label, to_label = pair_key.split("|")
            pair_csv_path = os.path.join(csv_dir, f"rel_{from_label}_{to_label}.csv")
            with open(pair_csv_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(rel_header + "\n" + "\n".join(lines))

            normalized_path = _normalize_copy_path(pair_csv_path)
            copy_query = (
                f'COPY {REL_TABLE_NAME} FROM "{normalized_path}" '
                f'(from="{from_label}", to="{to_label}", {COPY_CSV_OPTS})'
            )

            if pair_idx % 5 == 0 or len(lines) > 1000:
                log(
                    f"Loading edges: {pair_idx}/{len(rels_by_pair)} types "
                    f"({from_label} -> {to_label})"
                )

            try:
                await _maybe_await(conn.query(copy_query))
            except Exception:
                try:
                    retry_query = copy_query.replace(
                        "auto_detect=false)", "auto_detect=false, IGNORE_ERRORS=true)"
                    )
                    await _maybe_await(conn.query(retry_query))
                except Exception as retry_err:
                    retry_msg = retry_err.args[0] if retry_err.args else str(retry_err)
                    warnings.append(
                        f"{from_label}->{to_label} ({len(lines)} edges): "
                        f"{str(retry_msg)[:80]}"
                    )
                    failed_pair_edges += len(lines)
                    failed_pair_lines.extend(lines)
            with suppress(Exception):
                os.remove(pair_csv_path)

        if failed_pair_lines:
            log(
                "Inserting "
                f"{failed_pair_edges} edges individually (missing schema pairs)"
            )
            await _fallback_relationship_inserts(
                [rel_header, *failed_pair_lines], valid_tables, get_node_label
            )

    with suppress(Exception):
        os.remove(csv_result["relCsvPath"])
    for payload in csv_result["nodeFiles"].values():
        with suppress(Exception):
            os.remove(payload["csvPath"])
    with suppress(Exception):
        for remaining in os.listdir(csv_dir):
            with suppress(Exception):
                os.remove(os.path.join(csv_dir, remaining))
    with suppress(Exception):
        os.rmdir(csv_dir)

    return {
        "success": True,
        "insertedRels": inserted_rels,
        "skippedRels": skipped_rels,
        "warnings": warnings,
    }


COPY_CSV_OPTS = (
    "HEADER=true, ESCAPE='\"', DELIM=',', QUOTE='\"', PARALLEL=false, auto_detect=false"
)

BACKTICK_TABLES = {
    "Struct",
    "Enum",
    "Macro",
    "Typedef",
    "Union",
    "Namespace",
    "Trait",
    "Impl",
    "TypeAlias",
    "Const",
    "Static",
    "Property",
    "Record",
    "Delegate",
    "Annotation",
    "Constructor",
    "Template",
    "Module",
}


def _escape_table_name(table: str) -> str:
    return f"`{table}`" if table in BACKTICK_TABLES else table


async def _fallback_relationship_inserts(
    valid_rel_lines: Sequence[str],
    valid_tables: set[str],
    get_node_label: Callable[[str], str],
) -> None:
    if conn is None:
        return

    def escape_label(label: str) -> str:
        return f"`{label}`" if label in BACKTICK_TABLES else label

    for line in valid_rel_lines[1:]:
        try:
            match = re.match(
                r'"([^"]*)","([^"]*)","([^"]*)",([0-9.]+),"([^"]*)",([0-9-]+)',
                line,
            )
            if not match:
                continue
            from_id, to_id, rel_type, confidence_str, reason, step_str = match.groups()
            from_label = get_node_label(from_id)
            to_label = get_node_label(to_id)
            if from_label not in valid_tables or to_label not in valid_tables:
                continue

            confidence = float(confidence_str) if confidence_str else 1.0
            step = int(step_str) if step_str else 0

            from_id_escaped = from_id.replace("'", "''")
            to_id_escaped = to_id.replace("'", "''")
            rel_type_escaped = rel_type.replace("'", "''")
            reason_escaped = reason.replace("'", "''")

            from_label_escaped = escape_label(from_label)
            to_label_escaped = escape_label(to_label)
            query = (
                f"MATCH (a:{from_label_escaped} {{id: '{from_id_escaped}' }}) "
                f"(b:{to_label_escaped} {{id: '{to_id_escaped}' }}) "
                "CREATE (a)-"
                f"[:{REL_TABLE_NAME} {{type: '{rel_type_escaped}', "
                f"confidence: {confidence}, reason: '{reason_escaped}', "
                f"step: {step}}}]->(b)"
            )
            await _maybe_await(conn.query(query))
        except Exception:
            continue


TABLES_WITH_EXPORTED = {"Function", "Class", "Interface", "Method", "CodeElement"}


def _get_copy_query(table: NodeTableName, file_path: str) -> str:
    t = _escape_table_name(table)
    if table == "File":
        return (
            f"COPY {t}(id, name, filePath, content) "
            f'FROM "{file_path}" ({COPY_CSV_OPTS})'
        )
    if table == "Folder":
        return f'COPY {t}(id, name, filePath) FROM "{file_path}" ({COPY_CSV_OPTS})'
    if table == "Community":
        return (
            "COPY "
            f"{t}(id, label, heuristicLabel, keywords, description, enrichedBy, "
            "cohesion, symbolCount) "
            f'FROM "{file_path}" ({COPY_CSV_OPTS})'
        )
    if table == "Process":
        return (
            "COPY "
            f"{t}(id, label, heuristicLabel, processType, stepCount, communities, "
            "entryPointId, terminalId) "
            f'FROM "{file_path}" ({COPY_CSV_OPTS})'
        )
    if table in TABLES_WITH_EXPORTED:
        return (
            "COPY "
            f"{t}(id, name, filePath, startLine, endLine, isExported, content, "
            "description) "
            f'FROM "{file_path}" ({COPY_CSV_OPTS})'
        )
    return (
        "COPY "
        f"{t}(id, name, filePath, startLine, endLine, content, description) "
        f'FROM "{file_path}" ({COPY_CSV_OPTS})'
    )


def _extract_row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, (list, tuple)) and len(row) > index:
        return row[index]
    return None


async def _get_all_rows(result: Any) -> list[Any]:
    if hasattr(result, "get_all"):
        return await _maybe_await(result.get_all())
    if hasattr(result, "getAll"):
        return await _maybe_await(result.getAll())
    return []


async def execute_query(cypher: str) -> list[Any]:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")

    query_result = await _maybe_await(conn.query(cypher))
    result = query_result[0] if isinstance(query_result, list) else query_result
    return await _get_all_rows(result)


def _stmt_is_success(stmt: Any) -> bool:
    if hasattr(stmt, "isSuccess"):
        return bool(stmt.isSuccess())
    if hasattr(stmt, "is_success"):
        return bool(stmt.is_success())
    return True


def _stmt_error_message(stmt: Any) -> str:
    if hasattr(stmt, "getErrorMessage"):
        return str(stmt.getErrorMessage())
    if hasattr(stmt, "get_error_message"):
        return str(stmt.get_error_message())
    return ""


async def execute_with_reused_statement(
    cypher: str,
    params_list: list[dict[str, Any]],
) -> None:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")
    if not params_list:
        return

    sub_batch_size = 4
    for start in range(0, len(params_list), sub_batch_size):
        sub_batch = params_list[start : start + sub_batch_size]
        stmt = await _maybe_await(conn.prepare(cypher))
        if not _stmt_is_success(stmt):
            err_msg = _stmt_error_message(stmt)
            raise RuntimeError(f"Prepare failed: {err_msg}")
        try:
            for params in sub_batch:
                await _maybe_await(conn.execute(stmt, params))
        except Exception as exc:
            logger.warning("Batch execution error: %s", exc)


async def get_kuzu_stats() -> dict[str, int]:
    if conn is None:
        return {"nodes": 0, "edges": 0}

    total_nodes = 0
    for table_name in NODE_TABLES:
        with suppress(Exception):
            query_result = await _maybe_await(
                conn.query(
                    f"MATCH (n:{_escape_table_name(table_name)}) RETURN count(n) AS cnt"
                )
            )
            node_result = (
                query_result[0] if isinstance(query_result, list) else query_result
            )
            node_rows = await _get_all_rows(node_result)
            if node_rows:
                total_nodes += int(_extract_row_value(node_rows[0], "cnt", 0) or 0)

    total_edges = 0
    with suppress(Exception):
        query_result = await _maybe_await(
            conn.query(f"MATCH ()-[r:{REL_TABLE_NAME}]->() RETURN count(r) AS cnt")
        )
        edge_result = (
            query_result[0] if isinstance(query_result, list) else query_result
        )
        edge_rows = await _get_all_rows(edge_result)
        if edge_rows:
            total_edges = int(_extract_row_value(edge_rows[0], "cnt", 0) or 0)

    return {"nodes": total_nodes, "edges": total_edges}


async def load_cached_embeddings() -> dict[str, Any]:
    if conn is None:
        return {"embeddingNodeIds": set(), "embeddings": []}

    embedding_node_ids: set[str] = set()
    embeddings: list[dict[str, Any]] = []
    with suppress(Exception):
        rows_result = await _maybe_await(
            conn.query(
                f"MATCH (e:{EMBEDDING_TABLE_NAME}) RETURN e.nodeId AS nodeId, "
                "e.embedding AS embedding"
            )
        )
        result = rows_result[0] if isinstance(rows_result, list) else rows_result
        for row in await _get_all_rows(result):
            node_id = str(_extract_row_value(row, "nodeId", 0) or "")
            if not node_id:
                continue
            embedding_node_ids.add(node_id)
            embedding_value = _extract_row_value(row, "embedding", 1)
            if embedding_value is None:
                continue
            if isinstance(embedding_value, list):
                vector = [float(v) for v in embedding_value]
            else:
                try:
                    vector = [float(v) for v in list(embedding_value)]
                except Exception:
                    continue
            embeddings.append({"nodeId": node_id, "embedding": vector})

    return {"embeddingNodeIds": embedding_node_ids, "embeddings": embeddings}


async def upsert_embeddings(
    embeddings: Sequence[dict[str, Any]],
) -> dict[str, int]:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")
    if not embeddings:
        return {"inserted": 0, "failed": 0}

    cypher = (
        f"MERGE (e:{EMBEDDING_TABLE_NAME} {{nodeId: $nodeId}}) "
        "SET e.embedding = $embedding"
    )
    params_list = []
    for item in embeddings:
        node_id = str(item.get("nodeId") or "")
        embedding_value = item.get("embedding")
        if not node_id or embedding_value is None:
            continue
        params_list.append({"nodeId": node_id, "embedding": embedding_value})
    if not params_list:
        return {"inserted": 0, "failed": 0}

    await execute_with_reused_statement(cypher, params_list)
    return {"inserted": len(params_list), "failed": 0}


async def close_kuzu() -> None:
    global db, conn, current_db_path, fts_loaded
    if conn is not None:
        with suppress(Exception):
            await _maybe_await(conn.close())
        conn = None
    if db is not None:
        with suppress(Exception):
            await _maybe_await(db.close())
        db = None
    current_db_path = None
    fts_loaded = False


def is_kuzu_ready() -> bool:
    return conn is not None and db is not None


async def delete_nodes_for_file(
    file_path: str,
    db_path: str | None = None,
) -> dict[str, int]:
    use_per_query = db_path is not None
    temp_db: Any | None = None
    temp_conn: Any | None = None
    target_conn = conn

    if use_per_query:
        temp_db = kuzu.Database(db_path)
        temp_conn = kuzu.Connection(temp_db)
        target_conn = temp_conn
    elif conn is None:
        raise RuntimeError(
            "KuzuDB not initialized. Provide dbPath or call initKuzu first."
        )

    try:
        if target_conn is None:
            raise RuntimeError(
                "KuzuDB not initialized. Provide dbPath or call initKuzu first."
            )
        deleted_nodes = 0
        escaped_path = file_path.replace("'", "''")
        for table_name in NODE_TABLES:
            if table_name in ("Community", "Process"):
                continue
            try:
                tn = _escape_table_name(table_name)
                count_result = await _maybe_await(
                    target_conn.query(
                        f"MATCH (n:{tn}) WHERE n.filePath = '{escaped_path}' "
                        "RETURN count(n) AS cnt"
                    )
                )
                result = (
                    count_result[0] if isinstance(count_result, list) else count_result
                )
                rows = await _get_all_rows(result)
                count = int(_extract_row_value(rows[0], "cnt", 0) or 0) if rows else 0
                if count > 0:
                    await _maybe_await(
                        target_conn.query(
                            f"MATCH (n:{tn}) WHERE n.filePath = '{escaped_path}' "
                            "DETACH DELETE n"
                        )
                    )
                    deleted_nodes += count
            except Exception:
                continue

        with suppress(Exception):
            await _maybe_await(
                target_conn.query(
                    f"MATCH (e:{EMBEDDING_TABLE_NAME}) WHERE e.nodeId STARTS WITH "
                    f"'{escaped_path}' DELETE e"
                )
            )

        return {"deletedNodes": deleted_nodes}
    finally:
        if temp_conn is not None:
            with suppress(Exception):
                await _maybe_await(temp_conn.close())
        if temp_db is not None:
            with suppress(Exception):
                await _maybe_await(temp_db.close())


async def load_fts_extension() -> None:
    global fts_loaded
    if fts_loaded:
        return
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")
    try:
        await _maybe_await(conn.query("INSTALL fts"))
        await _maybe_await(conn.query("LOAD EXTENSION fts"))
        fts_loaded = True
    except Exception as err:
        msg = str(err)
        if any(
            token in msg
            for token in ("already loaded", "already installed", "already exists")
        ):
            fts_loaded = True
        else:
            logger.error("FTS extension load failed: %s", msg)


async def create_fts_index(
    table_name: str,
    index_name: str,
    properties: list[str],
    stemmer: str = "porter",
) -> None:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")

    await load_fts_extension()

    prop_list = ", ".join(f"'{p}'" for p in properties)
    query = (
        f"CALL CREATE_FTS_INDEX('{table_name}', '{index_name}', [{prop_list}], "
        f"stemmer := '{stemmer}')"
    )

    try:
        await _maybe_await(conn.query(query))
    except Exception as err:
        if "already exists" not in str(err):
            raise


async def query_fts(
    table_name: str,
    index_name: str,
    query: str,
    limit: int = 20,
    *,
    conjunctive: bool = False,
) -> list[dict[str, Any]]:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")

    escaped_query = query.replace("'", "''")
    cypher = (
        f"CALL QUERY_FTS_INDEX('{table_name}', '{index_name}', '{escaped_query}', "
        f"conjunctive := {str(conjunctive).lower()}) "
        "RETURN node, score ORDER BY score DESC "
        f"LIMIT {limit}"
    )

    try:
        query_result = await _maybe_await(conn.query(cypher))
        result = query_result[0] if isinstance(query_result, list) else query_result
        rows = await _get_all_rows(result)
        output: list[dict[str, Any]] = []
        for row in rows:
            node = _extract_row_value(row, "node", 0) or {}
            score_value = _extract_row_value(row, "score", 1) or 0
            if isinstance(node, dict):
                node_id = node.get("nodeId") or node.get("id") or ""
                name = node.get("name") or ""
                file_path = node.get("filePath") or ""
                merged = dict(node)
            else:
                node_id = getattr(node, "nodeId", None) or getattr(node, "id", "")
                name = getattr(node, "name", "")
                file_path = getattr(node, "filePath", "")
                merged = {}
            try:
                score = float(score_value)
            except Exception:
                score = 0.0
            merged.update(
                {
                    "nodeId": node_id,
                    "name": name,
                    "filePath": file_path,
                    "score": score,
                }
            )
            output.append(merged)
        return output
    except Exception as err:
        if "does not exist" in str(err):
            return []
        raise


async def drop_fts_index(table_name: str, index_name: str) -> None:
    if conn is None:
        raise RuntimeError("KuzuDB not initialized. Call initKuzu first.")

    with suppress(Exception):
        await _maybe_await(
            conn.query(f"CALL DROP_FTS_INDEX('{table_name}', '{index_name}')")
        )


initKuzu = init_kuzu  # noqa: N816
withKuzuDb = with_kuzu_db  # noqa: N816
loadGraphToKuzu = load_graph_to_kuzu  # noqa: N816
executeQuery = execute_query  # noqa: N816
executeWithReusedStatement = execute_with_reused_statement  # noqa: N816
getKuzuStats = get_kuzu_stats  # noqa: N816
loadCachedEmbeddings = load_cached_embeddings  # noqa: N816
upsertEmbeddings = upsert_embeddings  # noqa: N816
closeKuzu = close_kuzu  # noqa: N816
isKuzuReady = is_kuzu_ready  # noqa: N816
deleteNodesForFile = delete_nodes_for_file  # noqa: N816
loadFTSExtension = load_fts_extension  # noqa: N816
createFTSIndex = create_fts_index  # noqa: N816
queryFTS = query_fts  # noqa: N816
dropFTSIndex = drop_fts_index  # noqa: N816
currentDbPath = current_db_path  # noqa: N816
ftsLoaded = fts_loaded  # noqa: N816
