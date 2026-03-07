namespace ExperimentationPlatform.Exceptions;

/// <summary>
/// Base exception for all Experimentation Platform SDK errors.
/// </summary>
public class ExperimentationException : Exception
{
    public ExperimentationException(string message) : base(message) { }

    public ExperimentationException(string message, Exception innerException)
        : base(message, innerException) { }
}
