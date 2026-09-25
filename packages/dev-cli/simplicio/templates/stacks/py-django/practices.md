# py-django best practices

## Project structure
- Keep project configuration in `config/`.
- Keep the first domain app in `app/`; split apps only when ownership differs.
- Put serializers and viewsets next to the models they expose.

## API design
- Use Django REST Framework serializers for request and response validation.
- Use class-based viewsets for CRUD resources and explicit function views for
  narrow health or webhook endpoints.
- Keep migrations small and committed with the model change.

## Testing
- Use Django's `TestCase` or `APITestCase` for database-backed behavior.
- Test URLs and serializers, not only model methods.
- Keep settings deterministic for CI and local scratch verification.

## Dependencies discipline
- Add DRF when exposing JSON APIs; do not mix unrelated API frameworks.
- Keep environment-specific settings outside source code.
