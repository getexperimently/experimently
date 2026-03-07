using ExperimentationPlatform;
using ExperimentationPlatform.Models;
using Xunit;

namespace ExperimentationPlatform.Tests;

/// <summary>
/// Tests for the local feature flag evaluation logic in <see cref="FeatureFlagEvaluator"/>.
/// </summary>
public class FeatureFlagEvaluatorTests
{
    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private static FeatureFlag MakeFlag(
        bool enabled = true,
        double rollout = 100.0,
        List<Variant>? variants = null) =>
        new()
        {
            Key = "test-flag",
            Enabled = enabled,
            RolloutPercentage = rollout,
            Variants = variants ?? new List<Variant>
            {
                new() { Key = "control", Name = "Control" },
                new() { Key = "treatment", Name = "Treatment" }
            }
        };

    // -----------------------------------------------------------------------
    // Disabled flag
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_DisabledFlag_ReturnsNull()
    {
        var flag = MakeFlag(enabled: false);
        var result = FeatureFlagEvaluator.Evaluate(flag, "any-user");
        Assert.Null(result);
    }

    // -----------------------------------------------------------------------
    // Zero rollout
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_ZeroRollout_ReturnsNull()
    {
        var flag = MakeFlag(rollout: 0.0);
        // Every hash value >= 0.0 so bucket will always be >= rollout.
        var result = FeatureFlagEvaluator.Evaluate(flag, "user-123");
        Assert.Null(result);
    }

    // -----------------------------------------------------------------------
    // Full rollout
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_FullRollout_ReturnsVariant()
    {
        var flag = MakeFlag(rollout: 100.0);
        var result = FeatureFlagEvaluator.Evaluate(flag, "user-123");
        Assert.NotNull(result);
    }

    // -----------------------------------------------------------------------
    // Empty variant list
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_EmptyVariants_ReturnsNull()
    {
        var flag = MakeFlag(rollout: 100.0, variants: new List<Variant>());
        var result = FeatureFlagEvaluator.Evaluate(flag, "user-123");
        Assert.Null(result);
    }

    // -----------------------------------------------------------------------
    // Single variant
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_SingleVariant_AlwaysReturnsThatVariant()
    {
        var singleVariant = new List<Variant> { new() { Key = "only", Name = "Only Variant" } };
        var flag = MakeFlag(rollout: 100.0, variants: singleVariant);

        // All users in rollout should get the single variant.
        foreach (var userId in new[] { "user-1", "user-2", "user-abc", "another-user-42" })
        {
            var result = FeatureFlagEvaluator.Evaluate(flag, userId);
            Assert.NotNull(result);
            Assert.Equal("only", result.Key);
        }
    }

    // -----------------------------------------------------------------------
    // Determinism
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_SameUserId_ProducesDeterministicResult()
    {
        var flag = MakeFlag(rollout: 100.0);

        var first = FeatureFlagEvaluator.Evaluate(flag, "user-determinism-test");
        for (int i = 0; i < 50; i++)
        {
            var result = FeatureFlagEvaluator.Evaluate(flag, "user-determinism-test");
            Assert.Equal(first?.Key, result?.Key);
        }
    }

    // -----------------------------------------------------------------------
    // Variant distribution
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_DifferentUsers_CanGetDifferentVariants()
    {
        var flag = MakeFlag(rollout: 100.0);

        var seenVariants = new HashSet<string?>();
        for (int i = 0; i < 200; i++)
        {
            var result = FeatureFlagEvaluator.Evaluate(flag, $"user-{i}");
            if (result != null) seenVariants.Add(result.Key);
        }

        // With 200 users and 2 variants, we should see both.
        Assert.Contains("control", seenVariants);
        Assert.Contains("treatment", seenVariants);
    }

    // -----------------------------------------------------------------------
    // Attributes parameter
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_WithAttributes_DoesNotThrow()
    {
        var flag = MakeFlag(rollout: 100.0);
        var attrs = new Dictionary<string, object> { { "country", "US" }, { "age", 25 } };

        var ex = Record.Exception(() => FeatureFlagEvaluator.Evaluate(flag, "user-123", attrs));
        Assert.Null(ex);
    }

    [Fact]
    public void Evaluate_WithNullAttributes_DoesNotThrow()
    {
        var flag = MakeFlag(rollout: 100.0);
        var ex = Record.Exception(() => FeatureFlagEvaluator.Evaluate(flag, "user-123", null));
        Assert.Null(ex);
    }

    // -----------------------------------------------------------------------
    // Partial rollout boundary
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_PartialRollout_SomeUsersIncluded_SomeExcluded()
    {
        // With 50% rollout roughly half of users should be included.
        var flag = MakeFlag(rollout: 50.0);

        int inRollout = 0;
        int outOfRollout = 0;
        for (int i = 0; i < 1000; i++)
        {
            var result = FeatureFlagEvaluator.Evaluate(flag, $"user-{i}");
            if (result != null) inRollout++;
            else outOfRollout++;
        }

        // Both groups should be non-empty (statistical near-certainty with 1000 users).
        Assert.True(inRollout > 0, "Expected some users to be included in rollout");
        Assert.True(outOfRollout > 0, "Expected some users to be excluded from rollout");
    }

    // -----------------------------------------------------------------------
    // Variant value
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_VariantWithValue_ReturnsVariantWithValue()
    {
        var variants = new List<Variant>
        {
            new() { Key = "control", Name = "Control", Value = false },
            new() { Key = "treatment", Name = "Treatment", Value = true }
        };
        var flag = MakeFlag(rollout: 100.0, variants: variants);

        var result = FeatureFlagEvaluator.Evaluate(flag, "user-with-value");
        Assert.NotNull(result);
        Assert.NotNull(result.Value);
    }

    // -----------------------------------------------------------------------
    // Null / null variants list
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_NullVariantsList_ReturnsNull()
    {
        var flag = new FeatureFlag
        {
            Key = "test-flag",
            Enabled = true,
            RolloutPercentage = 100.0,
            Variants = null!
        };
        var result = FeatureFlagEvaluator.Evaluate(flag, "user-123");
        Assert.Null(result);
    }

    // -----------------------------------------------------------------------
    // Result is always a valid variant from the list
    // -----------------------------------------------------------------------

    [Fact]
    public void Evaluate_ReturnedVariant_IsAlwaysFromVariantsList()
    {
        var variants = new List<Variant>
        {
            new() { Key = "v1", Name = "V1" },
            new() { Key = "v2", Name = "V2" },
            new() { Key = "v3", Name = "V3" }
        };
        var flag = MakeFlag(rollout: 100.0, variants: variants);
        var validKeys = new HashSet<string> { "v1", "v2", "v3" };

        for (int i = 0; i < 200; i++)
        {
            var result = FeatureFlagEvaluator.Evaluate(flag, $"user-check-{i}");
            if (result != null)
                Assert.Contains(result.Key, validKeys);
        }
    }

    // -----------------------------------------------------------------------
    // HashUser result is in valid bucket range
    // -----------------------------------------------------------------------

    [Fact]
    public void HashUser_AllResults_InZeroToOneRange()
    {
        for (int i = 0; i < 500; i++)
        {
            double h = FeatureFlagEvaluator.HashUser($"user-{i}", $"flag-{i % 10}");
            Assert.True(h >= 0.0 && h < 1.0,
                $"Expected [0,1) but got {h} for user-{i}/flag-{i % 10}");
        }
    }
}
