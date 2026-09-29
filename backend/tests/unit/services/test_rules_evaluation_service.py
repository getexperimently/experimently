"""
Test cases for RulesEvaluationService.

Tests the high-level rules evaluation service that integrates:
- Rule compilation
- Evaluation caching
- Metrics collection
- Batch evaluation
"""

import timeit
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from backend.app.schemas.targeting_rule import (
    Condition,
    LogicalOperator,
    OperatorType,
    RuleGroup,
    TargetingRule,
    TargetingRules,
)
from backend.app.services.rules_evaluation_service import (
    EvaluationMetrics,
    EvaluationResult,
    RulesEvaluationService,
)


class TestServiceInitialization:
    """Test service initialization and setup."""

    def test_service_initializes_with_defaults(self):
        """Test that service initializes with default configuration."""
        service = RulesEvaluationService()

        assert service is not None
        assert service.evaluation_cache is not None
        assert service.rule_compiler is not None
        assert service.metrics is not None

    def test_service_initializes_with_custom_config(self):
        """Test service initialization with custom configuration."""
        service = RulesEvaluationService(
            cache_max_size=5000, cache_ttl=600.0, enable_metrics=True
        )

        assert service.evaluation_cache.max_size == 5000
        assert service.evaluation_cache.default_ttl == 600.0
        assert service.enable_metrics is True

    def test_service_initializes_without_metrics(self):
        """Test service can run without metrics collection."""
        service = RulesEvaluationService(enable_metrics=False)

        assert service.enable_metrics is False


class TestBasicEvaluation:
    """Test basic rule evaluation functionality."""

    def test_evaluate_simple_rule(self):
        """Test evaluating a simple rule."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_context = {"user_id": "user_123", "country": "US"}

        result = service.evaluate(rules, user_context)

        assert result is not None
        assert isinstance(result, EvaluationResult)
        assert result.matched is True
        assert result.matched_rule_id == "rule_1"

    def test_evaluate_no_match(self):
        """Test evaluation when no rules match."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_context = {"user_id": "user_123", "country": "CA"}

        result = service.evaluate(rules, user_context)

        assert result.matched is False
        assert result.matched_rule_id is None

    def test_evaluate_with_default_rule(self):
        """Test evaluation falls back to default rule."""
        service = RulesEvaluationService()

        default_rule = TargetingRule(
            id="default",
            rule=RuleGroup(operator=LogicalOperator.AND, conditions=[], groups=[]),
            priority=999,
            rollout_percentage=100,
        )

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=default_rule,
        )

        user_context = {"user_id": "user_123", "country": "CA"}

        result = service.evaluate(rules, user_context)

        assert result.matched is True
        assert result.matched_rule_id == "default"


class TestCachingBehavior:
    """Test evaluation caching functionality."""

    def test_cache_hit_on_repeated_evaluation(self):
        """Test that repeated evaluations hit the cache."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_context = {"user_id": "user_123", "country": "US"}

        # First evaluation (cache miss)
        result1 = service.evaluate(rules, user_context)

        # Second evaluation (should be cache hit)
        result2 = service.evaluate(rules, user_context)

        assert result1.matched == result2.matched
        assert result1.matched_rule_id == result2.matched_rule_id

        # Check cache stats
        stats = service.evaluation_cache.get_stats()
        assert stats["hits"] >= 1

    def test_cache_miss_with_different_context(self):
        """Test that different context causes cache miss."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Evaluate with different users
        result1 = service.evaluate(rules, {"user_id": "user_1", "country": "US"})
        result2 = service.evaluate(rules, {"user_id": "user_2", "country": "CA"})

        assert result1.matched is True
        assert result2.matched is False

    def test_cache_invalidation_on_rule_change(self):
        """Test cache invalidation when rules change."""
        service = RulesEvaluationService()

        rules_v1 = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_context = {"user_id": "user_123", "country": "US"}

        # First evaluation
        result1 = service.evaluate(rules_v1, user_context)
        assert result1.matched is True

        # Invalidate cache for rule_1
        service.invalidate_rule_cache("rule_1")

        # Modify rules
        rules_v2 = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="CA",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Evaluation with new rules should reflect changes
        result2 = service.evaluate(rules_v2, user_context)
        assert result2.matched is False


