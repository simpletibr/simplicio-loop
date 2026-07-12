export type Lang = "pt" | "en";

export type WhyStrings = {
  hook: {
    line1: string;
    line2: string;
    sub: string;
  };
  painTyping: {
    overline: string;
    user1: string;
    ai1: string;
    user2: string;
    ai2: string;
    annotation: string;
  };
  painList: {
    overline: string;
    title: string;
    items: [string, string, string, string];
  };
  reveal: {
    pre: string;
    brand: string;
    sub: string;
  };
  anatomy: {
    overline: string;
    title: string;
    pieces: Array<{ label: string; desc: string }>;
    glueLine: string;
  };
  sideBySide: {
    overline: string;
    leftTitle: string;
    rightTitle: string;
    leftChat: Array<{ role: "user" | "ai"; text: string }>;
    rightChat: Array<{ role: "user" | "ai"; text: string }>;
    leftBadge: string;
    rightBadge: string;
  };
  productivity: {
    overline: string;
    title: string;
    metrics: Array<{ value: string; label: string }>;
  };
  multiAgent: {
    overline: string;
    title: string;
    sub: string;
    centerLabel: string;
  };
  cta: {
    title: string;
    command: string;
    repo: string;
    footer: string;
  };
  sceneLabels: [
    string,
    string,
    string,
    string,
    string,
    string,
    string,
    string,
    string,
  ];
};

