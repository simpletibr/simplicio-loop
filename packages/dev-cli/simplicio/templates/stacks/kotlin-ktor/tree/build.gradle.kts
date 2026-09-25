plugins {
    kotlin("jvm") version "2.0.20"
    application
}

application {
    mainClass.set("com.example.ApplicationKt")
}

dependencies {
    implementation("io.ktor:ktor-server-core-jvm:3.0.0")
    implementation("io.ktor:ktor-server-netty-jvm:3.0.0")
    testImplementation("io.ktor:ktor-server-test-host-jvm:3.0.0")
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}
