# php-symfony

PHP 8.3 + Symfony 7 scaffold for conventional service or API applications with
controllers, dependency injection, and Composer-managed structure.

## When to use this stack

- Symfony ecosystem is the team default
- API or server-rendered app needs mature framework conventions
- Dependency injection and bundles are desired from the start

## Layout produced

```
<project_name>/
|-- src/Controller/HealthController.php
|-- tests/HealthControllerTest.php
|-- composer.json
`-- README.md
```

## Verify loop

- `install`: `composer install`
- `test`: `vendor/bin/phpunit`
- `lint`: `php -l src/Controller/HealthController.php`
