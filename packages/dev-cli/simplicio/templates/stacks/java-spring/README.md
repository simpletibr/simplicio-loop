# java-spring

Java 21 + Spring Boot 3 scaffold for JVM HTTP APIs with conventional
controllers, dependency injection, and Gradle builds.

## When to use this stack

- Enterprise Java service or API
- Team standardizes on Spring Boot
- Strong JVM ecosystem and typed dependency injection are desired

## Layout produced

```
<project_name>/
|-- build.gradle.kts
|-- src/main/java/com/example/Application.java
|-- src/main/java/com/example/HealthController.java
`-- README.md
```

## Verify loop

- `install`: `./gradlew dependencies`
- `test`: `./gradlew test`
- `lint`: `./gradlew check`
