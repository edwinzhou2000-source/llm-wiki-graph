#!/usr/bin/env bun
/**
 * gbrain-sidecar — persistent HTTP wrapper that eliminates the 1.2s bun startup
 * overhead per gbrain call. Initializes PGLite engine once, then serves
 * search/query/get over JSON HTTP endpoints.
 *
 * Usage:
 *   bun run gbrain-sidecar.ts
 *
 * The Python server.py replaces subprocess calls with HTTP to localhost:9876.
 */

const GBRAIN_SRC = '/Users/edwin.zhou/gbrain/src';

// ── Env (must be set before imports that might read process.env) ──
process.env.DATABASE_URL = '';
process.env.GBRAIN_HOME = '/Users/edwin.zhou/.gbrain-llm-wiki';

// ── Type stubs (avoids importing full TS types from gbrain) ──
interface BrainEngine {
  getPage(slug: string, opts?: Record<string, unknown>): Promise<Page | null>;
  searchKeyword(query: string, opts?: Record<string, unknown>): Promise<SearchResult[]>;
}

interface Page {
  slug: string;
  type: string;
  title: string;
  frontmatter: Record<string, unknown> | null;
  compiled_truth: string;
  timeline: string;
  tags: string[];
}

interface SearchResult {
  score: number;
  slug: string;
  page_id: number;
  chunk_text: string;
  stale?: boolean;
  [key: string]: unknown;
}

// ── Logging ──
const LOG_PREFIX = '[sidecar]';

function log(msg: string) {
  const ts = new Date().toISOString().slice(11, 19);
  process.stderr.write(`${ts} ${LOG_PREFIX} ${msg}\n`);
}

// ── PGLite serialization mutex ──
// PGLite (SQLite) serializes concurrent writers. Queue all engine calls.
let _queue: Promise<void> = Promise.resolve();

function serialized<T>(fn: () => Promise<T>, timeoutMs = 30000): Promise<T> {
  const prev = _queue;
  let resolve: () => void;
  const next = new Promise<void>(r => { resolve = r; });
  _queue = next;

  return prev.then(async () => {
    const start = Date.now();
    try {
      const result = fn();
      const timed = new Promise<T>((_, reject) =>
        setTimeout(() => reject(new Error(`Operation timed out after ${timeoutMs}ms`)), timeoutMs)
      );
      return await Promise.race([result, timed]) as T;
    } catch (err) {
      log(`operation error (${Date.now() - start}ms): ${(err as Error).message}`);
      throw err;
    } finally {
      resolve!();
    }
  });
}

// ── Init chain ──
async function bootstrap(): Promise<BrainEngine> {
  log('loading config...');
  const { loadConfig, toEngineConfig } = await import(`${GBRAIN_SRC}/core/config.ts`);

  const config = loadConfig();
  if (!config) {
    throw new Error('No brain configured. Check GBRAIN_HOME.');
  }
  log(`engine=${config.engine} db_path=${config.database_path || '(none)'}`);

  // Step 1: Configure AI gateway (needed for embedding dimensions)
  log('configuring AI gateway...');
  const { buildGatewayConfig } = await import(`${GBRAIN_SRC}/core/ai/build-gateway-config.ts`);
  const { configureGateway } = await import(`${GBRAIN_SRC}/core/ai/gateway.ts`);
  configureGateway(buildGatewayConfig(config));

  // Step 2: Create engine (heavy: loads PGLite WASM)
  log('creating engine (loading PGLite WASM)...');
  const startEngine = Date.now();
  const { createEngine } = await import(`${GBRAIN_SRC}/core/engine-factory.ts`);
  const engine = await createEngine(toEngineConfig(config));
  log(`engine created in ${Date.now() - startEngine}ms`);

  // Step 3: Connect with retry
  log('connecting to database...');
  const { connectWithRetry } = await import(`${GBRAIN_SRC}/core/db.ts`);
  await connectWithRetry(engine, toEngineConfig(config), { noRetry: true });
  log('connected.');

  // Step 4: Run pending migrations
  log('checking migrations...');
  const { tryRunPendingMigrations } = await import(`${GBRAIN_SRC}/core/migrate.ts`);
  const migResult = await tryRunPendingMigrations(engine);
  log(`migrations: ${migResult.status}`);

  // Step 5: Load config (merges DB-plane flags like embedding_multimodal)
  const { loadConfigWithEngine } = await import(`${GBRAIN_SRC}/core/config.ts`);
  const merged = await loadConfigWithEngine(engine, config);
  if (merged?.embedding_multimodal !== undefined) {
    process.env.GBRAIN_EMBEDDING_MULTIMODAL = String(merged.embedding_multimodal);
  }

  log('bootstrap complete.');
  return engine;
}

// ── Cached module imports (lazy-loaded once) ──
let _serializeMarkdown: any = null;

async function getSerializeMarkdown() {
  if (!_serializeMarkdown) {
    const mod = await import(`${GBRAIN_SRC}/core/markdown.ts`);
    _serializeMarkdown = mod.serializeMarkdown;
  }
  return _serializeMarkdown;
}

// ── Search helpers ──
async function doSearch(
  engine: BrainEngine,
  query: string,
  limit: number,
): Promise<Array<{ score: number; slug: string; content: string }>> {
  // Use searchKeyword for keyword-only (fast, no embedding API call)
  // For v2 we need the cheap-hybrid path via hybridSearchCached
  const { hybridSearchCached } = await import(`${GBRAIN_SRC}/core/search/hybrid.ts`);

  const results: SearchResult[] = await serialized(() =>
    hybridSearchCached(engine, query, {
      limit,
      expansion: false,
      // no source scope — search all sources
    }),
  ) as SearchResult[];

  return results.map((r: SearchResult) => ({
    score: r.score,
    slug: r.slug,
    content: (r.chunk_text || '').slice(0, 200),
  }));
}

