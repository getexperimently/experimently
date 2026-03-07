<?php

declare(strict_types=1);

/**
 * Standalone test runner — no composer/autoloader required.
 *
 * Verifies the critical hash algorithm and core evaluation logic without
 * any external dependencies. Useful for quick smoke-testing in CI or on
 * systems where composer is not yet set up.
 *
 * Run: php sdk/php/test_standalone.php
 */

require_once __DIR__ . '/src/FeatureFlagEvaluator.php';

use ExperimentationPlatform\FeatureFlagEvaluator;

$failures = [];
$passed   = 0;

function ok(string $name): void
{
    global $passed;
    $passed++;
    echo "  PASS  $name\n";
}

function fail(string $name, string $reason): void
{
    global $failures;
    $failures[] = "  FAIL  $name: $reason";
    echo "  FAIL  $name: $reason\n";
}

// =============================================================================
// Hash parity — cross-SDK compatibility vector
// =============================================================================

echo "\n=== Hash Compatibility ===\n";

// Known vector — must match JS, Python, Java, React SDKs
$result   = FeatureFlagEvaluator::hashUser('user-123', 'my-flag');
$expected = 0.6927449859213084;
if (abs($result - $expected) < 1e-10) {
    ok('hashUser("user-123", "my-flag") === 0.6927449859213084');
} else {
    fail('hashUser("user-123", "my-flag")', "got $result, expected $expected");
}

// Bounds check — 100 random-ish inputs
$outOfBounds = false;
for ($i = 0; $i < 100; $i++) {
    $h = FeatureFlagEvaluator::hashUser("user-$i", "flag-$i");
    if ($h < 0.0 || $h >= 1.0) {
        $outOfBounds = true;
        fail("hash bounds user-$i", "value $h is out of [0, 1)");
        break;
    }
}
if (!$outOfBounds) {
    ok('all 100 hash values are in [0.0, 1.0)');
}

// Determinism — same input always produces same output
$h1 = FeatureFlagEvaluator::hashUser('det-user', 'det-flag');
$h2 = FeatureFlagEvaluator::hashUser('det-user', 'det-flag');
$h3 = FeatureFlagEvaluator::hashUser('det-user', 'det-flag');
if ($h1 === $h2 && $h2 === $h3) {
    ok('hashUser is deterministic across multiple calls');
} else {
    fail('hashUser determinism', "values differ: $h1, $h2, $h3");
}

// Empty strings — should not throw
try {
    $h = FeatureFlagEvaluator::hashUser('', '');
    if ($h >= 0.0 && $h < 1.0) {
        ok('hashUser("", "") returns valid float in [0, 1)');
    } else {
        fail('hashUser("", "")', "out of range: $h");
    }
} catch (\Throwable $e) {
    fail('hashUser("", "")', 'threw ' . $e::class . ': ' . $e->getMessage());
}

// Unicode
try {
    $h = FeatureFlagEvaluator::hashUser('用户-123', '功能标志');
    if ($h >= 0.0 && $h < 1.0) {
        ok('hashUser(unicode) returns valid float in [0, 1)');
    } else {
        fail('hashUser(unicode)', "out of range: $h");
    }
} catch (\Throwable $e) {
    fail('hashUser(unicode)', 'threw ' . $e::class . ': ' . $e->getMessage());
}

// Long strings
try {
    $h = FeatureFlagEvaluator::hashUser(str_repeat('a', 5000), str_repeat('b', 5000));
    if ($h >= 0.0 && $h < 1.0) {
        ok('hashUser(long strings) returns valid float');
    } else {
        fail('hashUser(long strings)', "out of range: $h");
    }
} catch (\Throwable $e) {
    fail('hashUser(long strings)', 'threw ' . $e::class . ': ' . $e->getMessage());
}

