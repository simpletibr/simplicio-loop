# php-vanilla best practices

## Project structure
- Use PSR-4 autoloading from `src/`.
- Keep tests under `tests/` with matching class names.
- Keep framework adapters outside domain classes.

## PHP design
- Use strict types on every PHP file.
- Prefer readonly value objects for immutable data.
- Return typed values instead of arrays when structure matters.

## Testing
- Use PHPUnit for unit behavior.
- Keep fixtures small and local to each test.
- Run Pint in test mode before committing.

## Dependencies discipline
- Add Composer packages only when they remove real complexity.
- Keep dev-only packages under `require-dev`.