async function doQuery(
  engine: BrainEngine,
  query: string,
  limit: number,
): Promise<Array<{ score: number; slug: string; content: string }>> {
  // Same as search for our purposes — the distinction (expansion) is handled by the CLI
  const { hybridSearchCached } = await import(`${GBRAIN_SRC}/core/search/hybrid.ts`);

  const results: SearchResult[] = await serialized(() =>
    hybridSearchCached(engine, query, {
      limit,
      expansion: false,
    }),
  ) as SearchResult[];

  return results.map((r: SearchResult) => ({
    score: r.score,
    slug: r.slug,
    content: (r.chunk_text || '').slice(0, 200),
  }));
}

async function doGet(
  engine: BrainEngine,
  slug: string,
): Promise<string | null> {
  const page = await serialized(() => engine.getPage(slug));
  if (!page) return null;

  const serializeMarkdown = await getSerializeMarkdown();

  return serializeMarkdown(
    page.frontmatter || {},
    page.compiled_truth || '',
    page.timeline || '',
    {
      type: page.type,
      title: page.title,
      tags: page.tags || [],
    },
  );
}

// ── HTTP Server ──
async function main() {
  const engine = await bootstrap();

  const server = Bun.serve({
    port: 9876,
    hostname: '127.0.0.1',
    fetch(req: Request): Promise<Response> | Response {
      const url = new URL(req.url);

      // GET /health
      if (url.pathname === '/health') {
        return Response.json({ status: 'ok', uptime: process.uptime() });
      }

      // POST /search  { query, limit? }
      if (url.pathname === '/search' && req.method === 'POST') {
        return handleSearch(req, engine);
      }

      // POST /query  { query, limit? }
      if (url.pathname === '/query' && req.method === 'POST') {
        return handleQuery(req, engine);
      }

      // GET /get/:slug
      if (url.pathname.startsWith('/get/')) {
        return handleGet(url, engine);
      }

      return new Response('Not found', { status: 404 });
    },

    error(err: Error): Response {
      log(`HTTP error: ${err.message}`);
      return Response.json({ error: err.message }, { status: 500 });
    },
  });

  log(`listening on http://127.0.0.1:${server.port} (sidecar ready)`);

  // Graceful shutdown with PGLite lock cleanup
  const cleanup = () => {
    log('shutting down, cleaning locks...');
    server.stop();
    // Clean PGLite lock files so next start doesn't block
    try {
      const fs = require('node:fs') as typeof import('node:fs');
      const lockDir = '/Users/edwin.zhou/.gbrain-llm-wiki/.gbrain/brain.pglite/.gbrain-lock';
      const pidFile = '/Users/edwin.zhou/.gbrain-llm-wiki/.gbrain/brain.pglite/postmaster.pid';
      if (fs.existsSync(lockDir)) fs.rmSync(lockDir, { recursive: true, force: true });
      if (fs.existsSync(pidFile)) fs.unlinkSync(pidFile);
    } catch {}
    process.exit(0);
  };
  
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
  process.on('uncaughtException', (err) => {
    log(`UNCAUGHT: ${err.message}`);
    cleanup();
  });
}

// ── Request handlers ──
async function handleSearch(req: Request, engine: BrainEngine): Promise<Response> {
  let body: { query?: string; limit?: number };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const { query, limit = 10 } = body;
  if (!query || typeof query !== 'string') {
    return Response.json({ error: 'Missing query' }, { status: 400 });
  }

  const start = Date.now();
  try {
    const results = await doSearch(engine, query, limit);
    log(`search "${query.slice(0, 40)}" → ${results.length} results in ${Date.now() - start}ms`);
    return Response.json(results);
  } catch (err) {
    log(`search error: ${(err as Error).message}`);
    return Response.json({ error: (err as Error).message, results: [] }, { status: 200 });
  }
}

async function handleQuery(req: Request, engine: BrainEngine): Promise<Response> {
  let body: { query?: string; limit?: number };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const { query, limit = 10 } = body;
  if (!query || typeof query !== 'string') {
    return Response.json({ error: 'Missing query' }, { status: 400 });
  }

  const start = Date.now();
  try {
    const results = await doQuery(engine, query, limit);
    log(`query "${query.slice(0, 40)}" → ${results.length} results in ${Date.now() - start}ms`);
    return Response.json(results);
  } catch (err) {
    log(`query error: ${(err as Error).message}`);
    return Response.json({ error: (err as Error).message, results: [] }, { status: 200 });
  }
}

async function handleGet(url: URL, engine: BrainEngine): Promise<Response> {
  const slug = decodeURIComponent(url.pathname.slice(5));
  if (!slug) {
    return Response.json({ error: 'Missing slug' }, { status: 400 });
  }

  const start = Date.now();
  try {
    const content = await doGet(engine, slug);
    if (content === null) {
      return new Response('Not found', { status: 404 });
    }
    log(`get "${slug}" → ${content.length} chars in ${Date.now() - start}ms`);
    return new Response(content, {
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  } catch (err) {
    log(`get error: ${(err as Error).message}`);
    return new Response((err as Error).message, { status: 500 });
  }
}

// ── Entry ──
main().catch((err: Error) => {
  log(`FATAL: ${err.message}`);
  if (err.stack) log(err.stack);
  process.exit(1);
});
