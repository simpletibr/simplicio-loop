# php-laravel best practices (planner reference)

## Project structure

- Put HTTP controllers under `app/Http/Controllers`.
- Register API routes in `routes/api.php`.
- Keep request validation close to controllers until a form request class is
  actually reused.
- Use feature tests under `tests/Feature` for API behavior.

## API design

- Return JSON responses with explicit status codes.
- Keep route names resource-oriented: `units.index`, `units.store`.
- Prefer Laravel validation helpers before mutating state.
- Keep Eloquent model tasks separate from controller and route tasks.

## Testing

- Use `php vendor/bin/phpunit --configuration phpunit.xml` as the default
  verification command for the minimal scaffold.
- Feature tests should call JSON endpoints and assert status plus response
  shape.
- Every route task should add or update a focused feature test.

## Output the planner SHOULD produce for this stack

- Tasks order: route -> controller -> model/request -> feature test.
- Each task touches ONE file.
- `test_command` = `php vendor/bin/phpunit --configuration phpunit.xml`
- `lint_command` = `php vendor/bin/pint --test`
