using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// The result of evaluating a feature flag for a specific user.
/// </summary>
public class FlagEvaluationResult
{
    /// <summary>Whether the flag is enabled for this user.</summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>The variant key assigned to this user, or null if not in rollout / flag disabled.</summary>
    [JsonPropertyName("variant")]
    public string? Variant { get; set; }

    /// <summary>The variant payload value, or the default value if the flag is not enabled.</summary>
    [JsonPropertyName("value")]
    public object? Value { get; set; }
}
