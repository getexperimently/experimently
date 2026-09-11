using System.Text.Json;
using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// The server's decision for one feature flag and one user
/// (<c>GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…</c>).
/// </summary>
public class FlagEvaluationResult
{
    /// <summary>The evaluated flag key.</summary>
    [JsonPropertyName("key")]
    public string Key { get; set; } = "";

    /// <summary>Whether the flag is enabled for this user (decided by the server).</summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>
    /// The flag's <c>config</c> payload as returned by the server — any JSON value — or
    /// <c>null</c>. For an object payload use e.g.
    /// <c>result.Config?.GetProperty("variant").GetString()</c>.
    /// </summary>
    [JsonPropertyName("config")]
    public JsonElement? Config { get; set; }

    /// <summary>The idiomatic "unknown" result returned when a request fails and nothing is cached.</summary>
    public static FlagEvaluationResult Disabled(string flagKey) =>
        new() { Key = flagKey, Enabled = false, Config = null };
}
