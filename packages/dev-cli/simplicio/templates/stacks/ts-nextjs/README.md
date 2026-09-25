# ts-nextjs

TypeScript 5 + Next.js 14 app router. SSR-ready, React 18, TypeScript for
compile checks, Playwright for e2e, eslint for lint.

## When to use
- Full-stack web app with SSR / SSG
- React-based UI is desired or required
- Want streaming, server actions, edge functions

## When NOT to use
- Backend-only API service — use `py-fastapi` or `go-gin`
- Mobile app — use `kotlin-android` / `swift-ios` / `dart-flutter`
- SPA without SSR — use `react-vite` instead (Next.js is overkill)

## Layout
```
<project_name>/
├── src/
│   ├── app/              # app router pages + route handlers
│   ├── lib/              # shared utilities (db client, auth, etc.)
│   └── components/       # React components
├── tests/                # vitest unit + integration
├── playwright/           # e2e specs
├── package.json
├── pnpm-workspace.yaml
├── tsconfig.json
├── next.config.mjs
├── .eslintrc.json
└── README.md
```

## Verify-loop
- `install`: `pnpm install`
- `test`:    `pnpm tsc --noEmit`
- `lint`:    `pnpm eslint .`
