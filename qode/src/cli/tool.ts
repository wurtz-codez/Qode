/**
 * Direct CLI Tool Commands
 *
 * Exposes Qode tools (query, context, impact, cypher) as direct CLI commands.
 * Bypasses MCP entirely — invokes LocalBackend directly for minimal overhead.
 *
 * Usage:
 *   qode query "authentication flow"
 *   qode context --name "validateUser"
 *   qode impact --target "AuthService" --direction upstream
 *   qode cypher "MATCH (n:Function) RETURN n.name LIMIT 10"
 *
 * Note: Output goes to stderr because KuzuDB's native module captures stdout
 * at the OS level during init. This is consistent with augment.ts.
 */

import { LocalBackend } from '../mcp/local/local-backend.js';

let _backend: LocalBackend | null = null;

async function getBackend(): Promise<LocalBackend> {
  if (_backend) return _backend;
  _backend = new LocalBackend();
  const ok = await _backend.init();
  if (!ok) {
    console.error('Qode: No indexed repositories found. Run: qode analyze');
    process.exit(1);
  }
  return _backend;
}

function output(data: any): void {
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  // stderr because KuzuDB captures stdout at OS level
  process.stderr.write(text + '\n');
}

export async function queryCommand(queryText: string, options?: {
  repo?: string;
  context?: string;
  goal?: string;
  limit?: string;
  content?: boolean;
}): Promise<void> {
  if (!queryText?.trim()) {
    console.error('Usage: qode query <search_query>');
    process.exit(1);
  }

  const backend = await getBackend();
  const result = await backend.callTool('query', {
    query: queryText,
    task_context: options?.context,
    goal: options?.goal,
    limit: options?.limit ? parseInt(options.limit) : undefined,
    include_content: options?.content ?? false,
    repo: options?.repo,
  });
  output(result);
}

export async function contextCommand(name: string, options?: {
  repo?: string;
  file?: string;
  uid?: string;
  content?: boolean;
}): Promise<void> {
  if (!name?.trim() && !options?.uid) {
    console.error('Usage: qode context <symbol_name> [--uid <uid>] [--file <path>]');
    process.exit(1);
  }

  const backend = await getBackend();
  const result = await backend.callTool('context', {
    name: name || undefined,
    uid: options?.uid,
    file_path: options?.file,
    include_content: options?.content ?? false,
    repo: options?.repo,
  });
  output(result);
}

export async function impactCommand(target: string, options?: {
  direction?: string;
  repo?: string;
  depth?: string;
  includeTests?: boolean;
}): Promise<void> {
  if (!target?.trim()) {
    console.error('Usage: qode impact <symbol_name> [--direction upstream|downstream]');
    process.exit(1);
  }

  const backend = await getBackend();
  const result = await backend.callTool('impact', {
    target,
    direction: options?.direction || 'upstream',
    maxDepth: options?.depth ? parseInt(options.depth) : undefined,
    includeTests: options?.includeTests ?? false,
    repo: options?.repo,
  });
  output(result);
}

export async function cypherCommand(query: string, options?: {
  repo?: string;
}): Promise<void> {
  if (!query?.trim()) {
    console.error('Usage: qode cypher <cypher_query>');
    process.exit(1);
  }

  const backend = await getBackend();
  const result = await backend.callTool('cypher', {
    query,
    repo: options?.repo,
  });
  output(result);
}
