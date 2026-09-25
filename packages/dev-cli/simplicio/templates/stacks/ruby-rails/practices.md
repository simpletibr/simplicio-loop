# ruby-rails best practices

## Project structure
- Keep controllers thin and move business behavior to models or service objects.
- Use RESTful routes unless a domain action is clearly not CRUD.
- Keep migrations small and reversible.

## API design
- Return JSON from API controllers with explicit status codes.
- Use strong parameters for request filtering.
- Keep serializers explicit when response shape matters.

## Testing
- Use Rails tests for controller and model behavior.
- Keep fixture data minimal.
- Run RuboCop before release.

## Dependencies discipline
- Add gems only when Rails does not already provide the behavior.
- Keep framework monkey patches out of initial scaffolds.
