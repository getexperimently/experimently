namespace ExperimentationPlatform.Exceptions;

/// <summary>
/// Thrown when the API returns an error HTTP status code (4xx or 5xx, excluding 401).
/// </summary>
public class ApiException : ExperimentationException
{
    /// <summary>The HTTP status code returned by the API.</summary>
    public int StatusCode { get; }

    /// <summary>The raw response body, if available.</summary>
    public string? ResponseBody { get; }

    public ApiException(int statusCode, string message, string? responseBody = null)
        : base(message)
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
    }

    public ApiException(int statusCode, string message, Exception innerException, string? responseBody = null)
        : base(message, innerException)
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
    }
}
