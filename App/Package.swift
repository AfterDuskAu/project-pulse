// swift-tools-version: 6.0
// Pulse: the Mac app. PulseCore holds the data, comments and schedule (tested); Pulse is the window.
import PackageDescription

let package = Package(
    name: "Pulse",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "Pulse", targets: ["Pulse"])],
    targets: [
        .target(name: "PulseCore"),
        .executableTarget(name: "Pulse", dependencies: ["PulseCore"]),
        .testTarget(name: "PulseCoreTests", dependencies: ["PulseCore"]),
    ],
    swiftLanguageModes: [.v5]
)