export const STRINGS_WHY: Record<Lang, WhyStrings> = {
  pt: {
    hook: {
      line1: "Você já mandou a IA fazer algo",
      line2: "e ela inventou tudo?",
      sub: "ou pediu contexto que você já tinha colado três vezes...",
    },
    painTyping: {
      overline: "01 — Sem contexto",
      user1: "como esse projeto funciona?",
      ai1: "preciso de mais contexto — manda a estrutura, padrões e stack",
      user2: "cola README + tsconfig + package.json...",
      ai2: "ok, vou usar express na rota /v2/users com mongoose",
      annotation: "mas o projeto é fastify + prisma...",
    },
    painList: {
      overline: "02 — As 4 dores",
      title: "Por que IA falha em projeto real?",
      items: [
        "Contexto repetido 10x ao dia",
        "Padrões inventados que não existem",
        "Sem testes obrigatórios — quebra silencioso",
        "Cada IA reinventa a roda — Claude, Codex, Copilot",
      ],
    },
    reveal: {
      pre: "E se a IA já soubesse de tudo?",
      brand: "llm-project-mapper",
      sub: "um padrão que faz qualquer agente entender o projeto na primeira mensagem",
    },
    anatomy: {
      overline: "03 — Como funciona",
      title: "Quatro peças, um contrato",
      pieces: [
        {
          label: "AGENTS.md",
          desc: "stack, comandos, padrões, proibições — lido por TODA IA",
        },
        {
          label: ".specs/",
          desc: "specs como código: vision, ADRs, sprints, tasks",
        },
        {
          label: ".skills/",
          desc: "capacidades reutilizáveis: como testar, commitar, etc",
        },
        {
          label: ".claude/hooks/",
          desc: "automação: lint pré-commit, DoD bloqueia merge ruim",
        },
      ],
      glueLine: "Tudo versionado. Tudo lido pelo agente. Tudo bloqueia merge se quebrar.",
    },
    sideBySide: {
      overline: "04 — Antes vs depois",
      leftTitle: "Sem llm-project-mapper",
      rightTitle: "Com llm-project-mapper",
      leftChat: [
        { role: "user", text: "implementa o login" },
        { role: "ai", text: "qual stack? qual padrão de auth?" },
        { role: "user", text: "fastify + JWT, ver controllers/" },
        { role: "ai", text: "qual o padrão de teste?" },
        { role: "user", text: "playwright, ver tests/" },
        { role: "ai", text: "qual o naming? como commito?" },
      ],
      rightChat: [
        { role: "user", text: "implementa o login" },
        { role: "ai", text: "lido AGENTS.md + .specs/auth-flow" },
        { role: "ai", text: "feature/AUTH-42-login + 3 testes E2E" },
        { role: "ai", text: "commit feat(auth): add login + PR aberto" },
        { role: "ai", text: "DoD verde — pronto pra revisar" },
      ],
      leftBadge: "6+ perguntas",
      rightBadge: "0 perguntas",
    },
    productivity: {
      overline: "05 — Ganho real",
      title: "O que muda no dia a dia",
      metrics: [
        { value: "-90%", label: "contexto repetido por dia" },
        { value: "100%", label: "tasks com teste E2E + evidência" },
        { value: "0", label: "merges quebrados (DoD bloqueia)" },
      ],
    },
    multiAgent: {
      overline: "06 — Multi-agent",
      title: "Mesmo contrato. Qualquer agente.",
      sub: "Claude, Codex, Copilot, Cursor, Aider, Simplicio Agent, OpenClaw — todos leem o mesmo AGENTS.md",
      centerLabel: "AGENTS.md",
    },
    cta: {
      title: "Começa em 30 segundos.",
      command: "npx @wesleysimplicio/llm-project-mapper init",
      repo: "github.com/wesleysimplicio/llm-project-mapper",
      footer: "llm-project-mapper · pare de explicar seu projeto pra IA",
    },
    sceneLabels: [
      "Hook",
      "Dor 1",
      "Dor 2",
      "Solução",
      "Anatomia",
      "Antes vs Depois",
      "Ganho",
      "Multi-agent",
      "CTA",
    ],
  },
  en: {
    hook: {
      line1: "Ever asked AI to do something",
      line2: "and it just made stuff up?",
      sub: "or asked for context you've already pasted three times...",
    },
    painTyping: {
      overline: "01 — No context",
      user1: "how does this project work?",
      ai1: "I need more context — send the structure, patterns and stack",
      user2: "pastes README + tsconfig + package.json...",
      ai2: "ok, I'll use express on /v2/users with mongoose",
      annotation: "but the project is fastify + prisma...",
    },
    painList: {
      overline: "02 — The 4 pains",
      title: "Why does AI fail on real projects?",
      items: [
        "Context repeated 10x a day",
        "Invented patterns that don't exist",
        "No mandatory tests — silent breakage",
        "Each AI reinvents the wheel — Claude, Codex, Copilot",
      ],
    },
    reveal: {
      pre: "What if AI already knew everything?",
      brand: "llm-project-mapper",
      sub: "a standard that lets any agent understand the project on the first message",
    },
    anatomy: {
      overline: "03 — How it works",
      title: "Four pieces, one contract",
      pieces: [
        {
          label: "AGENTS.md",
          desc: "stack, commands, patterns, no-gos — read by EVERY AI",
        },
        {
          label: ".specs/",
          desc: "specs as code: vision, ADRs, sprints, tasks",
        },
        {
          label: ".skills/",
          desc: "reusable capabilities: how to test, commit, etc",
        },
        {
          label: ".claude/hooks/",
          desc: "automation: lint pre-commit, DoD blocks bad merges",
        },
      ],
      glueLine: "Versioned. Read by the agent. Blocks merge if broken.",
    },
    sideBySide: {
      overline: "04 — Before vs after",
      leftTitle: "Without llm-project-mapper",
      rightTitle: "With llm-project-mapper",
      leftChat: [
        { role: "user", text: "implement login" },
        { role: "ai", text: "which stack? auth pattern?" },
        { role: "user", text: "fastify + JWT, see controllers/" },
        { role: "ai", text: "what's the test pattern?" },
        { role: "user", text: "playwright, see tests/" },
        { role: "ai", text: "naming? how to commit?" },
      ],
      rightChat: [
        { role: "user", text: "implement login" },
        { role: "ai", text: "read AGENTS.md + .specs/auth-flow" },
        { role: "ai", text: "feature/AUTH-42-login + 3 E2E tests" },
        { role: "ai", text: "commit feat(auth): add login + PR opened" },
        { role: "ai", text: "DoD green — ready for review" },
      ],
      leftBadge: "6+ questions",
      rightBadge: "0 questions",
    },
    productivity: {
      overline: "05 — Real gain",
      title: "What changes day to day",
      metrics: [
        { value: "-90%", label: "context repeated per day" },
        { value: "100%", label: "tasks with E2E test + evidence" },
        { value: "0", label: "broken merges (DoD blocks)" },
      ],
    },
    multiAgent: {
      overline: "06 — Multi-agent",
      title: "Same contract. Any agent.",
      sub: "Claude, Codex, Copilot, Cursor, Aider, Simplicio Agent, OpenClaw — all read the same AGENTS.md",
      centerLabel: "AGENTS.md",
    },
    cta: {
      title: "Start in 30 seconds.",
      command: "npx @wesleysimplicio/llm-project-mapper init",
      repo: "github.com/wesleysimplicio/llm-project-mapper",
      footer: "llm-project-mapper · stop explaining your project to AI",
    },
    sceneLabels: [
      "Hook",
      "Pain 1",
      "Pain 2",
      "Solution",
      "Anatomy",
      "Before vs After",
      "Gain",
      "Multi-agent",
      "CTA",
    ],
  },
};
