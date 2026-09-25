'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { writeMappingArtifacts } = require('./mapper-artifacts');

const TEXT_EXTS = new Set([
  '.md', '.txt', '.json', '.jsonc', '.yml', '.yaml', '.toml',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
  '.py', '.go', '.rs', '.java', '.kt', '.php', '.rb', '.cs',
  '.sh', '.ps1', '.env', '',
]);

const WALK_SKIP_DIRS = new Set([
  '.git', 'node_modules', 'dist', 'build', 'out', 'coverage',
  '.next', '.nuxt', 'playwright-report', 'test-results', '.turbo',
  '.venv', 'venv', '__pycache__', '.idea', '.vscode', 'video',
  '.claude', '.codex', '.agents', '.skills', '.specs', '.github',
  'docs', 'scripts', 'tests',
]);

function readSafe(file) {
  try {
    return fs.readFileSync(file, 'utf8');
  } catch {
    return '';
  }
}

function exists(file) {
  return fs.existsSync(file);
}

function slugify(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-');
}

function humanizeName(value) {
  return String(value || '')
    .replace(/^@[^/]+\//, '')
    .replace(/[._-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function safeTitle(value, fallback) {
  const text = String(value || '').trim();
  return text || fallback;
}

function commandExists(cmd) {
  if (!cmd) return false;
  const which = process.platform === 'win32' ? 'where' : 'which';
  const result = spawnSync(which, [cmd], { stdio: 'ignore' });
  return result.status === 0;
}

function walk(dir, onFile) {
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    if (WALK_SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, onFile);
      continue;
    }
    if (entry.isFile()) {
      onFile(full);
    }
  }
}

function collectTextFiles(cwd) {
  const files = [];
  walk(cwd, (file) => {
    const ext = path.extname(file).toLowerCase();
    if (!TEXT_EXTS.has(ext)) return;
    files.push(file);
  });
  return files;
}

function parsePackageJson(cwd) {
  try {
    return JSON.parse(readSafe(path.join(cwd, 'package.json')) || '{}');
  } catch {
    return {};
  }
}

function detectPackageManager(cwd) {
  if (exists(path.join(cwd, 'pnpm-lock.yaml'))) return 'pnpm';
  if (exists(path.join(cwd, 'yarn.lock'))) return 'yarn';
  if (exists(path.join(cwd, 'bun.lockb')) || exists(path.join(cwd, 'bun.lock'))) return 'bun';
  return 'npm';
}

function detectUrls(stack, scripts, projectMode) {
  if (projectMode === 'monorepo') {
    return {
      frontendUrl: 'http://localhost:3000',
      backendUrl: 'http://localhost:4000',
    };
  }

  if (/next|react|vue|angular/i.test(stack)) {
    return {
      frontendUrl: 'http://localhost:3000',
      backendUrl: scripts.start || scripts.dev ? 'not-applicable' : 'not-applicable',
    };
  }

  if (/nestjs/i.test(stack)) {
    return { frontendUrl: 'not-applicable', backendUrl: 'http://localhost:3000' };
  }

  if (/express/i.test(stack)) {
    return { frontendUrl: 'not-applicable', backendUrl: 'http://localhost:4000' };
  }

  if (/python-fastapi/i.test(stack)) {
    return { frontendUrl: 'not-applicable', backendUrl: 'http://localhost:8000' };
  }

  if (/python-django/i.test(stack)) {
    return { frontendUrl: 'http://localhost:8000', backendUrl: 'http://localhost:8000' };
  }

  if (/dotnet/i.test(stack)) {
    return { frontendUrl: 'not-applicable', backendUrl: 'http://localhost:5000' };
  }

  if (/go/i.test(stack)) {
    return { frontendUrl: 'not-applicable', backendUrl: 'http://localhost:8080' };
  }

  return {
    frontendUrl: 'http://localhost:3000',
    backendUrl: 'not-applicable',
  };
}

function firstDefined(...values) {
  for (const value of values) {
    if (value && String(value).trim()) return String(value).trim();
  }
  return '';
}

function inferInstallCommand(stack, packageManager) {
  if (/next|react|vue|angular|nestjs|express|node/i.test(stack)) {
    return `${packageManager} install`;
  }
  if (/dotnet/i.test(stack)) return 'dotnet restore';
  if (/python/i.test(stack)) return exists('pyproject.toml') ? 'python -m pip install -e .' : 'pip install -r requirements.txt';
  if (/go/i.test(stack)) return 'go mod download';
  if (/rust/i.test(stack)) return 'cargo build';
  return 'review the project manifest and install its dependencies';
}

function inferCommands(cwd, stack, packageJson, packageManager) {
  const scripts = packageJson.scripts || {};
  const quote = (cmd) => cmd || '';
  const dev = firstDefined(
    scripts.dev && `${packageManager} run dev`,
    scripts.start && `${packageManager} run start`,
    /dotnet/i.test(stack) && 'dotnet run',
    /python-fastapi/i.test(stack) && 'uvicorn app:app --reload',
    /python-django/i.test(stack) && 'python manage.py runserver',
    /go/i.test(stack) && 'go run .',
    /rust/i.test(stack) && 'cargo run',
    `${packageManager} run dev`,
  );

  const build = firstDefined(
    scripts.build && `${packageManager} run build`,
    /dotnet/i.test(stack) && 'dotnet build',
    /python/i.test(stack) && 'python -m compileall .',
    /go/i.test(stack) && 'go build ./...',
    /rust/i.test(stack) && 'cargo build',
    '',
  );

  const lint = firstDefined(
    scripts.lint && `${packageManager} run lint`,
    /python/i.test(stack) && 'ruff check .',
    /dotnet/i.test(stack) && 'dotnet format --verify-no-changes',
    /go/i.test(stack) && 'go vet ./...',
    /rust/i.test(stack) && 'cargo fmt --check',
    '',
  );

  const test = firstDefined(
    scripts.test && `${packageManager} test`,
    /dotnet/i.test(stack) && 'dotnet test',
    /python/i.test(stack) && 'pytest',
    /go/i.test(stack) && 'go test ./...',
    /rust/i.test(stack) && 'cargo test',
    '',
  );

  const e2e = firstDefined(
    scripts['test:e2e'] && `${packageManager} run test:e2e`,
    scripts.e2e && `${packageManager} run e2e`,
    /playwright/i.test(JSON.stringify(packageJson)) && 'npx playwright test',
    '',
  );

  const validate = [lint, test, build].filter(Boolean).join(' && ') || firstDefined(test, lint, build, 'echo "Add project validation command here"');
  const evidence = e2e || 'BASE_URL=http://localhost:3000 npx playwright test --project=chromium';

  return {
    dev: quote(dev),
    build: quote(build),
    lint: quote(lint),
    test: quote(test),
    e2e: quote(e2e),
    validate: quote(validate),
    evidence: quote(evidence),
    install: inferInstallCommand(stack, packageManager),
  };
}

function inferDatabase(pkgJson, corpus) {
  const text = `${JSON.stringify(pkgJson)}\n${corpus}`.toLowerCase();
  if (/postgres|pg\b|prisma.*postgres|typeorm.*postgres|sequelize.*postgres|npgsql/.test(text)) return 'PostgreSQL';
  if (/mysql|mariadb/.test(text)) return 'MySQL/MariaDB';
  if (/sqlite/.test(text)) return 'SQLite';
  if (/mongodb|mongoose/.test(text)) return 'MongoDB';
  if (/redis/.test(text)) return 'Redis';
  return 'none documented';
}

function inferAuthFlow(pkgJson, corpus) {
  const text = `${JSON.stringify(pkgJson)}\n${corpus}`.toLowerCase();
  if (/next-auth|authjs/.test(text)) return 'NextAuth/Auth.js session flow';
  if (/clerk/.test(text)) return 'Clerk hosted authentication';
  if (/auth0/.test(text)) return 'Auth0 OAuth/OIDC';
  if (/firebase.*auth/.test(text)) return 'Firebase Authentication';
  if (/jwt|bearer token/.test(text)) return 'JWT bearer tokens';
  if (/login|signin|signup|password/.test(text)) return 'application-managed login flow';
  return 'not detected';
}

function inferTeam(meta, packageJson, gitRemote) {
  if (meta && meta.team) return meta.team;
  if (packageJson.author && typeof packageJson.author === 'object' && packageJson.author.name) {
    return `${slugify(packageJson.author.name)}-team`;
  }
  const pkgName = packageJson.name || '';
  if (/^@[^/]+\//.test(pkgName)) {
    return `${pkgName.slice(1).split('/')[0]}-team`;
  }
  if (gitRemote) {
    const match = gitRemote.match(/[:/]([^/]+)\/[^/]+(?:\.git)?$/);
    if (match) return `${slugify(match[1])}-team`;
  }
  return 'core-team';
}

function inferDomain(meta, packageJson, readme) {
  if (meta && meta.domain) return meta.domain;
  const description = String(packageJson.description || '').trim();
  const text = `${packageJson.name || ''} ${description} ${readme}`.toLowerCase();
  if (/agent|developer|repo|workflow|ci|spec|prompt|codex|claude/.test(text)) return 'developer-tools';
  if (/payment|billing|invoice|checkout|stripe/.test(text)) return 'payments';
  if (/health|clinic|patient|medical/.test(text)) return 'healthcare';
  if (/crm|lead|sales/.test(text)) return 'sales-ops';
  const pkgName = humanizeName(packageJson.name || '').toLowerCase();
  return slugify(pkgName || 'product-operations') || 'product-operations';
}

function getGitRemote(cwd) {
  try {
    const result = spawnSync('git', ['remote', 'get-url', 'origin'], {
      cwd,
      encoding: 'utf8',
      timeout: 2000,
    });
    if (result.status === 0) return String(result.stdout || '').trim();
  } catch {
    // ignore
  }
  return '';
}

function collectTopDirectories(cwd) {
  try {
    return fs.readdirSync(cwd, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.') && !WALK_SKIP_DIRS.has(entry.name))
      .map((entry) => entry.name)
      .slice(0, 10);
  } catch {
    return [];
  }
}

function collectEntities(files) {
  const scores = new Map();
  const interesting = /\b(user|account|order|invoice|payment|report|project|workspace|task|sprint|skill|agent|customer|team|session|document|message|job|build|release)\b/i;
  for (const file of files) {
    const base = path.basename(file, path.extname(file))
      .replace(/[-_.]/g, ' ')
      .trim();
    if (!interesting.test(base)) continue;
    for (const token of base.split(/\s+/)) {
      if (!interesting.test(token)) continue;
      const key = token.toLowerCase();
      scores.set(key, (scores.get(key) || 0) + 1);
    }
  }

  const entities = Array.from(scores.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([name]) => humanizeName(name));

  if (entities.length > 0) return entities;
  return ['Project', 'Workflow', 'Documentation'];
}

function collectFeatures(files) {
  const items = new Map();
  for (const file of files) {
    const normalized = file.replace(/\\/g, '/');
    const match = normalized.match(/(?:pages|routes|features|app)\/([^/]+)/i);
    if (!match) continue;
    const feature = humanizeName(match[1]);
    items.set(feature, normalized);
  }
  const features = Array.from(items.entries())
    .slice(0, 6)
    .map(([name, source]) => ({ name, source }));

  if (features.length > 0) return features;
  return [{ name: 'Project bootstrap', source: 'root manifest + starter docs' }];
}

function collectTodos(files) {
  const todos = [];
  for (const file of files) {
    const rel = file;
    const content = readSafe(file);
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      if (/(TODO|FIXME|HACK)/.test(lines[i])) {
        todos.push(`${path.basename(rel)}:${i + 1} — ${lines[i].trim()}`);
        if (todos.length >= 8) return todos;
      }
    }
  }
  return todos;
}

function collectIntegrations(pkgJson, corpus) {
  const integrations = [];
  const text = `${JSON.stringify(pkgJson)}\n${corpus}`.toLowerCase();
  const candidates = [
    ['GitHub', /github|gh\b/],
    ['Stripe', /stripe/],
    ['OpenAI', /openai/],
    ['Playwright', /playwright/],
    ['Auth0', /auth0/],
    ['Clerk', /clerk/],
    ['Sentry', /sentry/],
    ['Redis', /redis/],
    ['PostgreSQL', /postgres|pg\b/],
  ];

  for (const [label, pattern] of candidates) {
    if (pattern.test(text)) integrations.push(label);
  }
  return integrations.length > 0 ? integrations : ['none detected'];
}

function inferSystemType(stack, projectMode) {
  if (projectMode === 'monorepo') return 'MONOREPO';
  if (/next|react|vue|angular/i.test(stack)) return 'FRONTEND_ONLY';
  if (/nestjs|express|fastapi|django|dotnet|go|laravel/i.test(stack)) return 'API';
  return 'FULLSTACK';
}

function renderVision(profile) {
  const entityLine = profile.entities.slice(0, 3).join(', ');
  return `# VISION — ${profile.productTitle}

Documento gerado automaticamente no bootstrap para reduzir o tempo até a primeira contribuição útil no repositório.

## Problema

${profile.productTitle} ainda depende de descoberta manual para entender contexto, comandos e áreas principais do código. Isso aumenta o tempo de onboarding e faz cada agente ou desenvolvedor reconstruir o mapa do projeto do zero.

## Quem usa

- **Persona primária:** desenvolvedor ou agente responsável por executar mudanças com segurança.
- **Persona secundária:** revisor técnico que precisa validar impacto, comandos e evidências rapidamente.
- **Quem não é o público:** usuários finais fora do fluxo de manutenção do repositório.

## Diferencial

- Mapeamento inicial automático logo após aplicar o starter.
- Documentação operacional gerada a partir do manifesto e dos arquivos reais do projeto.
- Stack detectada automaticamente: ${profile.stackLabel}.
- Entidades e áreas principais resumidas sem depender de prompts manuais.

## Métricas de sucesso

| Métrica | Baseline | Meta inicial | Como medimos |
|---|---|---|---|
| Tempo para entender o projeto | desconhecido | < 30 min | leitura dos docs gerados + comandos válidos |
| Tempo para primeira task | desconhecido | < 1 dia | task criada e validada localmente |
| Cobertura do mapa inicial | manual | comandos, entidades e integrações registrados | revisão dos arquivos gerados |

## Não-objetivos

- Não reescrever código de produto.
- Não inferir regras de negócio inexistentes no repositório.
- Não substituir revisão humana para decisões arquiteturais sensíveis.

## Tese de longo prazo

${profile.productTitle} deve permitir que qualquer mantenedor entenda rapidamente ${profile.domainLabel} e comece a trabalhar com contexto suficiente já no primeiro contato com o repositório.

## Sinais detectados no bootstrap

- Stack: ${profile.stackLabel}
- Domínio inferido: ${profile.domainLabel}
- Entidades observadas: ${entityLine}
- Integrações observadas: ${profile.integrations.join(', ')}

## Histórico

| Data | Versão | Mudança | Quem |
|---|---|---|---|
| ${profile.today} | 0.1 | Initial automatic mapping generated during bootstrap | ${profile.team} |
`;
}

function renderDomain(profile) {
  const entityRows = profile.entities.map((entity) => `| ${entity} | Elemento recorrente detectado no código ou na estrutura do projeto. | source tree / docs |`).join('\n');
  const erBody = profile.entities.slice(0, 3).map((entity) => {
    const key = slugify(entity).replace(/-/g, '_').toUpperCase() || 'ENTITY';
    return `    ${key} {\n        string name\n        string source\n    }`;
  }).join('\n');
  return `# DOMAIN — ${profile.productTitle}

Mapa inicial do domínio inferido durante o bootstrap. Use este arquivo como glossário curto para alinhar nomes de entidades, fluxos e regras observadas no repositório.

## Contexto

- **Domínio inferido:** ${profile.domainLabel}
- **Objetivo operacional principal:** ${profile.businessGoal}
- **Entidades mais frequentes:** ${profile.entities.join(', ')}

## Glossário

| Termo | Definição | Onde aparece |
|---|---|---|
| ${profile.entities[0]} | Entidade recorrente usada para organizar parte importante do projeto. | estrutura de arquivos e documentação |
| ${profile.entities[1] || 'Workflow'} | Conceito operacional que aparece no fluxo principal do repositório. | docs e convenções do projeto |
| ${profile.entities[2] || 'Validation'} | Área usada para validar ou governar mudanças. | scripts, testes ou docs |

## Entidades principais

${profile.entities.map((entity) => `### ${entity}

- O que é: artefato ou conceito central detectado durante a inspeção automática.
- Onde aparece: arquivos com nomes relacionados a ${entity.toLowerCase()}.
- Papel no projeto: ajuda a estruturar o fluxo de ${profile.domainLabel}.`).join('\n\n')}

## Diagrama de entidades

\`\`\`mermaid
erDiagram
    PROJECT ||--o{ DOCUMENTATION : "describes"
    PROJECT ||--o{ WORKFLOW : "executes"
    WORKFLOW ||--o{ ENTITY : "organizes"

${erBody}
\`\`\`

## Regras de negócio observadas

- O código deve ser entendido por meio dos manifests, docs e testes antes de qualquer edição ampla.
- Comandos de desenvolvimento e validação precisam existir em documentação operacional.
- Novas mudanças devem preservar o contexto compartilhado do repositório.

## Termos que devem ficar consistentes

| Termo | Uso recomendado |
|---|---|
| product | o repositório ou aplicação principal |
| workflow | sequência operacional para entregar mudança |
| evidence | artefato de validação, como report, trace ou log |

## Fontes consultadas

${entityRows}

## Histórico

| Data | Mudança | Quem |
|---|---|---|
| ${profile.today} | Mapa inicial gerado automaticamente | ${profile.team} |
`;
}

function renderPersonas(profile) {
  const personas = profile.personas;
  return `# PERSONAS — ${profile.productTitle}

Personas inferidas automaticamente a partir da stack, dos comandos e da estrutura do repositório.

${personas.map((persona, index) => `## Persona ${index + 1} — ${persona.name}

**Arquétipo:** ${persona.archetype}

### Quem é

- **Papel:** ${persona.role}
- **Contexto:** ${persona.context}
- **Familiaridade com o domínio:** ${persona.domainFit}

### Objetivos

${persona.goals.map((goal) => `- ${goal}`).join('\n')}

### Frustrações

${persona.pains.map((pain) => `- ${pain}`).join('\n')}

### Métrica que importa

- ${persona.metric}
`).join('\n')}

## Histórico

| Data | Mudança | Quem |
|---|---|---|
| ${profile.today} | Personas iniciais geradas automaticamente | ${profile.team} |
`;
}

function renderDesign(profile) {
  const topDirs = profile.topDirs.length > 0 ? profile.topDirs.join(', ') : 'root files only';
  return `# Design — ${profile.productTitle}

Visão arquitetural inicial criada automaticamente a partir do manifesto, da árvore de arquivos e dos comandos detectados.

## 1. Contexto do sistema

\`\`\`mermaid
graph LR
  maintainer["Maintainer or AI agent"]
  repo["${profile.productTitle} repository"]
  docs["Operational docs"]
  tests["Validation commands"]
  integrations["External integrations"]

  maintainer --> repo
  repo --> docs
  repo --> tests
  repo --> integrations
\`\`\`

## 2. Componentes observados

- **Tipo do sistema:** ${profile.systemType}
- **Stack detectada:** ${profile.stackLabel}
- **Pastas principais:** ${topDirs}
- **Integrações observadas:** ${profile.integrations.join(', ')}

## 3. Fluxo principal de manutenção

1. Ler manifesto e documentação operacional.
2. Executar comandos reais de desenvolvimento e validação.
3. Alterar arquivos dentro do escopo.
4. Validar com lint, testes e evidências disponíveis.
5. Atualizar docs quando a mudança alterar entendimento do projeto.

## 4. Boundaries

| Boundary | Responsabilidade |
|---|---|
| Product docs | explicar propósito, domínio e decisões |
| Runtime / source | implementar o comportamento real |
| Validation | comprovar que a mudança funciona |
| Delivery | versionar, publicar e documentar release |

## 5. Stack resumida

| Camada | Tecnologia |
|---|---|
| Linguagem / runtime | ${profile.stackLabel} |
| Package manager | ${profile.packageManager} |
| Testes | ${profile.commands.test || 'not detected'} |
| E2E / evidence | ${profile.commands.evidence} |
| Build | ${profile.commands.build || 'not detected'} |

## 6. Notas de evolução

- O mapeamento automático é um ponto de partida, não um substituto para ADR quando a arquitetura muda.
- Se novas integrações, serviços ou boundaries surgirem, atualize este arquivo no mesmo PR.
`;
}

function renderPatterns(profile) {
  return `# Patterns — ${profile.productTitle}

Padrões iniciais inferidos automaticamente para orientar humanos e agentes até que o projeto refine suas próprias convenções.

## Naming

- Código em inglês, documentação operacional em pt-BR.
- Arquivos preferencialmente em kebab-case.
- Commits em Conventional Commits.

## Estrutura observada

- Diretórios de topo: ${profile.topDirs.join(', ') || 'root only'}
- Stack detectada: ${profile.stackLabel}
- Package manager: ${profile.packageManager}

## Comandos principais

- Desenvolvimento: \`${profile.commands.dev}\`
- Lint: \`${profile.commands.lint || 'not detected'}\`
- Testes: \`${profile.commands.test || 'not detected'}\`
- Build: \`${profile.commands.build || 'not detected'}\`

## Regras operacionais

- Ler docs e manifests antes de editar código.
- Validar localmente toda mudança relevante.
- Atualizar CHANGELOG quando a mudança for release-relevant.
- Preservar instruções já existentes do usuário quando o bootstrap detectar arquivos prévios.
`;
}

function renderBacklog(profile) {
  const todoItems = profile.todos.length > 0
    ? profile.todos.slice(0, 5).map((todo, index) => `| ${index + 1} | Revisar pendência detectada: ${todo.replace(/\|/g, '/')} | P1 | sprint-01 | todo |`).join('\n')
    : `| 1 | Validar o mapa automático inicial e ajustar docs específicas do projeto | P0 | sprint-01 | todo |`;
  return `# Backlog — ${profile.productTitle}

Backlog inicial gerado automaticamente a partir da inspeção do repositório.

| # | Título | Prioridade | Sprint alvo | Status |
|---|---|---|---|---|
${todoItems}

| 99 | Confirmar entidades e fluxos com um mantenedor humano | P2 | backlog | todo |
`;
}

function renderSprint(profile) {
  return `---
sprint: sprint-01
status: todo
start: ${profile.today}
end: ${profile.today}
owner: ${profile.team}
---

# Sprint 01 — Mapeamento inicial e baseline operacional

## Objetivo

Consolidar o mapa inicial de ${profile.productTitle}, validar os comandos detectados e deixar a base pronta para as próximas mudanças em ${profile.domainLabel}.

## Deliverables

1. Documentação operacional revisada.
2. Comandos de desenvolvimento, validação e evidência confirmados.
3. Pendências principais priorizadas no backlog.

## Tasks

| Arquivo | Status | Owner |
|---|---|---|
| \`01-example.task.md\` | todo | @${profile.team} |

## Riscos

- Algum comando detectado automaticamente pode precisar de ajuste humano.
- Integrações externas podem exigir credenciais que não estão no repositório.
`;
}

function renderSprintTask(profile) {
  return `---
id: 01
title: validar o mapeamento inicial do projeto
status: todo
owner: @${profile.team}
---

# Task 01 — Validar o mapeamento inicial

## Contexto

O bootstrap gerou automaticamente a primeira versão dos arquivos operacionais de ${profile.productTitle}. Agora o objetivo é revisar o material com foco em ${profile.domainLabel} e corrigir qualquer comando ou regra que tenha sido inferido de forma incompleta.

## Acceptance Criteria

- [ ] Os comandos em \`docs/local-setup.md\` funcionam ou estão claramente ajustados.
- [ ] As entidades principais em \`.specs/product/DOMAIN.md\` representam o projeto real.
- [ ] As integrações e riscos principais estão documentados.

## Test Plan

- Executar \`${profile.commands.lint || profile.commands.validate}\`
- Executar \`${profile.commands.test || profile.commands.validate}\`
- Revisar manualmente \`.specs/\` e \`docs/\`
`;
}

function renderLocalSetup(profile) {
  const services = [];
  if (profile.frontendUrl !== 'not-applicable') {
    services.push(`| Frontend | ${profile.frontendUrl} | ${profile.frontendUrl}/ |`);
  }
  if (profile.backendUrl !== 'not-applicable') {
    services.push(`| Backend | ${profile.backendUrl} | ${profile.backendUrl}/ |`);
  }
  if (services.length === 0) {
    services.push('| Primary service | not-applicable | not-applicable |');
  }

  return `# Local Setup

Documento inicial gerado automaticamente a partir do manifesto e dos scripts detectados no projeto.

## Prerequisites

- Runtime / stack: ${profile.stackLabel}
- Package manager: ${profile.packageManager}
- Database: ${profile.database}
- External access: none documented
- Secrets: review .env files and CI secrets before running protected flows

## Install

\`\`\`bash
${profile.commands.install}
\`\`\`

## Start

\`\`\`bash
${profile.commands.dev}
\`\`\`

## Validate

\`\`\`bash
${profile.commands.validate}
\`\`\`

## Expected services

| Service | URL | Health check |
|---|---|---|
${services.join('\n')}

## Demo access

- Flow: ${profile.authFlow}
- Demo user: not detected
- Demo password location: not documented

## Evidence

\`\`\`bash
${profile.commands.evidence}
\`\`\`
`;
}

function renderArchitectureMap(profile) {
  const serviceRows = [];
  if (profile.frontendUrl !== 'not-applicable') {
    serviceRows.push(`| Frontend | ${profile.frontendUrl} | generated default for detected web stack |`);
  }
  if (profile.backendUrl !== 'not-applicable') {
    serviceRows.push(`| Backend | ${profile.backendUrl} | generated default for detected server stack |`);
  }
  if (serviceRows.length === 0) {
    serviceRows.push('| Service | not-applicable | confirm runtime entrypoint manually |');
  }

  return `# Architecture Map

## System Shape

- Type: ${profile.systemType}
- Frontend: ${profile.frontendTech}
- Backend: ${profile.backendTech}
- Database: ${profile.database}
- Jobs/workers: ${profile.jobs}
- External integrations: ${profile.integrations.join(', ')}

## Local URLs

| Service | URL | Notes |
|---|---|---|
${serviceRows.join('\n')}

## Request Path

\`\`\`text
Maintainer or AI agent -> project manifest/docs -> runtime entrypoint -> validation commands -> evidence
\`\`\`

## Key Directories

${profile.topDirs.map((dir) => `- \`${dir}\` — top-level area detected during bootstrap`).join('\n')}

## Authentication

- Flow: ${profile.authFlow}
- Local/demo credentials: not documented
- Token/session storage: not detected
- Common failure mode: missing local environment variables or auth provider configuration

## Observability

- App logs: stdout / terminal output
- API logs: stdout when backend is present
- Job logs: not detected
- Request correlation: not detected

## Deployment

- Environments: local plus CI-managed environments if configured
- CI/CD: GitHub Actions when present under .github/workflows
- Release notes/changelog: CHANGELOG.md
`;
}

function renderDomainMap(profile) {
  return `# Domain Map

## Product Context

- App: ${profile.productTitle}
- Main users: ${profile.personas.map((persona) => persona.name).join(', ')}
- Main business goal: ${profile.businessGoal}

## Core Concepts

| Concept | Meaning | Source of truth |
|---|---|---|
${profile.entities.slice(0, 4).map((entity) => `| ${entity} | Conceito recorrente detectado automaticamente no projeto. | .specs/product/DOMAIN.md |`).join('\n')}

## Critical Rules

| Rule | Expected behavior | Where implemented | How to test |
|---|---|---|---|
| Commands stay documented | Desenvolvimento, validação e evidência precisam estar explícitos | docs/local-setup.md + AGENTS.md | executar os comandos listados |
| Mapping stays current | Mudanças relevantes atualizam docs no mesmo PR | .specs/ + docs/ | revisão de diff |

## Main Entities

| Entity | Description | Storage |
|---|---|---|
${profile.entities.map((entity) => `| ${entity} | Entidade ou conceito principal identificado no código. | repository structure / docs |`).join('\n')}

## Important Flows

### Project bootstrap and validation

1. User/system action: apply the starter and inspect the project.
2. Entry point: repository manifest and local scripts.
3. Main modules: package manifest, docs, tests, validation scripts.
4. Output: actionable project map plus runnable commands.
5. Evidence: lint/test output and Playwright report when available.

## Edge Cases

- Commands absent from the manifest: bootstrap falls back to generic runtime defaults.
- Pre-existing docs owned by the host project: automatic mapping preserves them instead of overwriting.
`;
}

function renderFeatureNotes(profile) {
  return `# Feature Notes

Resumo automático das áreas iniciais detectadas no projeto. Conforme o produto evoluir, crie um arquivo por fluxo relevante em \`docs/features/\`.

## Features detectadas

${profile.features.map((feature) => `### ${feature.name}

- **Origem detectada:** \`${feature.source}\`
- **Objetivo inicial:** revisar se esta área representa um fluxo de negócio, módulo técnico ou documentação operacional.
- **Próxima ação recomendada:** criar um arquivo dedicado se a área tiver regras, endpoints ou evidências próprias.
`).join('\n')}

