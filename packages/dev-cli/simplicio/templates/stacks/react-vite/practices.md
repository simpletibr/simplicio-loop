# react-vite best practices

## Project structure
- Keep domain components in `src/` and split routes only when navigation exists.
- Keep API clients separate from components.
- Keep global CSS small; prefer component-local classes.

## UI design
- Keep first screen usable, not a marketing shell.
- Use semantic buttons, labels, and form controls.
- Avoid hidden state that cannot be tested from the DOM.

## Testing
- Use Vitest with Testing Library for component behavior.
- Assert visible UI and user flows rather than implementation details.
- Keep build and test commands both green before publishing.

## Dependencies discipline
- Add state libraries only after props/context become insufficient.
- Keep Vite config explicit and small.
