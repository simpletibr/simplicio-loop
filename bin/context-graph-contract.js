'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const CONTRACT_SCHEMA = 'simplicio.context-graph-contract/v1';
const GRAPH_SCHEMA = 'simplicio.context-graph/v1';
const CONTRACT_VERSION = 1;
const SCHEMA_PATTERN = /^simplicio[.]context-graph-contract\/v([1-9][0-9]*)(?:[.][0-9]+)*$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;

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

function diagnostic(reason, pathValue, message, details = {}) {
  return { valid: false, reason, path: pathValue, message, ...details };
}

function validatePublicContract(contract) {
  if (!contract || typeof contract !== 'object' || Array.isArray(contract)) {
    return diagnostic('contract_not_object', '$', 'ContextGraph contract must be an object');
  }

  const schema = contract.schema;
  const match = typeof schema === 'string' ? SCHEMA_PATTERN.exec(schema) : null;
  if (!match) {
    return diagnostic(
      'schema_invalid',
      '$.schema',
      `schema must match ${CONTRACT_SCHEMA} or a compatible minor version`,
      { received: schema, supported: [CONTRACT_SCHEMA] },
    );
  }
  const major = Number(match[1]);
  if (major !== CONTRACT_VERSION) {
    return diagnostic(
      'schema_major_unsupported',
      '$.schema',
      `schema major v${major} is unsupported; supported major is v${CONTRACT_VERSION}`,
      { received: schema, supported: [CONTRACT_SCHEMA] },
    );
  }

  if (!Number.isInteger(contract.version) || contract.version !== CONTRACT_VERSION) {
    return diagnostic(
      'version_unsupported',
      '$.version',
      `version must be integer ${CONTRACT_VERSION} for schema major v${CONTRACT_VERSION}`,
    );
  }
  if (typeof contract.repository_id !== 'string' || !contract.repository_id) {
    return diagnostic('repository_identity_missing', '$.repository_id', 'repository_id must be a non-empty string');
  }
  if (typeof contract.generation !== 'string' || !contract.generation) {
    return diagnostic('generation_missing', '$.generation', 'generation must be a non-empty string');
  }

  const stableIds = contract.stable_ids;
  if (!stableIds || typeof stableIds !== 'object' || Array.isArray(stableIds)) {
    return diagnostic('stable_ids_invalid', '$.stable_ids', 'stable_ids must be an object');
  }
  for (const key of ['nodes', 'edges']) {
    if (!Array.isArray(stableIds[key]) || stableIds[key].some((value) => typeof value !== 'string')) {
      return diagnostic('stable_ids_invalid', `$.stable_ids.${key}`, `stable_ids.${key} must be an array of strings`);
    }
  }

  if (!Array.isArray(contract.nodes)) {
    return diagnostic('nodes_invalid', '$.nodes', 'nodes must be an array');
  }
  const nodeIds = [];
  for (let index = 0; index < contract.nodes.length; index += 1) {
    const node = contract.nodes[index];
    const itemPath = `$.nodes[${index}]`;
    if (!node || typeof node !== 'object' || Array.isArray(node)) {
      return diagnostic('node_invalid', itemPath, 'node must be an object');
    }
    if (typeof node.id !== 'string' || !node.id) {
      return diagnostic('node_id_invalid', `${itemPath}.id`, 'node id must be a non-empty string');
    }
    if (nodeIds.includes(node.id)) {
      return diagnostic('node_id_duplicate', `${itemPath}.id`, `duplicate node id: ${node.id}`);
    }
    if (typeof node.scale !== 'string' || !node.scale) {
      return diagnostic('node_scale_invalid', `${itemPath}.scale`, 'node scale must be a string');
    }
    nodeIds.push(node.id);
  }

  if (!Array.isArray(contract.relations)) {
    return diagnostic('relations_invalid', '$.relations', 'relations must be an array');
  }
  const relationIds = [];
  for (let index = 0; index < contract.relations.length; index += 1) {
    const relation = contract.relations[index];
    const itemPath = `$.relations[${index}]`;
    if (!relation || typeof relation !== 'object' || Array.isArray(relation)) {
      return diagnostic('relation_invalid', itemPath, 'relation must be an object');
    }
    if (typeof relation.id !== 'string' || !relation.id) {
      return diagnostic('relation_id_invalid', `${itemPath}.id`, 'relation id must be a non-empty string');
    }
    if (relationIds.includes(relation.id)) {
      return diagnostic('relation_id_duplicate', `${itemPath}.id`, `duplicate relation id: ${relation.id}`);
    }
    for (const field of ['kind', 'source', 'target']) {
      if (typeof relation[field] !== 'string' || !relation[field]) {
        return diagnostic('relation_field_invalid', `${itemPath}.${field}`, `relation ${field} must be a non-empty string`);
      }
    }
    relationIds.push(relation.id);
  }

  if (canonical(nodeIds) !== canonical([...nodeIds].sort())) {
    return diagnostic('node_ids_not_canonical', '$.nodes', 'nodes must be ordered by id');
  }
  if (canonical(relationIds) !== canonical([...relationIds].sort())) {
    return diagnostic('relation_ids_not_canonical', '$.relations', 'relations must be ordered by id');
  }
  if (canonical(stableIds.nodes) !== canonical(nodeIds)) {
    return diagnostic('stable_ids_mismatch', '$.stable_ids.nodes', 'stable node ids must exactly match ordered nodes');
  }
  if (canonical(stableIds.edges) !== canonical(relationIds)) {
    return diagnostic('stable_ids_mismatch', '$.stable_ids.edges', 'stable edge ids must exactly match ordered relations');
  }

  if (typeof contract.digest !== 'string' || !DIGEST_PATTERN.test(contract.digest)) {
    return diagnostic('digest_invalid', '$.digest', 'digest must be a lowercase SHA-256 hex string');
  }
  const body = Object.fromEntries(Object.entries(contract).filter(([key]) => key !== 'digest'));
  const expected = digest(body);
  if (contract.digest !== expected) {
    return diagnostic('digest_mismatch', '$.digest', 'digest does not match the canonical contract body', {
      expected,
      received: contract.digest,
    });
  }
  return { valid: true, reason: null, path: null, message: null };
}

