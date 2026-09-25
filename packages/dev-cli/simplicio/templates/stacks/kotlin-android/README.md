# kotlin-android

Kotlin + Jetpack Compose scaffold for native Android applications.

## When to use this stack

- Native Android app with Compose UI
- Kotlin-first mobile team
- Android Gradle Plugin and emulator/device tests are expected

## Layout produced

```
<project_name>/
|-- settings.gradle.kts
|-- build.gradle.kts
|-- app/build.gradle.kts
|-- app/src/main/java/com/example/MainActivity.kt
`-- README.md
```

## Verify loop

- `install`: `./gradlew dependencies`
- `test`: `./gradlew test`
- `lint`: `./gradlew lint`