## Estrutura recomendada para cada feature futura

- objetivo do fluxo
- arquivos principais
- regras de negócio
- cenários de teste
- evidências esperadas
`;
}

function renderEvidenceReadme(profile) {
  return `# Evidence

Evidence proves that a change works in the running application, not only in code.

## Default output

\`\`\`text
.runtime-logs/evidence/
  <feature>-<scenario>-<timestamp>.png
  <feature>-<scenario>-<timestamp>.webm
  <feature>-<scenario>-<timestamp>-trace.zip
\`\`\`

## Default command

\`\`\`bash
${profile.commands.evidence}
\`\`\`

## Checklist

- [ ] Evidence matches the requested scenario.
- [ ] Sensitive inputs are not visible.
- [ ] The expected result is visible or asserted.
- [ ] The evidence path is referenced in the final response or PR.
`;
}

function renderTroubleshooting(profile) {
  return `# Troubleshooting

## Port Already In Use

- Symptom: local service fails to bind the expected port.
- Diagnose: inspect processes listening on ${profile.port}.
- Fix: stop the previous process or change the configured port.

## Database Connection Fails

- Symptom: startup or tests fail while connecting to ${profile.database}.
- Diagnose: verify env vars, local services and migrations.
- Fix: start the database or update the local configuration.

## Authentication Fails

- Symptom: redirect loop, 401/403, callback error or missing session.
- Diagnose: confirm ${profile.authFlow}.
- Fix: update local auth configuration and documented demo credentials.

## Frontend Calls Wrong API

- Symptom: UI loads but reads data from the wrong environment.
- Diagnose: inspect the API base URL in local config.
- Fix: point the app to ${profile.backendUrl}.

## Playwright Missing Dependencies

- Symptom: E2E fails before opening the page or video cannot be recorded.
- Diagnose: review Playwright install output.
- Fix:

\`\`\`bash
npx playwright install
npx playwright install ffmpeg
\`\`\`
`;
}

