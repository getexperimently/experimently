<?php

declare(strict_types=1);

namespace ExperimentationPlatform\Tests;

use ExperimentationPlatform\FeatureFlagEvaluator;
use PHPUnit\Framework\TestCase;

/**
 * Unit tests for FeatureFlagEvaluator — local flag evaluation logic.
 */
class FeatureFlagEvaluatorTest extends TestCase
{
    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private function makeFlag(array $overrides = []): array
    {
        return array_merge([
            'key'                => 'test-flag',
            'enabled'            => true,
            'rollout_percentage' => 100,
            'variants'           => [
                ['key' => 'control',   'value' => 'A'],
                ['key' => 'treatment', 'value' => 'B'],
            ],
        ], $overrides);
    }

    // -------------------------------------------------------------------------
    // Disabled flag
    // -------------------------------------------------------------------------

    public function testEvaluateReturnsNullWhenDisabled(): void
    {
        $flag = $this->makeFlag(['enabled' => false]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'Disabled flag must return null regardless of rollout or user');
    }

    // -------------------------------------------------------------------------
    // Rollout percentage gating
    // -------------------------------------------------------------------------

    public function testEvaluateReturnsNullWhenBucketExceedsRollout(): void
    {
        // hashUser("user-123", "my-flag") = 0.6927... → bucket = 69.27 out of 100
        // Setting rollout to 50% should exclude this user
        $flag = $this->makeFlag([
            'key'                => 'my-flag',
            'rollout_percentage' => 50,
        ]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'User whose bucket exceeds rollout percentage must be excluded');
    }

    public function testEvaluateReturnsVariantWhenInRollout(): void
    {
        // hashUser("user-123", "my-flag") = 0.6927... → bucket = 69.27
        // Setting rollout to 100% ensures inclusion
        $flag = $this->makeFlag([
            'key'                => 'my-flag',
            'rollout_percentage' => 100,
        ]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertIsArray($result, 'User within rollout must receive a variant');
        $this->assertArrayHasKey('key', $result);
    }

    public function testEvaluateFullRollout100Percent(): void
    {
        // With 100% rollout all users should be included
        $flag = $this->makeFlag(['rollout_percentage' => 100]);

        $included = 0;
        for ($i = 0; $i < 100; $i++) {
            if (FeatureFlagEvaluator::evaluate($flag, "user-{$i}") !== null) {
                $included++;
            }
        }

        $this->assertSame(100, $included, '100% rollout must include all users');
    }

    public function testEvaluateZeroRollout(): void
    {
        // With 0% rollout no users should be included
        $flag = $this->makeFlag(['rollout_percentage' => 0]);

        for ($i = 0; $i < 50; $i++) {
            $result = FeatureFlagEvaluator::evaluate($flag, "user-{$i}");
            $this->assertNull($result, "User user-{$i} should not be included in 0% rollout");
        }
    }

    // -------------------------------------------------------------------------
    // Variant selection
    // -------------------------------------------------------------------------

    public function testEvaluateHandlesEmptyVariants(): void
    {
        $flag = $this->makeFlag([
            'rollout_percentage' => 100,
            'variants'           => [],
        ]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'Empty variants list must return null');
    }

    public function testEvaluateHandlesSingleVariant(): void
    {
        $flag = $this->makeFlag([
            'rollout_percentage' => 100,
            'variants'           => [['key' => 'only', 'value' => 'sole']],
        ]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertIsArray($result);
        $this->assertSame('only', $result['key']);
        $this->assertSame('sole', $result['value']);
    }

    public function testEvaluateReturnsFlagData(): void
    {
        $variants = [
            ['key' => 'v1', 'value' => 'value-1'],
            ['key' => 'v2', 'value' => 'value-2'],
        ];
        $flag = $this->makeFlag([
            'rollout_percentage' => 100,
            'variants'           => $variants,
        ]);

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertIsArray($result);
        // Result must be one of the defined variants
        $this->assertContains($result, $variants, 'Result must be one of the defined variants');
    }

    // -------------------------------------------------------------------------
    // Attribute handling
    // -------------------------------------------------------------------------

    public function testEvaluateWithAttributes(): void
    {
        // Attributes are accepted but currently unused in local evaluation — must not crash
        $flag = $this->makeFlag(['rollout_percentage' => 100]);

        $attributes = [
            'country' => 'US',
            'plan'    => 'premium',
            'age'     => 30,
        ];

        // Should not throw
        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123', $attributes);

        $this->assertIsArray($result);
    }

    // -------------------------------------------------------------------------
    // Consistency / determinism
    // -------------------------------------------------------------------------

    public function testEvaluateConsistentForSameUser(): void
    {
        $flag = $this->makeFlag(['rollout_percentage' => 100]);

        $first = FeatureFlagEvaluator::evaluate($flag, 'consistent-user');
        for ($i = 0; $i < 10; $i++) {
            $subsequent = FeatureFlagEvaluator::evaluate($flag, 'consistent-user');
            $this->assertSame(
                $first,
                $subsequent,
                "Evaluation must be deterministic — iteration $i returned a different variant"
            );
        }
    }

    // -------------------------------------------------------------------------
    // Variant distribution
    // -------------------------------------------------------------------------

    public function testEvaluateDistributesVariantsEvenly(): void
    {
        $flag = $this->makeFlag([
            'rollout_percentage' => 100,
            'variants'           => [
                ['key' => 'A', 'value' => 'a'],
                ['key' => 'B', 'value' => 'b'],
            ],
        ]);

        $counts = ['A' => 0, 'B' => 0];
        for ($i = 0; $i < 1000; $i++) {
            $variant = FeatureFlagEvaluator::evaluate($flag, "user-{$i}");
            $this->assertNotNull($variant);
            $counts[$variant['key']]++;
        }

        // Each variant should be within 10% of equal distribution (500 ± 10%)
        $this->assertGreaterThan(400, $counts['A'], 'Variant A should receive roughly 50% of traffic');
        $this->assertGreaterThan(400, $counts['B'], 'Variant B should receive roughly 50% of traffic');
    }

    // -------------------------------------------------------------------------
    // Missing / malformed flag data
    // -------------------------------------------------------------------------

    public function testEvaluateHandlesMissingEnabledKey(): void
    {
        // 'enabled' key is absent — should default to false
        $flag = [
            'key'                => 'test-flag',
            'rollout_percentage' => 100,
            'variants'           => [['key' => 'v', 'value' => '1']],
        ];

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'Missing enabled key should be treated as disabled');
    }

    public function testEvaluateHandlesMissingRolloutPercentage(): void
    {
        $flag = [
            'key'      => 'test-flag',
            'enabled'  => true,
            'variants' => [['key' => 'v', 'value' => '1']],
        ];

        // Missing rollout_percentage defaults to 0 — no user should be included
        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'Missing rollout_percentage should default to 0 (no users included)');
    }

    public function testEvaluateMissingVariantsKey(): void
    {
        $flag = [
            'key'                => 'test-flag',
            'enabled'            => true,
            'rollout_percentage' => 100,
        ];

        $result = FeatureFlagEvaluator::evaluate($flag, 'user-123');

        $this->assertNull($result, 'Missing variants key should return null');
    }
}
