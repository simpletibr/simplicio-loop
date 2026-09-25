# kotlin-spring

Kotlin + Spring Boot 3 scaffold for JVM APIs with concise controllers and
Spring's dependency injection model.

## When to use this stack

- Kotlin-first backend team
- Spring Boot ecosystem is desired
- Typed API services with JVM deployment

## Layout produced

```
<project_name>/
|-- build.gradle.kts
|-- src/main/kotlin/com/example/Application.kt
|-- src/main/kotlin/com/example/HealthController.kt
`-- README.md
```

## Verify loop

- `install`: `./gradlew dependencies`
- `test`: `./gradlew test`
- `lint`: `./gradlew check`
