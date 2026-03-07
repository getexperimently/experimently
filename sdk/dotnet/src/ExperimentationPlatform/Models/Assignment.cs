using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// Represents the result of assigning a user to an experiment variant.
/// </summary>
public class Assignment
{
    /// <summary>The key of the experiment this assignment belongs to.</summary>
    [JsonPropertyName("experiment_key")]
    public string? ExperimentKey { get; set; }

    /// <summary>The user ID that was assigned.</summary>
    [JsonPropertyName("user_id")]
    public string? UserId { get; set; }

    /// <summary>The variant assigned to this user, or null if not assigned.</summary>
    [JsonPropertyName("variant")]
    public Variant? Variant { get; set; }

    /// <summary>Whether the user is included in the experiment.</summary>
    [JsonPropertyName("is_in_experiment")]
    public bool IsInExperiment { get; set; }
}
