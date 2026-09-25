export type Lang = "pt" | "en";

type Strings = {
  intro: {
    title: string;
    taglinePre: string;
    taglineMid: string;
    taglinePost: string;
  };
  whatAreSkills: {
    overline: string;
    title: string;
    cardTitle: string;
    cardBody: string[];
    pathLabel: string;
    pillTitles: [string, string, string];
    pillBodies: [string, string, string];
    paper: {
      descValue: string;
      triggerExample: string;
      step1: string;
      step2: string;
      dodItem: string;
    };
  };
  catalog: {
    overline: string;
    title: string;
    skillDescs: [string, string, string];
    footerPrefix: string;
    footerLocalLabel: string;
    footerLocalSep: string;
    footerGlobalLabel: string;
  };
  playwright: {
    overline: string;
    triggerLabel: string;
    triggerBody: string[];
    hardRuleLabel: string;
    hardRuleBody: string[];
    patternsLabel: string;
    patternsGoodBody: string;
    patternsBadBody: string;
    codeComment: string;
    evidenceLabels: [string, string, string, string];
  };
  commits: {
    overline: string;
    typeDescs: Record<string, string>;
    breakingTitle: string;
    breakingFooter: string;
    breakingFooterImpact: string;
    semverNote: string[];
  };
  howToInvoke: {
    overline: string;
    title: string;
    mode: [string, string];
    modeBadge: [string, string];
    modeSubtitle: [string, string];
    explicit: { prompt: string; load: string; ok: string; create: string };
    implicit: { prompt: string; match: string; ok: string; ready: string };
    hintBody: string[];
    hintHighlight: string;
  };
  createYourOwn: {
    overline: string;
    title: string;
    steps: Array<{ title: string; body: string[] }>;
    terminal: { title: string; lines: Array<{ type: string; text: string }> };
    codeTitle: string;
    codeDescription: string;
  };
  bestPractices: {
    overline: string;
    title: string;
    tips: Array<{ title: string; body: string }>;
    notForLabel: string;
    notForBody: string[];
  };
  outro: {
    title: string;
    subtitlePre: string;
    subtitleMid: string;
    subtitlePost: string;
    pills: [string, string, string, string, string];
    ctaCommand: string;
    ctaLine: string;
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

export const STRINGS: Record<Lang, Strings> = {
  pt: {
    intro: {
      title: "Skills",
      taglinePre: "Como usar as ",
      taglineMid: "capacidades reutilizáveis",
      taglinePost: "do llm-project-mapper",
    },
    whatAreSkills: {
      overline: "01 — Conceito",
      title: "O que é uma Skill?",
      cardTitle: "📘 Definição",
      cardBody: [
        "Skill é um ",
        "manual operacional curto",
        " em Markdown que ensina o agente a executar uma tarefa recorrente do ",
        "jeito certo",
        ".",
      ],
      pathLabel: ".skills/<nome-da-skill>/SKILL.md",
      pillTitles: ["Trigger claro", "30-100 linhas", "DoD verificável"],
      pillBodies: [
        "Ativa por palavra-chave ou descrição",
        "Curta, direta, sem floreio",
        "Checklist objetivo no fim",
      ],
      paper: {
        descValue: '"escrever testes e2e..."',
        triggerExample: "- Quando ativar.",
        step1: "1. Faça X.",
        step2: "2. Faça Y.",
        dodItem: "- [ ] Critério 1",
      },
    },
    catalog: {
      overline: "02 — Catálogo",
      title: "Skills inclusas no starter",
      skillDescs: [
        "Testes end-to-end com trace, screenshot e vídeo",
        "Mensagens de commit padronizadas (SemVer-friendly)",
        "Base para criar suas próprias skills",
      ],
      footerPrefix: "📂 Skills ",
      footerLocalLabel: "locais",
      footerLocalSep: " ficam em ",
      footerGlobalLabel: "globais",
    },
    playwright: {
      overline: "03 · Skill #1",
      triggerLabel: "Trigger",
      triggerBody: [
        "Ativa em ",
        "TODA task técnica",
        " — feature, fix, refactor — antes do commit. Smoke test mínimo se a task não tem UI.",
      ],
      hardRuleLabel: "Hard rule",
      hardRuleBody: [
        "Sem evidência completa ",
        "não tem merge",
        ": trace + screenshot + video em ",
        "playwright-report/",
        ".",
      ],
      patternsLabel: "Padrões-chave",
      patternsGoodBody: "getByRole / getByLabel / getByTestId",
      patternsBadBody: "waitForTimeout / mock pra fazer passar",
      codeComment: "// estado final (auto-retry)",
      evidenceLabels: ["trace.zip", "screenshot.png", "video.webm", "report HTML"],
    },
    commits: {
      overline: "04 · Skill #2",
      typeDescs: {
        feat: "nova feature",
        fix: "correção de bug",
        docs: "documentação",
        refactor: "reestruturação",
        perf: "performance",
        test: "testes",
        build: "build / deps",
        ci: "pipeline",
        chore: "manutenção",
        style: "formatação",
      },
      breakingTitle: "Breaking change?",
      breakingFooter: "ou footer: ",
      breakingFooterImpact: "<impacto>",
      semverNote: [
        "⚙️ habilita changelog automático + version bump por ",
        "SemVer",
      ],
    },
    howToInvoke: {
      overline: "05 — Como invocar",
      title: "Dois jeitos de ativar uma skill",
      mode: ["Trigger explícito", "Trigger implícito"],
      modeBadge: ["MODO 01", "MODO 02"],
      modeSubtitle: [
        "você cita a skill pelo nome",
        "match por description no frontmatter",
      ],
      explicit: {
        prompt: "$playwright-e2e — escreve teste para o fluxo de checkout",
        load: "→ carregando .skills/playwright-e2e/SKILL.md",
        ok: "skill ativa: seguindo Steps 1..10",
        create: "→ criando tests/e2e/checkout.spec.ts",
      },
      implicit: {
        prompt: "faz commit dessas mudanças, por favor",
        match: "→ skill conventional-commits: description casa",
        ok: "padrão aplicado: feat(skills): ...",
        ready: "→ commit pronto pra push",
      },
      hintBody: [
        "O ",
        "description",
        " é o que mais importa: escreva como uma ",
        "query",
        " imaginando como o pedido aparecerá depois.",
      ],
      hintHighlight: "description",
    },
    createYourOwn: {
      overline: "06 — Skill #3",
      title: "Crie a sua própria skill com _template",
      steps: [
        {
          title: "Copie o template",
          body: ["cp -R .skills/_template .skills/<sua-skill>"],
        },
        {
          title: "Preencha o frontmatter",
          body: [
            "name + description (a parte mais importante: é o que dispara o trigger implícito).",
          ],
        },
        {
          title: "Escreva 4 sections",
          body: ["Trigger · Steps · Padrões · Definition of Done"],
        },
        {
          title: "Referencie no README",
          body: ["Adicione a linha em .skills/README.md."],
        },
      ],
      terminal: {
        title: "bash — criando skill nova",
        lines: [
          { type: "prompt", text: "cp -R .skills/_template .skills/db-migration" },
          { type: "ok", text: "skill esqueleto criada" },
          { type: "prompt", text: "$EDITOR .skills/db-migration/SKILL.md" },
          { type: "out", text: "# editando frontmatter + sections..." },
          { type: "prompt", text: "git add .skills/db-migration/" },
          {
            type: "prompt",
            text: 'git commit -m "feat(skills): add db-migration"',
          },
          { type: "ok", text: "skill pronta — agente já pode invocar" },
        ],
      },
      codeTitle: "SKILL.md (frontmatter mínimo)",
      codeDescription: "criar migrations reversíveis com naming consistente",
    },
    bestPractices: {
      overline: "07 — Boas práticas",
      title: "Skills que envelhecem bem",
      tips: [
        {
          title: "Concisão",
          body: "30-100 linhas. Acima vira doc — move pra .specs/.",
        },
        {
          title: "Idempotente",
          body: "Rodar duas vezes = mesmo efeito. Não acumula estado.",
        },
        {
          title: "Single-responsibility",
          body: "Uma skill, uma responsabilidade. Vontade de juntar? Divida.",
        },
        {
          title: "Linguagem direta",
          body: "Verbo no imperativo. Sem floreio, sem rodeio.",
        },
        {
          title: "DoD verificável",
          body: "Checklist booleano no fim — true/false, nunca subjetivo.",
        },
        {
          title: "Exemplos concretos",
          body: "Code blocks com a stack real. Sem pseudocódigo.",
        },
      ],
      notForLabel: "Não crie skill para",
      notForBody: [
        "algo que aparece ",
        "uma única vez",
        " · convenção ",
        "universal",
        " (vai pra global) · conhecimento ",
        "genérico de stack",
      ],
    },
    outro: {
      title: "Agora é com você.",
      subtitlePre: "Skills transformam ",
      subtitleMid: "convenções repetidas",
      subtitlePost: " em superpoderes do agente.",
      pills: [
        "playwright-e2e",
        "conventional-commits",
        "_template",
        "DoD verificável",
        "trigger por description",
      ],
      ctaCommand: "cp -R .skills/_template .skills/<sua-skill>",
      ctaLine: "crie a sua primeira skill agora ⚡",
      footer: "llm-project-mapper · skills tutorial",
    },
    sceneLabels: [
      "Intro",
      "Conceito",
      "Catálogo",
      "playwright-e2e",
      "conventional-commits",
      "Como invocar",
      "Crie a sua",
      "Boas práticas",
      "Encerramento",
    ],
  },
  en: {
    intro: {
      title: "Skills",
      taglinePre: "How to use the ",
      taglineMid: "reusable capabilities",
      taglinePost: "of llm-project-mapper",
    },
    whatAreSkills: {
      overline: "01 — Concept",
      title: "What is a Skill?",
      cardTitle: "📘 Definition",
      cardBody: [
        "A Skill is a ",
        "short operational manual",
        " in Markdown that teaches the agent how to execute a recurring task ",
        "the right way",
        ".",
      ],
      pathLabel: ".skills/<skill-name>/SKILL.md",
      pillTitles: ["Clear trigger", "30-100 lines", "Verifiable DoD"],
      pillBodies: [
        "Activates by keyword or description",
        "Short, direct, no fluff",
        "Objective checklist at the end",
      ],
      paper: {
        descValue: '"write e2e tests..."',
        triggerExample: "- When to activate.",
        step1: "1. Do X.",
        step2: "2. Do Y.",
        dodItem: "- [ ] Criterion 1",
      },
    },
    catalog: {
      overline: "02 — Catalog",
      title: "Skills shipped in the starter",
      skillDescs: [
        "End-to-end tests with trace, screenshot and video",
        "Standardized commit messages (SemVer-friendly)",
        "Base for creating your own skills",
      ],
      footerPrefix: "📂 ",
      footerLocalLabel: "Local",
      footerLocalSep: " skills live in ",
      footerGlobalLabel: "global",
    },
    playwright: {
      overline: "03 · Skill #1",
      triggerLabel: "Trigger",
      triggerBody: [
        "Activates on ",
        "EVERY technical task",
        " — feature, fix, refactor — before commit. Minimum smoke test if the task has no UI.",
      ],
      hardRuleLabel: "Hard rule",
      hardRuleBody: [
        "No full evidence means ",
        "no merge",
        ": trace + screenshot + video in ",
        "playwright-report/",
        ".",
      ],
      patternsLabel: "Key patterns",
      patternsGoodBody: "getByRole / getByLabel / getByTestId",
      patternsBadBody: "waitForTimeout / mock-to-pass",
      codeComment: "// final state (auto-retry)",
      evidenceLabels: ["trace.zip", "screenshot.png", "video.webm", "HTML report"],
    },
    commits: {
      overline: "04 · Skill #2",
      typeDescs: {
        feat: "new feature",
        fix: "bug fix",
        docs: "documentation",
        refactor: "restructuring",
        perf: "performance",
        test: "tests",
        build: "build / deps",
        ci: "pipeline",
        chore: "maintenance",
        style: "formatting",
      },
      breakingTitle: "Breaking change?",
      breakingFooter: "or footer: ",
      breakingFooterImpact: "<impact>",
      semverNote: [
        "⚙️ enables automatic changelog + version bump via ",
        "SemVer",
      ],
    },
    howToInvoke: {
      overline: "05 — How to invoke",
      title: "Two ways to activate a skill",
      mode: ["Explicit trigger", "Implicit trigger"],
      modeBadge: ["MODE 01", "MODE 02"],
      modeSubtitle: [
        "you cite the skill by name",
        "match by description in the frontmatter",
      ],
      explicit: {
        prompt: "$playwright-e2e — write a test for the checkout flow",
        load: "→ loading .skills/playwright-e2e/SKILL.md",
        ok: "skill active: following Steps 1..10",
        create: "→ creating tests/e2e/checkout.spec.ts",
      },
      implicit: {
        prompt: "please commit these changes",
        match: "→ skill conventional-commits: description matches",
        ok: "pattern applied: feat(skills): ...",
        ready: "→ commit ready to push",
      },
      hintBody: [
        "The ",
        "description",
        " is what matters most: write it like a ",
        "query",
        " imagining how the request will appear later.",
      ],
      hintHighlight: "description",
    },
    createYourOwn: {
      overline: "06 — Skill #3",
      title: "Create your own skill with _template",
      steps: [
        {
          title: "Copy the template",
          body: ["cp -R .skills/_template .skills/<your-skill>"],
        },
        {
          title: "Fill the frontmatter",
          body: [
            "name + description (the most important part: it's what triggers the implicit match).",
          ],
        },
        {
          title: "Write 4 sections",
          body: ["Trigger · Steps · Patterns · Definition of Done"],
        },
        {
          title: "Reference it in the README",
          body: ["Add the line to .skills/README.md."],
        },
      ],
      terminal: {
        title: "bash — creating new skill",
        lines: [
          { type: "prompt", text: "cp -R .skills/_template .skills/db-migration" },
          { type: "ok", text: "skill skeleton created" },
          { type: "prompt", text: "$EDITOR .skills/db-migration/SKILL.md" },
          { type: "out", text: "# editing frontmatter + sections..." },
          { type: "prompt", text: "git add .skills/db-migration/" },
          {
            type: "prompt",
            text: 'git commit -m "feat(skills): add db-migration"',
          },
          { type: "ok", text: "skill ready — agent can invoke now" },
        ],
      },
      codeTitle: "SKILL.md (minimal frontmatter)",
      codeDescription: "create reversible migrations with consistent naming",
    },
    bestPractices: {
      overline: "07 — Best practices",
      title: "Skills that age well",
      tips: [
        {
          title: "Concise",
          body: "30-100 lines. More than that is docs — move to .specs/.",
        },
        {
          title: "Idempotent",
          body: "Run twice = same effect. No state accumulation.",
        },
        {
          title: "Single-responsibility",
          body: "One skill, one responsibility. Want to merge? Split.",
        },
        {
          title: "Direct language",
          body: "Imperative verb. No fluff, no rambling.",
        },
        {
          title: "Verifiable DoD",
          body: "Boolean checklist at the end — true/false, never subjective.",
        },
        {
          title: "Concrete examples",
          body: "Code blocks with the real stack. No pseudocode.",
        },
      ],
      notForLabel: "Don't create a skill for",
      notForBody: [
        "something that appears ",
        "only once",
        " · ",
        "universal",
        " convention (goes global) · ",
        "generic stack",
        " knowledge",
      ],
    },
    outro: {
      title: "Now it's up to you.",
      subtitlePre: "Skills turn ",
      subtitleMid: "repeated conventions",
      subtitlePost: " into agent superpowers.",
      pills: [
        "playwright-e2e",
        "conventional-commits",
        "_template",
        "Verifiable DoD",
        "trigger by description",
      ],
      ctaCommand: "cp -R .skills/_template .skills/<your-skill>",
      ctaLine: "ship your first skill today ⚡",
      footer: "llm-project-mapper · skills tutorial",
    },
    sceneLabels: [
      "Intro",
      "Concept",
      "Catalog",
      "playwright-e2e",
      "conventional-commits",
      "How to invoke",
      "Build your own",
      "Best practices",
      "Outro",
    ],
  },
};
