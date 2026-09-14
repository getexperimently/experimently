<?php

declare(strict_types=1);

namespace Experimently\Errors;

/**
 * Base exception for all Experimently SDK errors.
 */
class ExperimentationException extends \RuntimeException
{
    public function __construct(string $message = '', int $code = 0, ?\Throwable $previous = null)
    {
        parent::__construct($message, $code, $previous);
    }
}