function renderInspection(profile) {
  return `# Inspection — ${profile.today}

## Stack real

- Product: ${profile.productTitle}
- Stack: ${profile.stackLabel}
- Package manager: ${profile.packageManager}
- Project mode: ${profile.projectMode}

## Commands úteis

- Install: \`${profile.commands.install}\`
- Dev: \`${profile.commands.dev}\`
- Lint: \`${profile.commands.lint || 'not detected'}\`
- Test: \`${profile.commands.test || 'not detected'}\`
- Build: \`${profile.commands.build || 'not detected'}\`
- Evidence: \`${profile.commands.evidence}\`

## Estrutura de pastas

${profile.topDirs.map((dir) => `- \`${dir}\``).join('\n')}

## Entidades detectadas

${profile.entities.map((entity) => `- ${entity}`).join('\n')}

## Integrações

${profile.integrations.map((item) => `- ${item}`).join('\n')}

## TODOs encontrados

${profile.todos.length > 0 ? profile.todos.map((todo) => `- ${todo}`).join('\n') : '- nenhum TODO/FIXME/HACK encontrado na inspeção curta'}
`;
}

function renderStartScript(profile, shell) {
  if (shell === 'ps1') {
    return `param(
    [string]$FrontendCommand = "${profile.frontendStartCommand}",
    [string]$BackendCommand = "${profile.backendStartCommand}"
)

