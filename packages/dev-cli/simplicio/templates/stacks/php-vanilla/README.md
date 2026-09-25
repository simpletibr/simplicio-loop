# php-vanilla

PHP 8.3 + Composer + PHPUnit scaffold for small libraries, scripts, and domain
modules that do not need a full framework.

## When to use this stack

- Plain PHP package or service component
- Existing application wants a focused module with tests
- Framework overhead is not needed

## Layout produced

```
<project_name>/
|-- src/Health.php
|-- tests/HealthTest.php
|-- composer.json
|-- phpunit.xml
`-- README.md
```

## Verify loop

- `install`: `composer install`
- `test`: `vendor/bin/phpunit --configuration phpunit.xml`
- `lint`: `vendor/bin/pint --test`
