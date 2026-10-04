"""
Unit tests for ``backend/app/services/bandit_routing.py``: the bandit choice
both tracking assignment routes use for new users.

Pure-logic tests: no database, MagicMock experiments and bandit states.
"""

import uuid
from collections import Counter
from unittest.mock import MagicMock

import pytest

from backend.app.services.bandit_routing import bandit_chooser
from backend.app.services.bandit_routing import bandit_weight as _bandit_weight
from backend.app.services.bandit_routing import (
    select_bandit_variant as _select_bandit_variant,
)


def _experiment(optimization_type="thompson_sampling", n_variants=2):
    exp = MagicMock()
    exp.id = uuid.uuid4()
    exp.optimization_type = optimization_type
    exp.variants = []
    for i in range(n_variants):
        variant = MagicMock()
        variant.id = uuid.uuid4()
        variant.name = f"v{i}"
        exp.variants.append(variant)
    return exp


def _state(weights):
    state = MagicMock()
    state.variant_weights = weights
    return state


class TestBanditWeight:
    def test_plain_numbers_and_payload_dicts(self):
        assert _bandit_weight(0.4) == 0.4
        assert _bandit_weight({"weight": 0.25, "pulls": 10}) == 0.25
        assert _bandit_weight("0.5") == 0.5

    def test_missing_zero_or_invalid_gives_zero(self):
        assert _bandit_weight(None) == 0.0
        assert _bandit_weight(0) == 0.0
        assert _bandit_weight(-0.3) == 0.0
        assert _bandit_weight({}) == 0.0
        assert _bandit_weight("nope") == 0.0


class TestSelectBanditVariant:
    def test_is_deterministic_per_user(self):
        exp = _experiment()
        a, b = exp.variants
        state = _state({str(a.id): 0.5, str(b.id): 0.5})

        for user_id in ("alice", "bob", "carol", str(uuid.uuid4())):
            first = _select_bandit_variant(exp, state, user_id)
            assert first in (a.id, b.id)
            assert all(
                _select_bandit_variant(exp, state, user_id) == first for _ in range(25)
            )

    def test_all_weight_on_one_variant(self):
        exp = _experiment()
        a, b = exp.variants
        state = _state({str(a.id): 1.0, str(b.id): 0.0})

        assert all(
            _select_bandit_variant(exp, state, f"user-{i}") == a.id for i in range(200)
        )

    def test_scheduler_payload_shape(self):
        exp = _experiment()
        a, b = exp.variants
        state = _state(
            {
                str(a.id): {"weight": 0.0, "successes": 0, "failures": 10, "pulls": 10},
                str(b.id): {"weight": 1.0, "successes": 9, "failures": 1, "pulls": 10},
            }
        )
        assert all(
            _select_bandit_variant(exp, state, f"user-{i}") == b.id for i in range(100)
        )

    def test_variants_missing_from_weights_get_no_traffic(self):
        exp = _experiment(n_variants=3)
        a, b, c = exp.variants
        state = _state({str(b.id): 0.7})  # a and c missing → no traffic

        assert all(
            _select_bandit_variant(exp, state, f"user-{i}") == b.id for i in range(100)
        )

    def test_distribution_roughly_matches_weights(self):
        exp = _experiment()
        a, b = exp.variants
        state = _state({str(a.id): 0.7, str(b.id): 0.3})

        n = 4000
        counts = Counter(
            _select_bandit_variant(exp, state, f"user-{i}") for i in range(n)
        )
        assert set(counts) == {a.id, b.id}
        share_a = counts[a.id] / n
        assert 0.65 < share_a < 0.75, share_a

    def test_fixed_experiment_returns_none(self):
        exp = _experiment(optimization_type="fixed")
        a, b = exp.variants
        state = _state({str(a.id): 1.0, str(b.id): 0.0})
        assert _select_bandit_variant(exp, state, "user-1") is None

        exp.optimization_type = None
        assert _select_bandit_variant(exp, state, "user-1") is None

    def test_missing_or_empty_state_returns_none(self):
        exp = _experiment()
        assert _select_bandit_variant(exp, None, "user-1") is None
        assert _select_bandit_variant(exp, _state({}), "user-1") is None
        assert _select_bandit_variant(exp, _state(None), "user-1") is None
        assert _select_bandit_variant(exp, _state([1.0, 0.0]), "user-1") is None

    def test_all_zero_weights_return_none(self):
        exp = _experiment()
        a, b = exp.variants
        assert (
            _select_bandit_variant(
                exp, _state({str(a.id): 0.0, str(b.id): 0}), "user-1"
            )
            is None
        )

    def test_weights_are_normalised(self):
        """Weights that do not sum to 1 still split traffic proportionally."""
        exp = _experiment()
        a, b = exp.variants
        state = _state({str(a.id): 3.0, str(b.id): 1.0})

        n = 2000
        counts = Counter(
            _select_bandit_variant(exp, state, f"user-{i}") for i in range(n)
        )
        assert 0.70 < counts[a.id] / n < 0.80

    def test_bucket_is_scoped_to_experiment(self):
        """The same user can land on different arms in different experiments."""
        exp1, exp2 = _experiment(), _experiment()
        picks = set()
        for exp in (exp1, exp2):
            a, b = exp.variants
            state = _state({str(a.id): 0.5, str(b.id): 0.5})
            for i in range(50):
                chosen = _select_bandit_variant(exp, state, f"user-{i}")
                picks.add((exp.id, chosen == a.id))
        # Both experiments hand out both arms across 50 users
        assert len(picks) == 4

    def test_experiment_none_returns_none(self):
        assert _select_bandit_variant(None, _state({"x": 1.0}), "user-1") is None


class TestBanditChooser:
    """``bandit_chooser`` answers as ``select_bandit_variant`` does, reading the
    state once and holding plain values only."""

    @staticmethod
    def _db(state):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = state
        return db

    def test_agrees_with_select_for_every_user(self):
        exp = _experiment(n_variants=3)
        a, b, c = exp.variants
        state = _state({str(a.id): 0.1, str(b.id): {"weight": 0.6}, str(c.id): 0.3})
        choose = bandit_chooser(self._db(state), exp)
        for i in range(500):
            assert choose(f"user-{i}") == _select_bandit_variant(
                exp, state, f"user-{i}"
            )

    def test_reads_the_state_once(self):
        exp = _experiment()
        a, b = exp.variants
        db = self._db(_state({str(a.id): 1.0, str(b.id): 1.0}))
        choose = bandit_chooser(db, exp)
        for i in range(50):
            choose(f"user-{i}")
        assert db.query.call_count == 1

    def test_holds_plain_values_not_the_objects(self):
        """Changing the ORM objects afterwards changes nothing: a commit that
        expires them cannot make the chooser reload them."""
        exp = _experiment()
        a, b = exp.variants
        state = _state({str(a.id): 0.0, str(b.id): 1.0})
        choose = bandit_chooser(self._db(state), exp)
        state.variant_weights = {str(a.id): 1.0, str(b.id): 0.0}
        exp.variants = []
        exp.id = uuid.uuid4()
        assert all(choose(f"user-{i}") == b.id for i in range(50))

    def test_fixed_allocation_reads_nothing(self):
        exp = _experiment(optimization_type="fixed")
        db = self._db(_state({str(exp.variants[0].id): 1.0}))
        assert bandit_chooser(db, exp)("user-1") is None
        assert db.query.call_count == 0

    def test_no_state_means_default_hashing(self):
        exp = _experiment()
        assert bandit_chooser(self._db(None), exp)("user-1") is None