$ErrorActionPreference = "Stop"

Write-Host "Starting ${profile.productTitle} local services"
Write-Host "Frontend URL: ${profile.frontendUrl}"
Write-Host "Backend URL: ${profile.backendUrl}"
Write-Host ""
Write-Host "Frontend command:"
Write-Host $FrontendCommand
Write-Host ""
Write-Host "Backend command:"
Write-Host $BackendCommand
`;
  }

  return `#!/usr/bin/env bash
set -euo pipefail

FRONTEND_COMMAND="\${FRONTEND_COMMAND:-${profile.frontendStartCommand}}"
BACKEND_COMMAND="\${BACKEND_COMMAND:-${profile.backendStartCommand}}"

echo "Starting ${profile.productTitle} local services"
echo "Frontend URL: ${profile.frontendUrl}"
echo "Backend URL: ${profile.backendUrl}"
echo
echo "Frontend command:"
echo "$FRONTEND_COMMAND"
echo
echo "Backend command:"
echo "$BACKEND_COMMAND"
`;
}

function renderTestScript(profile, shell) {
  if (shell === 'ps1') {
    return `$ErrorActionPreference = "Stop"

$TestCommand = $env:TEST_COMMAND
if ([string]::IsNullOrWhiteSpace($TestCommand)) {
    $TestCommand = "${profile.commands.validate}"
}

