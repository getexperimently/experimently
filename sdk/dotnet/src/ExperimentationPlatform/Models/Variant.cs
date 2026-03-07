using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// Represents a single variant within a feature flag or experiment.
/// </summary>
public class Variant
{
    /// <summary>The unique key identifier for this variant (e.g. "control", "treatment").</summary>
    [JsonPropertyName("key")]
    public string Key { get; set; } = "";

    /// <summary>The human-readable name for this variant.</summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    /// <summary>The optional payload value associated with this variant.</summary>
    [JsonPropertyName("value")]
    public object? Value { get; set; }
}
