namespace ExperimentationPlatform.Exceptions;

/// <summary>
/// Thrown when a network-level error occurs (e.g. connection refused, DNS failure, timeout).
/// </summary>
public class NetworkException : ExperimentationException
{
    public NetworkException(string message) : base(message) { }

    public NetworkException(string message, Exception innerException)
        : base(message, innerException) { }
}
