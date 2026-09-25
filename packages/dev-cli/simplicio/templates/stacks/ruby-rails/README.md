# ruby-rails

Ruby 3.3 + Rails 7 scaffold for conventional MVC apps and JSON APIs.

## When to use this stack

- CRUD-heavy product app with Rails conventions
- Team wants Active Record, routing, jobs, and tests from one framework
- Server-rendered app or JSON API in Ruby

## Layout produced

```
<project_name>/
|-- bin/rails
|-- app/controllers/health_controller.rb
|-- test/controllers/health_controller_test.rb
|-- Gemfile
`-- README.md
```

## Verify loop

- `install`: `bundle install`
- `test`: `bin/rails test`
- `lint`: `bundle exec rubocop`
