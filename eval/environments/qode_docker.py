"""
Qode Docker Environment for SWE-bench Evaluation

Extends mini-swe-agent's Docker environment to:
1. Install Qode (Node.js + npm + qode package)
2. Run `qode analyze` on the repository
3. Start the eval-server daemon (persistent HTTP server with warm KuzuDB)
4. Install standalone tool scripts in /usr/local/bin/ (works with subprocess.run)
5. Cache indexes per (repo, base_commit) to avoid re-indexing

IMPORTANT: mini-swe-agent runs every command with subprocess.run in a fresh subshell.
This means .bashrc is NOT sourced, exported functions are NOT available, and env vars
don't persist. The tool scripts must be standalone executables in $PATH.

Architecture:
  Agent bash cmd → /usr/local/bin/qode-query → curl localhost:4848/tool/query → eval-server → KuzuDB
  Fallback: → npx qode query (cold start, slower)

Tool call latency: ~50-100ms via eval-server, ~5-10s via CLI fallback.
"""

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

from minisweagent.environments.docker import DockerEnvironment

logger = logging.getLogger("qode_docker")

DEFAULT_CACHE_DIR = Path.home() / ".qode-eval-cache"
EVAL_SERVER_PORT = 4848

# Standalone tool scripts installed into /usr/local/bin/ inside the container.
# Each script calls the eval-server via curl, with a CLI fallback.
# These are standalone — no sourcing, no env inheritance needed.

TOOL_SCRIPT_QUERY = r"""#!/bin/bash
PORT="${QODE_EVAL_PORT:-__PORT__}"
query="$1"; task_ctx="${2:-}"; goal="${3:-}"
[ -z "$query" ] && echo "Usage: qode-query <query> [task_context] [goal]" && exit 1
args="{\"query\": \"$query\""
[ -n "$task_ctx" ] && args="$args, \"task_context\": \"$task_ctx\""
[ -n "$goal" ] && args="$args, \"goal\": \"$goal\""
args="$args}"
result=$(curl -sf -X POST "http://127.0.0.1:${PORT}/tool/query" -H "Content-Type: application/json" -d "$args" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$result" ]; then echo "$result"; exit 0; fi
cd /testbed && npx qode query "$query" 2>&1
"""

TOOL_SCRIPT_CONTEXT = r"""#!/bin/bash
PORT="${QODE_EVAL_PORT:-__PORT__}"
name="$1"; file_path="${2:-}"
[ -z "$name" ] && echo "Usage: qode-context <symbol_name> [file_path]" && exit 1
args="{\"name\": \"$name\""
[ -n "$file_path" ] && args="$args, \"file_path\": \"$file_path\""
args="$args}"
result=$(curl -sf -X POST "http://127.0.0.1:${PORT}/tool/context" -H "Content-Type: application/json" -d "$args" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$result" ]; then echo "$result"; exit 0; fi
cd /testbed && npx qode context "$name" 2>&1
"""

TOOL_SCRIPT_IMPACT = r"""#!/bin/bash
PORT="${QODE_EVAL_PORT:-__PORT__}"
target="$1"; direction="${2:-upstream}"
[ -z "$target" ] && echo "Usage: qode-impact <symbol_name> [upstream|downstream]" && exit 1
result=$(curl -sf -X POST "http://127.0.0.1:${PORT}/tool/impact" -H "Content-Type: application/json" -d "{\"target\": \"$target\", \"direction\": \"$direction\"}" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$result" ]; then echo "$result"; exit 0; fi
cd /testbed && npx qode impact "$target" --direction "$direction" 2>&1
"""

TOOL_SCRIPT_CYPHER = r"""#!/bin/bash
PORT="${QODE_EVAL_PORT:-__PORT__}"
query="$1"
[ -z "$query" ] && echo "Usage: qode-cypher <cypher_query>" && exit 1
result=$(curl -sf -X POST "http://127.0.0.1:${PORT}/tool/cypher" -H "Content-Type: application/json" -d "{\"query\": \"$query\"}" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$result" ]; then echo "$result"; exit 0; fi
cd /testbed && npx qode cypher "$query" 2>&1
"""

