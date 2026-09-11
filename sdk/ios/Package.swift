// swift-tools-version:5.5
import PackageDescription

let package = Package(
    name: "ExperimentationSDK",
    platforms: [
        .iOS(.v14),
        .macOS(.v11)
    ],
    products: [
        .library(
            name: "ExperimentationSDK",
            targets: ["ExperimentationSDK"]
        ),
        // Contract smoke against a live backend: `swift run contract-smoke`.
        .executable(
            name: "contract-smoke",
            targets: ["contract-smoke"]
        )
    ],
    targets: [
        .target(
            name: "ExperimentationSDK",
            dependencies: [],
            path: "Sources/ExperimentationSDK"
        ),
        .executableTarget(
            name: "contract-smoke",
            dependencies: ["ExperimentationSDK"],
            path: "Sources/contract-smoke"
        ),
        .testTarget(
            name: "ExperimentationSDKTests",
            dependencies: ["ExperimentationSDK"],
            path: "Tests/ExperimentationSDKTests"
        )
    ]
)
