// BasicUsage — demonstrates the ExperimentationPlatform .NET SDK
//
// To run:
//   cd sdk/dotnet/examples/BasicUsage
//   dotnet run
//
// Set your actual API base URL and key via environment variables or replace the constants below.

using ExperimentationPlatform;
using ExperimentationPlatform.Models;

// -----------------------------------------------------------------
// 1. Configure the SDK
// -----------------------------------------------------------------
const string BaseUrl = "https://your-api.example.com";  // override with EP_BASE_URL env var
const string ApiKey  = "your-api-key-here";              // override with EP_API_KEY env var

var baseUrl = Environment.GetEnvironmentVariable("EP_BASE_URL") ?? BaseUrl;
var apiKey  = Environment.GetEnvironmentVariable("EP_API_KEY")  ?? ApiKey;

var config = new SdkConfig(baseUrl, apiKey)
{
    CacheTtlSeconds = 300,   // cache flags for 5 minutes
    TimeoutSeconds  = 10,    // HTTP timeout
    MaxCacheSize    = 1000   // max in-memory cached flags
};

using var client = new ExperimentationClient(config);

// -----------------------------------------------------------------
// 2. Evaluate a feature flag
// -----------------------------------------------------------------
Console.WriteLine("=== Feature Flag Evaluation ===");

var userId = "user-42";
var flagResult = await client.EvaluateFlagAsync(
    flagKey: "new-checkout-ui",
    userId: userId,
    attributes: new Dictionary<string, object> { { "country", "US" }, { "plan", "pro" } },
    defaultValue: false);

Console.WriteLine($"Flag 'new-checkout-ui' for user '{userId}':");
Console.WriteLine($"  Enabled  : {flagResult.Enabled}");
Console.WriteLine($"  Variant  : {flagResult.Variant ?? "(none)"}");
Console.WriteLine($"  Value    : {flagResult.Value}");

// -----------------------------------------------------------------
// 3. Get an experiment assignment
// -----------------------------------------------------------------
Console.WriteLine();
Console.WriteLine("=== Experiment Assignment ===");

var assignment = await client.GetAssignmentAsync(
    experimentKey: "checkout-cta-test",
    userId: userId);

if (assignment != null)
{
    Console.WriteLine($"Experiment 'checkout-cta-test' for user '{userId}':");
    Console.WriteLine($"  InExperiment : {assignment.IsInExperiment}");
    Console.WriteLine($"  Variant      : {assignment.Variant?.Key ?? "(not assigned)"}");
}
else
{
    Console.WriteLine("Could not retrieve assignment (check that the experiment exists and API is reachable).");
}

// -----------------------------------------------------------------
// 4. Track an event
// -----------------------------------------------------------------
Console.WriteLine();
Console.WriteLine("=== Event Tracking ===");

bool tracked = await client.TrackAsync(
    eventName: "checkout_started",
    userId: userId,
    properties: new Dictionary<string, object>
    {
        { "cart_total", 129.99 },
        { "item_count", 3 },
        { "currency", "USD" }
    });

Console.WriteLine($"Event 'checkout_started' tracked: {tracked}");

// -----------------------------------------------------------------
// 5. Local hash parity demo — no network needed
// -----------------------------------------------------------------
Console.WriteLine();
Console.WriteLine("=== Local Hash Parity ===");

double hashResult = FeatureFlagEvaluator.HashUser("user-123", "my-flag");
double expected   = 0.6927449859213084;
bool   matches    = Math.Abs(hashResult - expected) < 1e-10;

Console.WriteLine($"HashUser(\"user-123\", \"my-flag\") = {hashResult}");
Console.WriteLine($"Expected                            = {expected}");
Console.WriteLine($"Cross-SDK parity: {(matches ? "PASS" : "FAIL")}");
