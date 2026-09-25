# ts-remix

TypeScript + Remix 2 scaffold for server-rendered React apps with route modules,
loaders, actions, and progressive enhancement.

## When to use this stack

- SSR React app where data loading belongs with routes
- Form-heavy product UI that benefits from Remix actions
- Team wants web-platform primitives instead of a custom API layer

## Layout produced

```
<project_name>/
|-- app/root.tsx
|-- app/routes/_index.tsx
|-- package.json
`-- README.md
```

## Verify loop

- `install`: `npm install`
- `test`: `npm test`
- `lint`: `npm run lint`
- `build`: `npm run build`
