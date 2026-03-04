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
        )
    ],
    targets: [
        .target(
            name: "ExperimentationSDK",
            dependencies: [],
            path: "Sources/ExperimentationSDK"
        ),
        .testTarget(
            name: "ExperimentationSDKTests",
            dependencies: ["ExperimentationSDK"],
            path: "Tests/ExperimentationSDKTests"
        )
    ]
)
