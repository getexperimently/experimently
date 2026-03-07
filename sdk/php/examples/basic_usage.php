<?php

declare(strict_types=1);

/**
 * Basic usage example for the Experimently PHP SDK.
 *
 * This file demonstrates how to:
 *  1. Create a client with a valid configuration
 *  2. Evaluate a feature flag for a user
 *  3. Get an experiment assignment
 *  4. Track a user event
 *
 * Run from the sdk/php directory after installing dependencies:
 *   composer install
 *   php examples/basic_usage.php
 */

require_once __DIR__ . '/../vendor/autoload.php';

use ExperimentationPlatform\ExperimentationClient;
use ExperimentationPlatform\SdkConfig;
use ExperimentationPlatform\Errors\ExperimentationException;

// ---------------------------------------------------------------------------
// 1. Configure the SDK
// ---------------------------------------------------------------------------

$config = new SdkConfig(
    baseUrl: getenv('EXPERIMENT_API_URL') ?: 'https://api.example.com',
    apiKey:  getenv('EXPERIMENT_API_KEY') ?: 'your-api-key-here',
    cacheTtl:     300,   // Cache flag definitions for 5 minutes
    timeout:       10,   // 10-second HTTP timeout
    maxCacheSize: 1000,  // Keep up to 1,000 flags in memory
);

// ---------------------------------------------------------------------------
// 2. Create the client
// ---------------------------------------------------------------------------

$client = new ExperimentationClient($config);

// ---------------------------------------------------------------------------
// 3. Evaluate a feature flag
// ---------------------------------------------------------------------------

$userId = 'user-' . rand(1000, 9999);

$result = $client->evaluateFlag(
    flagKey:    'dark-mode',
    userId:     $userId,
    attributes: ['country' => 'US', 'plan' => 'premium'],
    default:    false
);

echo "=== Feature Flag Evaluation ===\n";
echo "Flag:    dark-mode\n";
echo "User:    $userId\n";
echo "Enabled: " . ($result['enabled'] ? 'true' : 'false') . "\n";
echo "Variant: " . ($result['variant'] ?? 'none') . "\n";
echo "Value:   " . json_encode($result['value']) . "\n\n";

if ($result['enabled']) {
    // Use the variant value to drive the application experience
    echo "Dark mode is ENABLED for this user (variant: {$result['variant']})\n";
} else {
    echo "Dark mode is DISABLED for this user — showing default experience\n";
}

// ---------------------------------------------------------------------------
// 4. Get an experiment assignment
// ---------------------------------------------------------------------------

echo "\n=== Experiment Assignment ===\n";

$assignment = $client->getAssignment(
    experimentKey: 'checkout-flow-v2',
    userId:        $userId,
    attributes:    ['plan' => 'premium'],
);

if ($assignment !== null) {
    echo "Experiment: checkout-flow-v2\n";
    echo "Variant:    " . ($assignment['variant'] ?? 'unknown') . "\n";
    echo "Is control: " . (($assignment['is_control'] ?? false) ? 'yes' : 'no') . "\n";
} else {
    echo "User is not assigned to experiment checkout-flow-v2\n";
}

// ---------------------------------------------------------------------------
// 5. Track an event
// ---------------------------------------------------------------------------

echo "\n=== Event Tracking ===\n";

$success = $client->track(
    eventName:  'page_view',
    userId:     $userId,
    properties: [
        'page'     => 'checkout',
        'referrer' => 'homepage',
    ]
);

echo "Tracked page_view: " . ($success ? "success" : "failed (non-fatal)") . "\n";

// track() never throws — safe to call unconditionally
$client->track('button_click', $userId, ['button' => 'buy-now']);

// ---------------------------------------------------------------------------
// 6. Local hash evaluation (no network call)
// ---------------------------------------------------------------------------

echo "\n=== Local Hash Evaluation ===\n";

use ExperimentationPlatform\FeatureFlagEvaluator;

$bucket = FeatureFlagEvaluator::hashUser($userId, 'some-flag');
printf("Local bucket for %s / some-flag: %.6f\n", $userId, $bucket);

// Known cross-SDK vector
$known = FeatureFlagEvaluator::hashUser('user-123', 'my-flag');
printf("Known cross-SDK vector (user-123, my-flag): %.16f\n", $known);
echo "Expected:                                    0.6927449859213084\n";
echo "Match: " . (abs($known - 0.6927449859213084) < 1e-10 ? "YES" : "NO") . "\n";

echo "\nDone.\n";