Write-Host "Running validation:"
Write-Host $TestCommand
Invoke-Expression $TestCommand
`;
  }

  return `#!/usr/bin/env bash
set -euo pipefail

TEST_COMMAND="\${TEST_COMMAND:-${profile.commands.validate}}"

echo "Running validation:"
echo "$TEST_COMMAND"
eval "$TEST_COMMAND"
`;
}

function renderE2EReadme(profile) {
  return `# E2E Tests

The starter ships with a generic Playwright smoke test.

Run it with:

\`\`\`bash
BASE_URL=${profile.frontendUrl === 'not-applicable' ? profile.backendUrl : profile.frontendUrl} npx playwright test --project=chromium
\`\`\`

Replace or extend \`smoke.spec.ts\` with project-specific scenarios once the main user flows are known.
`;
}

function defaultPersonas(profile) {
  return [
    {
      name: 'Developer maintainer',
      archetype: 'Pessoa que altera código, docs e automações do projeto',
      role: 'developer or repository maintainer',
      context: 'trabalha no terminal, editor e CI do repositório',
      domainFit: `alta em ${profile.domainLabel}`,
      goals: [
        'entender rapidamente os comandos reais do projeto',
        'alterar código sem quebrar validação local',
        'usar documentação como contexto operacional confiável',
      ],
      pains: [
        'docs incompletas ou desatualizadas',
        'falta de comandos claros para validar mudanças',
      ],
      metric: 'tempo até primeira mudança validada',
    },
    {
      name: 'AI execution agent',
      archetype: 'Agente que consome o repositório para executar tarefas',
      role: 'AI agent operating on the repo',
      context: 'depende totalmente do contexto escrito no repositório',
      domainFit: `média em ${profile.domainLabel} até o projeto detalhar regras próprias`,
      goals: [
        'localizar áreas importantes do código',
        'seguir comandos válidos de lint, teste e build',
        'preservar arquivos do usuário ao aplicar o starter',
      ],
      pains: [
        'placeholders não resolvidos',
        'arquivos de contexto em conflito com a implementação real',
      ],
      metric: 'percentual de tarefas concluídas sem retrabalho de contexto',
    },
  ];
}

