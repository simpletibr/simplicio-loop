# swift-ios

Swift 5 + SwiftUI scaffold for native iOS applications.

## When to use this stack

- Native iOS app with SwiftUI screens
- Apple platform integration is required
- Xcode build and test are the release gate

## Layout produced

```
<project_name>/
|-- Sources/App/App.swift
|-- Sources/App/ContentView.swift
|-- Tests/AppTests/AppTests.swift
`-- README.md
```

## Verify loop

- `install`: `xcodebuild -resolvePackageDependencies`
- `test`: `xcodebuild test`
- `lint`: `swift-format lint Sources`