TOOL_SCRIPT_AUGMENT = r"""#!/bin/bash
cd /testbed && npx qode augment "$1" 2>&1 || true
"""

TOOL_SCRIPT_OVERVIEW = r"""#!/bin/bash
PORT="${QODE_EVAL_PORT:-__PORT__}"
echo "=== Code Knowledge Graph Overview ==="
result=$(curl -sf -X POST "http://127.0.0.1:${PORT}/tool/list_repos" -H "Content-Type: application/json" -d "{}" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$result" ]; then echo "$result"; exit 0; fi
cd /testbed && npx qode list 2>&1
"""


class QodeDockerEnvironment(DockerEnvironment):
    """
    Docker environment with Qode pre-installed, indexed, and eval-server running.

    Setup flow:
    1. Start Docker container (base SWE-bench image)
    2. Install Node.js + qode inside the container
    3. Run `qode analyze` (or restore from cache)
    4. Start `qode eval-server` daemon (keeps KuzuDB warm)
    5. Install standalone tool scripts in /usr/local/bin/
    6. Agent runs with near-instant Qode tool calls
    """

    def __init__(
        self,
        *,
        enable_qode: bool = True,
        cache_dir: str | Path | None = None,
        skip_embeddings: bool = True,
        qode_timeout: int = 120,
        eval_server_port: int = EVAL_SERVER_PORT,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.enable_qode = enable_qode
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.skip_embeddings = skip_embeddings
        self.qode_timeout = qode_timeout
        self.eval_server_port = eval_server_port
        self.index_time: float = 0.0
        self._qode_ready = False

    def start(self) -> dict:
        """Start the container and set up Qode."""
        result = super().start()

        if self.enable_qode:
            try:
                self._setup_qode()
            except Exception as e:
                logger.warning(f"Qode setup failed, continuing without it: {e}")
                self._qode_ready = False

        return result

    def _setup_qode(self):
        """Install and configure Qode in the container."""
        start = time.time()

        self._ensure_nodejs()
        self._install_qode()
        self._index_repository()
        self._start_eval_server()
        self._install_tools()

        self.index_time = time.time() - start
        self._qode_ready = True
        logger.info(f"Qode setup completed in {self.index_time:.1f}s")

    def _ensure_nodejs(self):
        """Ensure Node.js >= 18 is available in the container."""
        check = self.execute(
            {"command": "node --version 2>/dev/null || echo 'NOT_FOUND'"}
        )
        output = check.get("output", "").strip()

        if "NOT_FOUND" in output:
            logger.info("Installing Node.js in container...")
            install_cmds = [
                "apt-get update -qq",
                "apt-get install -y -qq curl ca-certificates",
                "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
                "apt-get install -y -qq nodejs",
            ]
            for cmd in install_cmds:
                result = self.execute({"command": cmd, "timeout": 60})
                if result.get("returncode", 1) != 0:
                    raise RuntimeError(
                        f"Failed to install Node.js: {result.get('output', '')}"
                    )
        else:
            logger.info(f"Node.js already available: {output}")

    def _install_qode(self):
        """Install the qode npm package globally."""
        check = self.execute(
            {"command": "npx qode --version 2>/dev/null || echo 'NOT_FOUND'"}
        )
        if "NOT_FOUND" in check.get("output", ""):
            logger.info("Installing qode...")
            result = self.execute(
                {
                    "command": "npm install -g qode",
                    "timeout": 60,
                }
            )
            if result.get("returncode", 1) != 0:
                raise RuntimeError(
                    f"Failed to install qode: {result.get('output', '')}"
                )

    def _index_repository(self):
        """Run qode analyze on the repo, using cache if available."""
        repo_info = self._get_repo_info()
        cache_key = self._make_cache_key(repo_info)
        cache_path = self.cache_dir / cache_key

        if cache_path.exists():
            logger.info(f"Restoring Qode index from cache: {cache_key}")
            self._restore_cache(cache_path)
            return

        logger.info("Running qode analyze...")
        skip_flag = "--skip-embeddings" if self.skip_embeddings else ""
        result = self.execute(
            {
                "command": f"cd /testbed && npx qode analyze . {skip_flag} 2>&1",
                "timeout": self.qode_timeout,
            }
        )

        if result.get("returncode", 1) != 0:
            output = result.get("output", "")
            if "error" in output.lower() and "indexed" not in output.lower():
                raise RuntimeError(f"qode analyze failed: {output[-500:]}")

        self._save_cache(cache_path, repo_info)

    def _start_eval_server(self):
        """Start the Qode eval-server daemon in the background."""
        logger.info(f"Starting eval-server on port {self.eval_server_port}...")

        self.execute(
            {
                "command": (
                    f"nohup npx qode eval-server --port {self.eval_server_port} "
                    f"--idle-timeout 600 "
                    f"> /tmp/qode-eval-server.log 2>&1 &"
                ),
                "timeout": 5,
            }
        )

        # Wait for the server to be ready (up to 15s for KuzuDB init)
        for i in range(30):
            time.sleep(0.5)
            health = self.execute(
                {
                    "command": f"curl -sf http://127.0.0.1:{self.eval_server_port}/health 2>/dev/null || echo 'NOT_READY'",
                    "timeout": 3,
                }
            )
            output = health.get("output", "").strip()
            if "NOT_READY" not in output and "ok" in output:
                logger.info(f"Eval-server ready after {(i + 1) * 0.5:.1f}s")
                return

        log_output = self.execute(
            {
                "command": "cat /tmp/qode-eval-server.log 2>/dev/null | tail -20",
            }
        )
        logger.warning(
            f"Eval-server didn't become ready in 15s. "
            f"Tools will fall back to direct CLI.\n"
            f"Server log: {log_output.get('output', 'N/A')}"
        )

    def _install_tools(self):
        """
        Install standalone Qode tool scripts in /usr/local/bin/.

        Each script is a self-contained bash script that:
        1. Calls the eval-server via curl (fast path, ~100ms)
        2. Falls back to direct CLI if eval-server is unavailable

        These are standalone executables — no sourcing, env inheritance, or .bashrc
        needed. This is critical because mini-swe-agent runs every command via
        subprocess.run in a fresh subshell.

        Uses heredocs with quoted delimiter to avoid all quoting/escaping issues.
        """
        port = str(self.eval_server_port)

        tools = {
            "qode-query": TOOL_SCRIPT_QUERY,
            "qode-context": TOOL_SCRIPT_CONTEXT,
            "qode-impact": TOOL_SCRIPT_IMPACT,
            "qode-cypher": TOOL_SCRIPT_CYPHER,
            "qode-augment": TOOL_SCRIPT_AUGMENT,
            "qode-overview": TOOL_SCRIPT_OVERVIEW,
        }

        for name, script in tools.items():
            script_content = script.replace("__PORT__", port).strip()
            # Use heredoc with quoted delimiter — prevents all variable expansion and quoting issues
            self.execute(
                {
                    "command": f"cat << 'QODE_SCRIPT_EOF' > /usr/local/bin/{name}\n{script_content}\nQODE_SCRIPT_EOF\nchmod +x /usr/local/bin/{name}",
                    "timeout": 5,
                }
            )

        logger.info(f"Installed {len(tools)} Qode tool scripts in /usr/local/bin/")

    def _get_repo_info(self) -> dict:
        """Get repository identity info from the container."""
        repo_result = self.execute(
            {
                "command": "cd /testbed && basename $(git remote get-url origin 2>/dev/null || basename $(pwd)) .git"
            }
        )
        commit_result = self.execute(
            {"command": "cd /testbed && git rev-parse HEAD 2>/dev/null || echo unknown"}
        )

        return {
            "repo": repo_result.get("output", "unknown").strip(),
            "commit": commit_result.get("output", "unknown").strip(),
        }

    @staticmethod
    def _make_cache_key(repo_info: dict) -> str:
        """Create a deterministic cache key from repo info."""
        content = f"{repo_info['repo']}:{repo_info['commit']}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _save_cache(self, cache_path: Path, repo_info: dict):
        """Save the Qode index to the host cache directory."""
        try:
            cache_path.mkdir(parents=True, exist_ok=True)

            find_result = self.execute(
                {
                    "command": "find /root/.qode -name 'kuzu' -type d 2>/dev/null | head -1"
                }
            )
            qode_dir = find_result.get("output", "").strip()

            if qode_dir:
                parent = str(Path(qode_dir).parent)
                self.execute(
                    {
                        "command": f"cd {parent} && tar czf /tmp/qode-cache.tar.gz .",
                        "timeout": 30,
                    }
                )

                container_id = getattr(self, "_container_id", None) or getattr(
                    self, "container_id", None
                )
                if container_id:
                    import subprocess as sp

                    sp.run(
                        [
                            "docker",
                            "cp",
                            f"{container_id}:/tmp/qode-cache.tar.gz",
                            str(cache_path / "index.tar.gz"),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    (cache_path / "metadata.json").write_text(
                        json.dumps(repo_info, indent=2)
                    )
                    logger.info(f"Cached Qode index: {cache_path}")

        except Exception as e:
            logger.warning(f"Failed to cache Qode index: {e}")
            if cache_path.exists():
                shutil.rmtree(cache_path, ignore_errors=True)

    def _restore_cache(self, cache_path: Path):
        """Restore a cached Qode index into the container."""
        try:
            cache_tarball = cache_path / "index.tar.gz"
            if not cache_tarball.exists():
                logger.warning("Cache tarball not found, re-indexing")
                self._index_repository()
                return

            container_id = getattr(self, "_container_id", None) or getattr(
                self, "container_id", None
            )
            if container_id:
                import subprocess as sp

                self.execute({"command": "mkdir -p /root/.qode"})

                storage_result = self.execute(
                    {
                        "command": "npx qode list 2>/dev/null | grep -o '/root/.qode/[^ ]*' | head -1 || echo '/root/.qode/repos/default'"
                    }
                )
                storage_path = (
                    storage_result.get("output", "").strip()
                    or "/root/.qode/repos/default"
                )
                self.execute({"command": f"mkdir -p {storage_path}"})

                sp.run(
                    [
                        "docker",
                        "cp",
                        str(cache_tarball),
                        f"{container_id}:/tmp/qode-cache.tar.gz",
                    ],
                    check=True,
                    capture_output=True,
                )
                self.execute(
                    {
                        "command": f"cd {storage_path} && tar xzf /tmp/qode-cache.tar.gz",
                        "timeout": 30,
                    }
                )
                logger.info("Qode index restored from cache")

        except Exception as e:
            logger.warning(f"Failed to restore cache, re-indexing: {e}")
            self._index_repository()

    def stop(self) -> dict:
        """Stop the container, shutting down eval-server first."""
        if self._qode_ready:
            try:
                self.execute(
                    {
                        "command": f"curl -sf -X POST http://127.0.0.1:{self.eval_server_port}/shutdown 2>/dev/null || true",
                        "timeout": 3,
                    }
                )
            except Exception:
                pass

        return super().stop()

    def get_template_vars(self) -> dict:
        """Add Qode-specific template variables."""
        base_vars = super().get_template_vars()
        base_vars["qode_ready"] = self._qode_ready
        base_vars["qode_index_time"] = self.index_time
        return base_vars

    def serialize(self) -> dict:
        """Include Qode environment info in serialization."""
        base = super().serialize()
        base.setdefault("info", {})["qode_env"] = {
            "enabled": self.enable_qode,
            "ready": self._qode_ready,
            "index_time_seconds": round(self.index_time, 2),
            "skip_embeddings": self.skip_embeddings,
            "eval_server_port": self.eval_server_port,
        }
        return base
