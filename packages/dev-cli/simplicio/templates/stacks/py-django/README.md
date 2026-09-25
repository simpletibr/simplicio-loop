# py-django

Python 3.12 + Django 5 + Django REST Framework scaffold for CRUD-heavy server
apps that benefit from Django's ORM, admin, migrations, and batteries-included
project layout.

## When to use this stack

- Back-office app with models, auth, admin, and CRUD workflows
- REST API where Django ORM and migrations are the desired foundation
- Team wants conventional Django project structure

## Layout produced

```
<project_name>/
|-- manage.py
|-- config/
|-- app/
|-- pyproject.toml
`-- README.md
```

## Verify loop

- `install`: `python3 -m pip install -e .[dev]`
- `test`: `python manage.py test`
- `lint`: `ruff check app config`
