# kotlin-ktor

Kotlin + Ktor scaffold for compact asynchronous JVM HTTP services.

## When to use this stack

- Kotlin service with lightweight HTTP routing
- Team wants explicit routing without Spring Boot
- Async JVM deployment is the target

## Layout produced

```
<project_name>/
|-- build.gradle.kts
|-- src/main/kotlin/com/example/Application.kt
|-- src/test/kotlin/com/example/ApplicationTest.kt
`-- README.md
```

## Verify loop

- `install`: `./gradlew dependencies`
- `test`: `./gradlew test`
- `lint`: `./gradlew check`
