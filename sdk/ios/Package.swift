// swift-tools-version:5.5
import PackageDescription

let package = Package(
    name: "Experimently",
    platforms: [
        .iOS(.v14),
        .macOS(.v11)
    ],
    products: [
        .library(
            name: "Experimently",
            targets: ["Experimently"]
        ),
        // Contract smoke against a live backend: `swift run contract-smoke`.
        .executable(
            name: "contract-smoke",
            targets: ["contract-smoke"]
        )
    ],
    targets: [
        .target(
            name: "Experimently",
            dependencies: [],
            path: "Sources/Experimently"
        ),
        .executableTarget(
            name: "contract-smoke",
            dependencies: ["Experimently"],
            path: "Sources/contract-smoke"
        ),
        .testTarget(
            name: "ExperimentlyTests",
            dependencies: ["Experimently"],
            path: "Tests/ExperimentlyTests"
        )
    ]
)
