// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "{project_name}",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.100.0")
    ],
    targets: [
        .executableTarget(
            name: "App",
            dependencies: [.product(name: "Vapor", package: "vapor")]
        ),
        .testTarget(name: "AppTests", dependencies: ["App"])
    ]
)