function looksStarterManaged(content) {
  return /LLM Project Mapper|<[^>\n]{1,80}>/.test(content);
}

function writeIfSafe(cwd, relPath, content) {
  const abs = path.join(cwd, relPath);
  const current = readSafe(abs);
  if (current && !looksStarterManaged(current)) return false;
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, content);
  return true;
}

function substituteTokensInFile(file, replacements) {
  const current = readSafe(file);
  if (!current) return false;
  let next = current;
  for (const [token, value] of Object.entries(replacements)) {
    next = next.split(`<${token}>`).join(value);
  }
  if (next === current) return false;
  fs.writeFileSync(file, next);
  return true;
}

function collectCorpus(files) {
  return files
    .slice(0, 80)
    .map((file) => readSafe(file).slice(0, 3000))
    .join('\n');
}

function buildProfile(cwd, meta) {
  const pkg = parsePackageJson(cwd);
  const readme = readSafe(path.join(cwd, 'README.md'));
  const files = collectTextFiles(cwd);
  const corpus = collectCorpus(files);
  const packageManager = detectPackageManager(cwd);
  const commands = inferCommands(cwd, meta.stack, pkg, packageManager);
  const urls = detectUrls(meta.stack, commands, meta.project_mode);
  const remote = getGitRemote(cwd);
  const productTitle = humanizeName(meta.product_name || pkg.name || path.basename(cwd));
  const domain = inferDomain(meta, pkg, readme);
  const domainLabel = humanizeName(domain);
  const team = inferTeam(meta, pkg, remote);
  const entities = collectEntities(files);
  const features = collectFeatures(files);
  const todos = collectTodos(files);
  const integrations = collectIntegrations(pkg, corpus);
  const frontendTech = /next|react|vue|angular/i.test(meta.stack) ? meta.stack : 'not detected';
  const backendTech = /express|nestjs|python|dotnet|go|laravel/i.test(meta.stack) ? meta.stack : 'not detected';
  const today = new Date().toISOString().slice(0, 10);
  const portMatch = `${urls.frontendUrl} ${urls.backendUrl}`.match(/:(\d{2,5})/);
  const businessGoal = safeTitle(
    String(pkg.description || '').trim(),
    `reduce discovery time and make ${productTitle} easier to operate`,
  );

  return {
    cwd,
    today,
    projectMode: meta.project_mode || 'root',
    productTitle,
    stackLabel: meta.stack,
    packageManager,
    commands,
    frontendUrl: urls.frontendUrl,
    backendUrl: urls.backendUrl,
    frontendHealth: urls.frontendUrl === 'not-applicable' ? 'not-applicable' : `${urls.frontendUrl}/`,
    backendHealth: urls.backendUrl === 'not-applicable' ? 'not-applicable' : `${urls.backendUrl}/`,
    database: inferDatabase(pkg, corpus),
    authFlow: inferAuthFlow(pkg, corpus),
    team,
    domain,
    domainLabel,
    entities,
    features,
    todos,
    integrations,
    topDirs: collectTopDirectories(cwd),
    systemType: inferSystemType(meta.stack, meta.project_mode),
    frontendTech,
    backendTech,
    jobs: /worker|queue|cron|job/i.test(corpus) ? 'detected in repository text' : 'not detected',
    businessGoal,
    port: portMatch ? portMatch[1] : '3000',
    frontendStartCommand: commands.dev,
    backendStartCommand: commands.dev,
    personas: defaultPersonas({ domainLabel }),
  };
}