class TestMetricsCollection:
    """Test metrics collection functionality."""

    def test_metrics_track_evaluation_count(self):
        """Test that metrics track number of evaluations."""
        service = RulesEvaluationService(enable_metrics=True)

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Perform multiple evaluations
        for i in range(10):
            service.evaluate(rules, {"user_id": f"user_{i}", "country": "US"})

        metrics = service.get_metrics()

        assert metrics.total_evaluations >= 10

    def test_metrics_track_cache_hits(self):
        """Test that metrics track cache hit/miss."""
        service = RulesEvaluationService(enable_metrics=True)

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_context = {"user_id": "user_123", "country": "US"}

        # First evaluation (cache miss)
        service.evaluate(rules, user_context)

        # Second evaluation (cache hit)
        service.evaluate(rules, user_context)

        metrics = service.get_metrics()

        assert metrics.cache_hits >= 1

    def test_metrics_track_latency(self):
        """Test that metrics track evaluation latency."""
        service = RulesEvaluationService(enable_metrics=True)

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        service.evaluate(rules, {"user_id": "user_123", "country": "US"})

        metrics = service.get_metrics()

        assert metrics.avg_latency_ms is not None
        assert metrics.avg_latency_ms >= 0
        assert metrics.p99_latency_ms is not None


class TestBatchEvaluation:
    """Test batch evaluation functionality."""

    def test_batch_evaluate_multiple_users(self):
        """Test evaluating multiple users in batch."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        user_contexts = [
            {"user_id": "user_1", "country": "US"},
            {"user_id": "user_2", "country": "CA"},
            {"user_id": "user_3", "country": "US"},
        ]

        results = service.batch_evaluate(rules, user_contexts)

        assert len(results) == 3
        assert results[0].matched is True
        assert results[1].matched is False
        assert results[2].matched is True

    def test_batch_evaluation_shares_compiled_rules(self):
        """Test that batch evaluation reuses compiled rules."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.IN,
                                value=["US", "CA"],
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Create many users
        user_contexts = [{"user_id": f"user_{i}", "country": "US"} for i in range(100)]

        # This used to assert the batch took under 100 ms -- a single
        # wall-clock reading (#409). What the test's name claims is that the
        # rule is compiled once and reused, and that is a count.
        compiler = service.rule_compiler
        with patch.object(
            compiler, "_compile_rule", wraps=compiler._compile_rule
        ) as compile_rule:
            results = service.batch_evaluate(rules, user_contexts)

        assert len(results) == 100
        assert all(r.matched and r.matched_rule_id == "rule_1" for r in results)
        assert compile_rule.call_count == 1, (
            f"100 users, one rule, compiled {compile_rule.call_count} times"
        )
        assert compiler.cache_hits >= 100

    def test_batch_evaluation_with_cache(self):
        """Test that batch evaluation benefits from caching."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Same user evaluated multiple times
        user_contexts = [{"user_id": "user_123", "country": "US"}] * 10

        results = service.batch_evaluate(rules, user_contexts)

        assert len(results) == 10
        # All should match
        assert all(r.matched for r in results)

        # Check cache hit rate
        stats = service.evaluation_cache.get_stats()
        # Should have at least 9 cache hits (first is miss, rest are hits)
        assert stats["hits"] >= 9


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_evaluate_with_missing_attribute(self):
        """Test evaluation when user context missing required attribute."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.EQUALS,
                                value="US",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # User context missing 'country' attribute
        user_context = {"user_id": "user_123"}

        # Should not crash, should return no match
        result = service.evaluate(rules, user_context)

        assert result.matched is False
        assert result.error is None or "missing" in result.error.lower()

    def test_evaluate_with_invalid_rule(self):
        """Test evaluation with rule that causes runtime error."""
        service = RulesEvaluationService()

        # Create a valid rule but with attributes that will cause runtime issues
        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            # Valid Pydantic condition, but might cause evaluation errors
                            Condition(
                                attribute="nested_data",
                                operator=OperatorType.EQUALS,
                                value="expected",
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # User context with unusual data types that might cause issues
        user_context = {"user_id": "user_123", "nested_data": None}

        # Should handle gracefully
        result = service.evaluate(rules, user_context)

        # Should indicate error or no match (not crash)
        assert result is not None
        assert result.matched is False

    def test_evaluate_with_empty_rules(self):
        """Test evaluation with no rules."""
        service = RulesEvaluationService()

        rules = TargetingRules(rules=[], default_rule=None)
        user_context = {"user_id": "user_123"}

        result = service.evaluate(rules, user_context)

        assert result.matched is False

    def test_evaluate_with_exception_in_operator(self):
        """Test handling of exception during operator evaluation."""
        service = RulesEvaluationService()

        rules = TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            # Semantic version with malformed data
                            Condition(
                                attribute="version",
                                operator=OperatorType.SEMANTIC_VERSION,
                                value="1.0.0",
                                additional_value="gt",  # Comparison mode
                            )
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

        # Invalid version format will cause comparison to fail gracefully
        user_context = {"user_id": "user_123", "version": "not-a-version"}

        # Should handle exception gracefully
        result = service.evaluate(rules, user_context)

        # Should not crash, should return failed match
        assert result is not None
        assert result.matched is False


class TestPerformance:
    """What makes the service fast, counted rather than timed (#409).

    Both tests here used to compare wall-clock readings -- one against an
    absolute second, one against another reading taken a moment earlier --
    and the second failed CI at a load average above 30 while passing 21/21
    alone. A timing on a shared runner measures the runner. What made these
    paths fast is that the rule is compiled once and that a cache hit skips
    evaluation entirely; both are counts. The absolute throughput survives as
    a ``benchmark`` (skipped unless RUN_BENCHMARKS=1).
    """

    @staticmethod
    def _rules() -> TargetingRules:
        return TargetingRules(
            rules=[
                TargetingRule(
                    id="rule_1",
                    rule=RuleGroup(
                        operator=LogicalOperator.AND,
                        conditions=[
                            Condition(
                                attribute="country",
                                operator=OperatorType.IN,
                                value=["US", "CA", "UK"],
                            ),
                            Condition(
                                attribute="age",
                                operator=OperatorType.GREATER_THAN,
                                value=18,
                            ),
                        ],
                        groups=[],
                    ),
                    priority=1,
                    rollout_percentage=100,
                )
            ],
            default_rule=None,
        )

    def test_evaluation_is_fast(self):
        """1000 users: one compilation, and each condition evaluated once each.

        This asserted 1000 evaluations took under a second. The cost of an
        evaluation is its compilation plus its condition evaluations; neither
        may grow per call.
        """
        service = RulesEvaluationService()
        rules = self._rules()
        compiler = service.rule_compiler

        with (
            patch.object(
                compiler, "_compile_rule", wraps=compiler._compile_rule
            ) as compile_rule,
            patch.object(
                service,
                "_evaluate_condition_enhanced",
                wraps=service._evaluate_condition_enhanced,
            ) as evaluate_condition,
        ):
            results = [
                service.evaluate(
                    rules, {"user_id": f"user_{i}", "country": "US", "age": 25}
                )
                for i in range(1000)
            ]

        assert all(r.matched and not r.cached and r.error is None for r in results)
        assert compile_rule.call_count == 1, (
            f"one rule compiled {compile_rule.call_count} times over 1000 users"
        )
        assert evaluate_condition.call_count == 2 * 1000, (
            f"two conditions x 1000 users, {evaluate_condition.call_count} evaluations"
        )
        assert service.get_metrics().total_evaluations == 1000

    @pytest.mark.regression
    def test_cached_evaluation_is_faster(self):
        """A cache hit does not evaluate the rules at all.

        #409: this compared two single timings (``cached < uncached``) and
        failed at a load average above 30. The reason a cached evaluation is
        faster is that it skips compilation and rule evaluation, so that is
        what is asserted -- with the uncached pass first, as a positive
        control that the counter sees evaluations when they happen.
        """
        service = RulesEvaluationService()
        rules = self._rules()
        user_context = {"user_id": "user_123", "country": "US", "age": 25}

        with (
            patch.object(
                service,
                "_evaluate_targeting_rules_enhanced",
                wraps=service._evaluate_targeting_rules_enhanced,
            ) as evaluate_rules,
            patch.object(
                service, "_compile_rules", wraps=service._compile_rules
            ) as compile_rules,
        ):
            uncached = [
                service.evaluate(
                    rules, {"user_id": f"unique_{i}", "country": "US", "age": 25}
                )
                for i in range(100)
            ]
            assert evaluate_rules.call_count == 100
            assert not any(r.cached for r in uncached)

            # Warm the cache for one user, then count what the hits cost.
            service.evaluation_cache.clear()
            service.evaluate(rules, user_context)
            service.reset_metrics()
            evaluate_rules.reset_mock()
            compile_rules.reset_mock()

            cached = [service.evaluate(rules, user_context) for _ in range(100)]

        assert all(r.cached and r.matched for r in cached)
        assert evaluate_rules.call_count == 0, (
            f"100 cache hits re-evaluated the rules {evaluate_rules.call_count} times"
        )
        assert compile_rules.call_count == 0
        assert service.get_metrics().cache_hits == 100

    @pytest.mark.benchmark
    def test_evaluation_throughput_benchmark(self):
        """At least 100 evaluations a second, best of five rounds."""
        service = RulesEvaluationService()
        rules = self._rules()

        def run() -> None:
            for i in range(1000):
                service.evaluate(
                    rules,
                    {"user_id": f"user_{i}", "country": "US", "age": 25},
                    skip_cache=True,
                )

        best = min(timeit.repeat(run, repeat=5, number=1))
        assert 1000 / best > 100, f"{1000 / best:.0f} evaluations/sec"
