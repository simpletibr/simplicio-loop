/*
 * Reference Cloudflare Worker template for LLM Project Mapper install telemetry.
 *
 * Deploy with:
 *   wrangler deploy
 *
 * Bindings expected (configure in wrangler.toml):
 *   - TELEMETRY (KV namespace) — daily counters, retained 90 days.
 *   - ANALYTICS (Analytics Engine dataset, optional) — high-cardinality events.
 *
 * The worker accepts only POST + JSON, validates the payload shape, rejects
 * anything that smells like PII, then aggregates in KV.
 *
 * NOT shipped as an active worker in this repo — adopters bring their own
 * Cloudflare account and configure LLM_PROJECT_MAPPER_TELEMETRY_URL on dev
 * machines to point here. See docs/PRIVACY.md for the data contract.
 */

const ALLOWED_FIELDS = new Set([
  'starter_version',
  'stack',
  'project_mode',
  'preset',
  'node_version',
  'os',
  'arch',
  'cli_runtime',
  'timestamp',
]);

function sanitize(obj) {
  const out = {};
  for (const key of ALLOWED_FIELDS) {
    if (obj[key] === null || obj[key] === undefined) continue;
    const value = String(obj[key]).slice(0, 64);
    if (/[\/\\]/.test(value)) return null; // path-like → reject (privacy)
    out[key] = value;
  }
  return out;
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST',
          'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400',
        },
      });
    }
    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }
    if (!/^application\/json/.test(request.headers.get('content-type') || '')) {
      return new Response('Unsupported media type', { status: 415 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response('Invalid JSON', { status: 400 });
    }

    const clean = sanitize(body);
    if (!clean) {
      return new Response('Rejected payload (suspected PII)', { status: 422 });
    }

    const day = new Date().toISOString().slice(0, 10);
    const key = `install:${day}:${clean.starter_version || 'unknown'}:${clean.stack || 'unknown'}`;

    if (env.TELEMETRY) {
      const current = parseInt((await env.TELEMETRY.get(key)) || '0', 10);
      await env.TELEMETRY.put(key, String(current + 1), { expirationTtl: 90 * 24 * 60 * 60 });
    }
    if (env.ANALYTICS) {
      env.ANALYTICS.writeDataPoint({
        indexes: [clean.starter_version || 'unknown'],
        blobs: [clean.stack, clean.project_mode, clean.preset || '', clean.os, clean.arch],
        doubles: [1],
      });
    }

    return new Response(null, { status: 204 });
  },
};
