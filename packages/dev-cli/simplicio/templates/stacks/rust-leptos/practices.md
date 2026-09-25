# rust-leptos best practices

## Project structure
- Keep route components small and split shared UI once reused.
- Keep server functions near the UI that calls them until boundaries appear.
- Prefer typed resources over ad hoc JSON handling.

## UI design
- Keep initial render useful without client-only state.
- Avoid large global signals; scope state to components.
- Use server-side validation for forms.

## Testing
- Unit-test pure formatting and domain functions.
- Add browser or hydration tests once interactions grow.
- Run Clippy with warnings denied before release.

## Dependencies discipline
- Keep feature flags explicit.
- Avoid adding client-side packages until Rust-side options are insufficient.
