using System.Text.Json.Serialization;

namespace ExperimentationPlatform.Models;

/// <summary>
/// Represents an analytics event to track user actions.
/// </summary>
public class TrackEvent
{
    /// <summary>The name of the event (e.g. "button_clicked", "purchase_completed").</summary>
    [JsonPropertyName("event_name")]
    public string EventName { get; set; } = "";

    /// <summary>The user ID who triggered this event.</summary>
    [JsonPropertyName("user_id")]
    public string UserId { get; set; } = "";

    /// <summary>Optional key-value properties associated with this event.</summary>
    [JsonPropertyName("properties")]
    public Dictionary<string, object>? Properties { get; set; }

    /// <summary>The UTC timestamp when this event occurred. Defaults to now.</summary>
    [JsonPropertyName("timestamp")]
    public DateTimeOffset Timestamp { get; set; } = DateTimeOffset.UtcNow;
}
