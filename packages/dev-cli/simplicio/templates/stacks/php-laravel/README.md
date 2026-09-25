# php-laravel

PHP 8.3 + Laravel scaffold for API-first applications where the team wants
Laravel conventions, Composer packages, and PHPUnit feature tests.

## When to use this stack

- Laravel or PHP team conventions are required
- Backend API needs routing, controllers, validation, and feature tests
- Project expects Composer packages and Artisan workflows
- CRUD admin or business workflow service with conventional MVC boundaries

## When NOT to use this stack

- SSR React application - use `ts-nextjs`
- Systems programming or compact static service - use `rust-axum` or `go-gin`
- Python-first integrations - use `py-fastapi`

## Layout produced

```
<project_name>/
+-- app/Http/Controllers/
+-- bootstrap/app.php
+-- routes/api.php
+-- tests/Feature/
+-- composer.json
+-- artisan
```

## Verify-loop

- `install`: `composer install`
- `test`:    `php vendor/bin/phpunit --configuration phpunit.xml`
- `lint`:    `php vendor/bin/pint --test`