// Different inputs → different outputs (statistical, not guaranteed but near-certain)
$hA = FeatureFlagEvaluator::hashUser('user-A', 'flag-1');
$hB = FeatureFlagEvaluator::hashUser('user-B', 'flag-1');
$hC = FeatureFlagEvaluator::hashUser('user-A', 'flag-2');
if ($hA !== $hB && $hA !== $hC) {
    ok('different inputs produce different hashes');
} else {
    fail('hash collision test', "hA=$hA, hB=$hB, hC=$hC — unexpected collision");
}

// =============================================================================
// FeatureFlagEvaluator — evaluate()
// =============================================================================

echo "\n=== FeatureFlagEvaluator ===\n";

$baseFlag = [
    'key'                => 'my-flag',
    'enabled'            => true,
    'rollout_percentage' => 100,
    'variants'           => [
        ['key' => 'control',   'value' => 'A'],
        ['key' => 'treatment', 'value' => 'B'],
    ],
];

// Disabled flag must return null
$disabledFlag          = $baseFlag;
$disabledFlag['enabled'] = false;
$result = FeatureFlagEvaluator::evaluate($disabledFlag, 'user-123');
if ($result === null) {
    ok('evaluate() returns null when flag is disabled');
} else {
    fail('evaluate() disabled', 'expected null, got ' . json_encode($result));
}

// 100% rollout → user is included
$result = FeatureFlagEvaluator::evaluate($baseFlag, 'user-123');
if (is_array($result)) {
    ok('evaluate() returns variant for user in 100% rollout');
} else {
    fail('evaluate() 100% rollout', 'expected array, got null');
}

// 0% rollout → user is excluded
$zeroFlag                      = $baseFlag;
$zeroFlag['rollout_percentage'] = 0;
$result = FeatureFlagEvaluator::evaluate($zeroFlag, 'user-123');
if ($result === null) {
    ok('evaluate() returns null for 0% rollout');
} else {
    fail('evaluate() 0% rollout', 'expected null, got ' . json_encode($result));
}

// Empty variants → null
$emptyVariantsFlag             = $baseFlag;
$emptyVariantsFlag['variants'] = [];
$result = FeatureFlagEvaluator::evaluate($emptyVariantsFlag, 'user-123');
if ($result === null) {
    ok('evaluate() returns null when variants is empty');
} else {
    fail('evaluate() empty variants', 'expected null, got ' . json_encode($result));
}

// Deterministic for same user
$r1 = FeatureFlagEvaluator::evaluate($baseFlag, 'consistent-user');
$r2 = FeatureFlagEvaluator::evaluate($baseFlag, 'consistent-user');
if ($r1 === $r2) {
    ok('evaluate() is deterministic for the same user');
} else {
    fail('evaluate() determinism', 'got different results: ' . json_encode($r1) . ' vs ' . json_encode($r2));
}

// Attributes accepted without crash
try {
    $result = FeatureFlagEvaluator::evaluate($baseFlag, 'user-123', ['country' => 'US']);
    ok('evaluate() accepts attributes without throwing');
} catch (\Throwable $e) {
    fail('evaluate() with attributes', 'threw ' . $e::class . ': ' . $e->getMessage());
}

// Variant distribution — 1000 users, expect roughly 50/50
$counts = ['control' => 0, 'treatment' => 0];
for ($i = 0; $i < 1000; $i++) {
    $v = FeatureFlagEvaluator::evaluate($baseFlag, "user-$i");
    if ($v !== null) {
        $counts[$v['key']]++;
    }
}
if ($counts['control'] > 400 && $counts['treatment'] > 400) {
    ok("variant distribution roughly 50/50 (control={$counts['control']}, treatment={$counts['treatment']})");
} else {
    fail('variant distribution', "skewed: control={$counts['control']}, treatment={$counts['treatment']}");
}

// =============================================================================
// Summary
// =============================================================================

echo "\n" . str_repeat('=', 50) . "\n";
$total = $passed + count($failures);
echo "Results: $passed/$total tests passed\n";

if (empty($failures)) {
    echo "\nAll standalone tests PASSED\n";
    exit(0);
} else {
    echo "\nFailed tests:\n";
    foreach ($failures as $f) {
        echo "$f\n";
    }
    exit(1);
}
