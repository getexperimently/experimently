<?php

declare(strict_types=1);

namespace ExperimentationPlatform;

use ExperimentationPlatform\Errors\ExperimentationException;

/**
 * Main entry-point for the Experimentation Platform PHP SDK.
 *
 * Provides feature flag evaluation, experiment assignment, and event tracking.
 * Flag data is fetched from the API and cached locally; evaluation is performed
 * client-side using the consistent MD5 hash algorithm shared across all SDKs.
 *
 * Usage:
 * ```php
 * $config = new SdkConfig(baseUrl: 'https://api.example.com', apiKey: 'your-key');
 * $client = new ExperimentationClient($config);
 *
 * $result = $client->evaluateFlag('dark-mode', 'user-123');
 * if ($result['enabled']) {
 *     // Show dark mode
 * }
 * ```
 */
class ExperimentationClient
{
    private readonly Cache $cache;
    private readonly HttpClient $httpClient;
    private readonly SdkConfig $config;

    /**
     * @param SdkConfig       $config     SDK configuration
     * @param HttpClient|null $httpClient Optional HTTP client override (useful for testing)
     */
    public function __construct(SdkConfig $config, ?HttpClient $httpClient = null)
    {
        $this->config     = $config;
        $this->cache      = new Cache($config->cacheTtl, $config->maxCacheSize);
        $this->httpClient = $httpClient ?? new HttpClient($config);
    }

    /**
     * Evaluate a feature flag for the given user.
     *
     * The flag definition is fetched once from the API and then cached locally.
     * Subsequent calls within the TTL window use the cached definition and evaluate
     * entirely client-side, making evaluation fast and resilient to network issues.
     *
     * @param string $flagKey    Feature flag key (e.g. 'dark-mode')
     * @param string $userId     Stable user identifier
     * @param array  $attributes Additional user attributes for targeting rules (reserved for future use)
     * @param mixed  $default    Default value returned when the flag cannot be fetched or user is not in rollout
     * @return array{enabled: bool, variant: string|null, value: mixed}
     */
    public function evaluateFlag(
        string $flagKey,
        string $userId,
        array $attributes = [],
        mixed $default = false
    ): array {
        $flag = $this->fetchFlag($flagKey);

        if ($flag === null) {
            return [
                'enabled' => false,
                'variant' => null,
                'value'   => $default,
            ];
        }

        $variant = FeatureFlagEvaluator::evaluate($flag, $userId, $attributes);

        if ($variant === null) {
            return [
                'enabled' => false,
                'variant' => null,
                'value'   => $default,
            ];
        }

        return [
            'enabled' => true,
            'variant' => $variant['key'] ?? null,
            'value'   => $variant['value'] ?? true,
        ];
    }

    /**
     * Retrieve the experiment assignment for a given user.
     *
     * @param string $experimentKey Experiment identifier
     * @param string $userId        Stable user identifier
     * @param array  $attributes    Additional user attributes
     * @return array|null Assignment data, or null if the user is not assigned / an error occurred
     */
    public function getAssignment(string $experimentKey, string $userId, array $attributes = []): ?array
    {
        try {
            $cacheKey = "assignment:{$experimentKey}:{$userId}";
            $cached   = $this->cache->get($cacheKey);

            if ($cached !== null) {
                return $cached;
            }

            $response = $this->httpClient->post('/api/v1/sdk/assign', [
                'experiment_key' => $experimentKey,
                'user_id'        => $userId,
                'attributes'     => $attributes,
            ]);

            if (empty($response)) {
                return null;
            }

            $this->cache->set($cacheKey, $response);
            return $response;
        } catch (ExperimentationException) {
            return null;
        }
    }

    /**
     * Track a user event.
     *
     * This method never throws — errors are swallowed and false is returned so that
     * a tracking failure never interrupts the host application.
     *
     * @param string $eventName  Name of the event (e.g. 'purchase', 'page_view')
     * @param string $userId     User identifier
     * @param array  $properties Arbitrary event properties
     * @return bool true on success, false on any error
     */
    public function track(string $eventName, string $userId, array $properties = []): bool
    {
        try {
            $this->httpClient->post('/api/v1/sdk/events', [
                'event_name' => $eventName,
                'user_id'    => $userId,
                'properties' => $properties,
                'timestamp'  => date('c'),
            ]);
            return true;
        } catch (\Throwable) {
            // Intentionally suppress all errors — tracking must never break the app
            return false;
        }
    }

    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------

    /**
     * Fetch a feature flag definition, using the cache when available.
     *
     * @param string $flagKey
     * @return array|null Flag definition array, or null on error
     */
    private function fetchFlag(string $flagKey): ?array
    {
        $cacheKey = "flag:{$flagKey}";
        $cached   = $this->cache->get($cacheKey);

        if ($cached !== null) {
            return $cached;
        }

        try {
            $flag = $this->httpClient->get("/api/v1/sdk/flags/{$flagKey}");

            if (empty($flag)) {
                return null;
            }

            $this->cache->set($cacheKey, $flag);
            return $flag;
        } catch (ExperimentationException) {
            return null;
        }
    }
}
