'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const CONTRACT_SCHEMA = 'simplicio.context-graph-contract/v1';
const GRAPH_SCHEMA = 'simplicio.context-graph/v1';

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function digest(value) {
  return crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
}

function buildPublicContract(graph, repositoryId, generation) {
  if (!graph || graph.schema !== GRAPH_SCHEMA) throw new Error('graph_schema_invalid');
  const nodes = (graph.nodes || [])
    .filter((node) => node && node.id)
    .map((node) => ({ id: String(node.id), scale: String(node.scale || '') }))
    .sort((a, b) => a.id.localeCompare(b.id));
  const relations = (graph.edges || [])
    .filter((edge) => edge && edge.id)
    .map((edge) => ({ id: String(edge.id), kind: String(edge.kind || ''), source: String(edge.source || ''), target: String(edge.target || '') }))
    .sort((a, b) => a.id.localeCompare(b.id));
  const body = {
    schema: CONTRACT_SCHEMA,
    version: 1,
    repository_id: repositoryId,
    generation,
    stable_ids: { nodes: nodes.map((node) => node.id), edges: relations.map((edge) => edge.id) },
    nodes,
    relations,
  };
  return { ...body, digest: digest(body) };
}

function run(fixturePath) {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const nodeContracts = fixture.cases.map((item) => buildPublicContract(item.graph, item.repository_id, item.generation));
  const pythonScript = [
    'import json, sys',
    'from simplicio_mapper.context_graph_contract import build_public_contract',
    'fixture=json.load(open(sys.argv[1], encoding="utf-8"))',
    'print(json.dumps([build_public_contract(item["graph"], repository_id=item["repository_id"], generation=item["generation"]) for item in fixture["cases"]], sort_keys=True))',
  ].join('\n');
  const python = spawnSync(process.env.PYTHON || 'python3', ['-c', pythonScript, fixturePath], { encoding: 'utf8', cwd: path.resolve(__dirname, '..') });
  const pythonContracts = python.status === 0 ? JSON.parse(python.stdout) : [];
  const divergences = [];
  nodeContracts.forEach((item, index) => {
    if (canonical(item) !== canonical(pythonContracts[index])) {
      divergences.push({ case: fixture.cases[index].name, channels: ['node', 'python'], reason: 'public_projection_mismatch', versions: { node: process.version, python: process.env.PYTHON || 'python3' } });
    }
  });
  const rustProbe = spawnSync(process.env.PYTHON || 'python3', ['-c', 'import simplicio_mapper_rs; print("available")'], { encoding: 'utf8' });
  const rustAvailable = rustProbe.status === 0;
  if (rustAvailable) {
    const rustScript = [
      'import json, sys',
      'from simplicio_mapper_rs import schema_registry_sha256',
      'contracts=json.loads(sys.argv[1])',
      'print(json.dumps([schema_registry_sha256(json.dumps({k:v for k,v in item.items() if k != "digest"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) for item in contracts], sort_keys=True))',
    ].join('\n');
    const rust = spawnSync(process.env.PYTHON || 'python3', ['-c', rustScript, JSON.stringify(nodeContracts)], { encoding: 'utf8' });
    if (rust.status !== 0) {
      divergences.push({ case: '*', channels: ['rust'], reason: 'rust_probe_failed', versions: { rust: 'optional' } });
    } else {
      const rustHashes = JSON.parse(rust.stdout);
      nodeContracts.forEach((item, index) => {
        if (rustHashes[index] !== item.digest) {
          divergences.push({ case: fixture.cases[index].name, channels: ['rust', 'node'], reason: 'public_digest_mismatch', versions: { rust: 'optional', node: process.version } });
        }
      });
    }
  }
  const rustStatus = rustAvailable
    ? (divergences.some((item) => item.channels.includes('rust')) ? 'fail' : 'pass')
    : 'skipped';
  return {
    schema: 'simplicio.context-graph-parity/v1',
    fixture: path.relative(path.resolve(__dirname, '..'), fixturePath).replaceAll(path.sep, '/'),
    channels: {
      python: { status: python.status === 0 && divergences.every((item) => !item.channels.includes('python')) ? 'pass' : 'fail', version: 'simplicio-mapper' },
      node: { status: divergences.every((item) => !item.channels.includes('node')) ? 'pass' : 'fail', version: process.version },
      rust: { status: rustStatus, version: rustAvailable ? 'optional' : null, reason: rustAvailable ? null : 'optional accelerator unavailable' },
    },
    cases: fixture.cases.map((item, index) => ({ name: item.name, behavior: item.behavior, digest: nodeContracts[index].digest })),
    divergences,
  };
}

if (require.main === module) {
  try {
    const fixture = process.argv[2] || 'contracts/context-graph/v1/fixtures/parity.json';
    process.stdout.write(`${JSON.stringify(run(path.resolve(fixture)))}\n`);
    process.exitCode = 0;
  } catch (error) {
    console.error(error.message || error);
    process.exitCode = 1;
  }
}

module.exports = { buildPublicContract, canonical, digest, run };
