import SwiftUI
import ExperimentationSDK

// MARK: - App Entry Point

@main
struct ExampleApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

// MARK: - Content View

struct ContentView: View {
    @State private var flagEnabled = false
    @State private var variant = ""
    @State private var statusMessage = "Tap 'Evaluate Flag' to begin."
    @State private var isLoading = false

    // Initialize the SDK client with your base URL and API key.
    // In production, load these from a configuration file or environment.
    private let client = ExperimentationClient(
        baseURL: "http://localhost:8000",
        apiKey: "your-api-key"
    )

    // A fixed user for the demo. In production, use the authenticated user's ID.
    private let user = User(id: "user-123", attributes: ["plan": "pro"])

    var body: some View {
        NavigationView {
            VStack(spacing: 24) {

                // Flag status indicator
                VStack(spacing: 8) {
                    Text("Feature Flag Status")
                        .font(.headline)
                        .foregroundColor(.secondary)

                    Text(flagEnabled ? "ENABLED" : "DISABLED")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                        .foregroundColor(flagEnabled ? .green : .red)
                        .animation(.spring(), value: flagEnabled)
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(Color(.systemGray6))
                .cornerRadius(12)

                // Variant display
                if !variant.isEmpty {
                    VStack(spacing: 4) {
                        Text("Assigned Variant")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                        Text(variant)
                            .font(.title3)
                            .fontWeight(.semibold)
                            .foregroundColor(.blue)
                    }
                }

                // Status / error message
                Text(statusMessage)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)

                Divider()

                // Action buttons
                VStack(spacing: 12) {
                    Button(action: evaluateFlag) {
                        HStack {
                            if isLoading {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                    .scaleEffect(0.8)
                            }
                            Text("Evaluate Flag")
                                .fontWeight(.semibold)
                        }
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.blue)
                        .foregroundColor(.white)
                        .cornerRadius(10)
                    }
                    .disabled(isLoading)

                    Button(action: refreshAllFlags) {
                        Text("Refresh All Flags")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color(.systemGray5))
                            .foregroundColor(.primary)
                            .cornerRadius(10)
                    }
                    .disabled(isLoading)

                    Button(action: trackEvent) {
                        Text("Track 'button_tapped' Event")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color(.systemGray5))
                            .foregroundColor(.primary)
                            .cornerRadius(10)
                    }
                    .disabled(isLoading)
                }

                Spacer()

                Text("Experimentation SDK Demo\nUser: \(user.id)")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding()
            .navigationTitle("SDK Demo")
        }
    }

    // MARK: - Actions

    private func evaluateFlag() {
        isLoading = true
        statusMessage = "Evaluating..."

        Task {
            defer { isLoading = false }
            do {
                let result = try await client.evaluateFlag("new-feature", user: user)
                await MainActor.run {
                    flagEnabled = result.enabled
                    variant = result.variantKey ?? ""
                    statusMessage = "Evaluated successfully. Reason: \(result.reason)"
                }
            } catch {
                await MainActor.run {
                    statusMessage = "Error: \(error.localizedDescription)"
                }
            }
        }
    }

    private func refreshAllFlags() {
        isLoading = true
        statusMessage = "Refreshing flags..."

        Task {
            defer { isLoading = false }
            do {
                try await client.refreshFlags()
                await MainActor.run {
                    statusMessage = "All flags refreshed and cached locally."
                }
            } catch {
                await MainActor.run {
                    statusMessage = "Refresh error: \(error.localizedDescription)"
                }
            }
        }
    }

    private func trackEvent() {
        Task {
            do {
                let event = TrackEvent(
                    userId: user.id,
                    eventName: "button_tapped",
                    properties: ["screen": "demo", "timestamp": Int(Date().timeIntervalSince1970)]
                )
                try await client.track(event)
                await MainActor.run {
                    statusMessage = "Event 'button_tapped' tracked successfully."
                }
            } catch {
                await MainActor.run {
                    statusMessage = "Track error: \(error.localizedDescription)"
                }
            }
        }
    }
}

// MARK: - Preview

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