function autoMapProject({ cwd, meta, log = () => {} }) {
  const profile = buildProfile(cwd, meta);
  profile.personas = defaultPersonas(profile);

  const replacements = {
    PRODUCT_NAME: profile.productTitle,
    STACK: profile.stackLabel,
    TEAM: profile.team,
    DOMAIN: profile.domain,
    APP_NAME: profile.productTitle,
    FRONTEND_URL: profile.frontendUrl,
    BACKEND_URL: profile.backendUrl,
    FRONTEND_HEALTH: profile.frontendHealth,
    BACKEND_HEALTH: profile.backendHealth,
    DATABASE_REQUIREMENT: profile.database,
    AUTH_FLOW: profile.authFlow,
    EVIDENCE_COMMAND: profile.commands.evidence,
    USER_TYPES: profile.personas.map((persona) => persona.name).join(', '),
    BUSINESS_GOAL: profile.businessGoal,
    PORT: profile.port,
    NOTES: 'generated automatically during bootstrap',
    FRONTEND_START_COMMAND: profile.frontendStartCommand,
    BACKEND_START_COMMAND: profile.backendStartCommand,
    TEST_COMMAND: profile.commands.validate,
  };

  const substitutionTargets = [
    'AGENTS.md',
    'CLAUDE.md',
    '.github/copilot-instructions.md',
    '.specs',
    'docs',
    'scripts',
    'tests/e2e/README.md',
  ];

  for (const rel of substitutionTargets) {
    const abs = path.join(cwd, rel);
    if (!exists(abs)) continue;
    const stat = fs.statSync(abs);
    if (stat.isDirectory()) {
      walk(abs, (file) => { substituteTokensInFile(file, replacements); });
      continue;
    }
    substituteTokensInFile(abs, replacements);
  }

  const writes = [
    ['.specs/product/VISION.md', renderVision(profile)],
    ['.specs/product/DOMAIN.md', renderDomain(profile)],
    ['.specs/product/PERSONAS.md', renderPersonas(profile)],
    ['.specs/architecture/DESIGN.md', renderDesign(profile)],
    ['.specs/architecture/PATTERNS.md', renderPatterns(profile)],
    ['.specs/sprints/BACKLOG.md', renderBacklog(profile)],
    ['.specs/sprints/sprint-01/SPRINT.md', renderSprint(profile)],
    ['.specs/sprints/sprint-01/01-example.task.md', renderSprintTask(profile)],
    ['docs/local-setup.md', renderLocalSetup(profile)],
    ['docs/architecture-map.md', renderArchitectureMap(profile)],
    ['docs/domain-map.md', renderDomainMap(profile)],
    ['docs/features/README.md', renderFeatureNotes(profile)],
    ['docs/evidence/README.md', renderEvidenceReadme(profile)],
    ['docs/troubleshooting.md', renderTroubleshooting(profile)],
    ['scripts/start.sh', renderStartScript(profile, 'sh')],
    ['scripts/start.ps1', renderStartScript(profile, 'ps1')],
    ['scripts/test.sh', renderTestScript(profile, 'sh')],
    ['scripts/test.ps1', renderTestScript(profile, 'ps1')],
    ['tests/e2e/README.md', renderE2EReadme(profile)],
    [`.specs/journal/inspection-${profile.today}.md`, renderInspection(profile)],
  ];

  let written = 0;
  for (const [relPath, content] of writes) {
    if (writeIfSafe(cwd, relPath, content)) written++;
  }

  log(`→ auto-mapped ${written} project files from local inspection.`);
  writeMappingArtifacts({ cwd, meta, incremental: false, log });
  return profile;
}

module.exports = {
  autoMapProject,
};
