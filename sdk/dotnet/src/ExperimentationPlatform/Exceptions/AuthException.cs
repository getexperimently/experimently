namespace ExperimentationPlatform.Exceptions;

/// <summary>
/// Thrown when authentication fails (HTTP 401 Unauthorized).
/// </summary>
public class AuthException : ExperimentationException
{
    public AuthException(string message) : base(message) { }

    public AuthException(string message, Exception innerException)
        : base(message, innerException) { }
}