function buildPublicContract(graph, repositoryId, generation) {
  if (!graph || graph.schema !== GRAPH_SCHEMA) throw new Error('graph_schema_invalid');
  if (!repositoryId || !generation) throw new Error('identity_missing');
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
    version: CONTRACT_VERSION,
    repository_id: repositoryId,
    generation,
    stable_ids: { nodes: nodes.map((node) => node.id), edges: relations.map((edge) => edge.id) },
    nodes,
    relations,
  };
  return { ...body, digest: digest(body) };
}

function publicDiagnostic(report) {
  return { valid: report.valid, reason: report.reason, path: report.path };
}

function run(fixturePath, compatibilityFixturePath) {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const compatibilityPath = compatibilityFixturePath || path.join(path.dirname(fixturePath), 'compatibility.json');
  const compatibilityFixture = JSON.parse(fs.readFileSync(compatibilityPath, 'utf8'));
  const nodeContracts = fixture.cases.map((item) => buildPublicContract(item.graph, item.repository_id, item.generation));
  const nodeDiagnostics = compatibilityFixture.cases.map((item) => validatePublicContract(item.contract));
  const pythonScript = [
    'import json, sys',
    'from simplicio_mapper.context_graph_contract import build_public_contract, validate_public_contract',
    'fixture=json.load(open(sys.argv[1], encoding="utf-8"))',
    'compatibility=json.load(open(sys.argv[2], encoding="utf-8"))',
    'contracts=[build_public_contract(item["graph"], repository_id=item["repository_id"], generation=item["generation"]) for item in fixture["cases"]]',
    'diagnostics=[validate_public_contract(item["contract"]) for item in compatibility["cases"]]',
    'print(json.dumps({"contracts": contracts, "diagnostics": diagnostics}, sort_keys=True))',
  ].join('\n');
  const python = spawnSync(process.env.PYTHON || 'python3', ['-c', pythonScript, fixturePath, compatibilityPath], { encoding: 'utf8', cwd: path.resolve(__dirname, '..') });
  const pythonReport = python.status === 0 ? JSON.parse(python.stdout) : { contracts: [], diagnostics: [] };
  const divergences = [];
  nodeContracts.forEach((item, index) => {
    if (canonical(item) !== canonical(pythonReport.contracts[index])) {
      divergences.push({ case: fixture.cases[index].name, channels: ['node', 'python'], reason: 'public_projection_mismatch', versions: { node: process.version, python: process.env.PYTHON || 'python3' } });
    }
  });

  compatibilityFixture.cases.forEach((item, index) => {
    const expected = item.expected;
    const nodeResult = publicDiagnostic(nodeDiagnostics[index]);
    const pythonResult = publicDiagnostic(pythonReport.diagnostics[index] || {});
    if (canonical(nodeResult) !== canonical(expected)) {
      divergences.push({ case: item.name, channels: ['node'], reason: 'compatibility_diagnostic_mismatch', expected, actual: nodeResult, versions: { node: process.version } });
    }
    if (canonical(pythonResult) !== canonical(expected)) {
      divergences.push({ case: item.name, channels: ['python'], reason: 'compatibility_diagnostic_mismatch', expected, actual: pythonResult, versions: { python: process.env.PYTHON || 'python3' } });
    }
  });

  const rustProbe = spawnSync(
    process.env.PYTHON || 'python3',
    ['-c', 'from simplicio_mapper_rs import schema_registry_sha256, validate_context_graph_contract; print("available")'],
    { encoding: 'utf8' },
  );
  const rustAvailable = rustProbe.status === 0;
  let rustDiagnostics = [];
  if (rustAvailable) {
    const rustScript = [
      'import json, sys',
      'from simplicio_mapper_rs import schema_registry_sha256, validate_context_graph_contract',
      'contracts=json.loads(sys.argv[1])',
      'hashes=[schema_registry_sha256(json.dumps({k:v for k,v in item.items() if k != "digest"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) for item in contracts]',
      'diagnostics=[json.loads(validate_context_graph_contract(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))) for item in contracts]',
      'print(json.dumps({"hashes": hashes, "diagnostics": diagnostics}, sort_keys=True))',
    ].join('\n');
    const compatibilityContracts = compatibilityFixture.cases.map((item) => item.contract);
    const rust = spawnSync(process.env.PYTHON || 'python3', ['-c', rustScript, JSON.stringify(compatibilityContracts)], { encoding: 'utf8' });
    if (rust.status !== 0) {
      divergences.push({ case: '*', channels: ['rust'], reason: 'rust_probe_failed', diagnostic: rust.stderr.trim(), versions: { rust: 'optional' } });
    } else {
      const rustReport = JSON.parse(rust.stdout);
      rustDiagnostics = rustReport.diagnostics;
      compatibilityFixture.cases.forEach((item, index) => {
        const actual = publicDiagnostic(rustDiagnostics[index]);
        if (canonical(actual) !== canonical(item.expected)) {
          divergences.push({ case: item.name, channels: ['rust'], reason: 'compatibility_diagnostic_mismatch', expected: item.expected, actual, versions: { rust: 'optional' } });
        }
        if (item.expected.reason !== 'digest_mismatch' && rustReport.hashes[index] !== item.contract.digest) {
          divergences.push({ case: item.name, channels: ['rust'], reason: 'public_digest_mismatch', versions: { rust: 'optional' } });
        }
      });
    }
  }
  const rustStatus = rustAvailable
    ? (divergences.some((item) => item.channels.includes('rust')) ? 'fail' : 'pass')
    : 'skipped';
  const compatibilityCases = compatibilityFixture.cases.map((item, index) => ({
    name: item.name,
    expected: item.expected,
    diagnostics: {
      python: publicDiagnostic(pythonReport.diagnostics[index] || {}),
      node: publicDiagnostic(nodeDiagnostics[index]),
      rust: rustAvailable ? publicDiagnostic(rustDiagnostics[index] || {}) : null,
    },
    status: divergences.some((divergence) => divergence.case === item.name || divergence.case === '*') ? 'fail' : 'pass',
  }));
  return {
    schema: 'simplicio.context-graph-parity/v1',
    fixture: path.relative(path.resolve(__dirname, '..'), fixturePath).replaceAll(path.sep, '/'),
    compatibility_fixture: path.relative(path.resolve(__dirname, '..'), compatibilityPath).replaceAll(path.sep, '/'),
    channels: {
      python: { status: python.status === 0 && divergences.every((item) => !item.channels.includes('python')) ? 'pass' : 'fail', version: 'simplicio-mapper', diagnostic: python.status === 0 ? null : python.stderr.trim() },
      node: { status: divergences.every((item) => !item.channels.includes('node')) ? 'pass' : 'fail', version: process.version },
      rust: { status: rustStatus, version: rustAvailable ? 'optional' : null, reason: rustAvailable ? null : 'optional accelerator unavailable' },
    },
    cases: fixture.cases.map((item, index) => ({ name: item.name, behavior: item.behavior, digest: nodeContracts[index].digest })),
    compatibility_cases: compatibilityCases,
    divergences,
  };
}

if (require.main === module) {
  try {
    const fixture = process.argv[2] || 'contracts/context-graph/v1/fixtures/parity.json';
    const compatibilityFixture = process.argv[3];
    process.stdout.write(`${JSON.stringify(run(path.resolve(fixture), compatibilityFixture && path.resolve(compatibilityFixture)))}\n`);
    process.exitCode = 0;
  } catch (error) {
    console.error(error.message || error);
    process.exitCode = 1;
  }
}

module.exports = { buildPublicContract, canonical, digest, run, validatePublicContract };
