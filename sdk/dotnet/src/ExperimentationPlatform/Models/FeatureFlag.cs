using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// Represents a feature flag retrieved from the Experimentation Platform API.
/// </summary>
public class FeatureFlag
{
    /// <summary>The unique string key identifying this flag.</summary>
    [JsonPropertyName("key")]
    public string Key { get; set; } = "";

    /// <summary>Whether the flag is globally enabled.</summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>The rollout percentage (0–100). Users whose hash bucket is below this value are included.</summary>
    [JsonPropertyName("rollout_percentage")]
    public double RolloutPercentage { get; set; }

    /// <summary>The list of variants for this flag. May be empty for a simple on/off flag.</summary>
    [JsonPropertyName("variants")]
    public List<Variant> Variants { get; set; } = new();
}
