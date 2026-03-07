defmodule ExperimentationPlatform.EvaluatorTest do
  @moduledoc """
  Unit tests for the Evaluator module.

  Tests cover feature flag evaluation, experiment assignment,
  and edge cases with various flag configurations.
  """

  use ExUnit.Case, async: true

  alias ExperimentationPlatform.Evaluator

  # Helper to build a flag with atom keys
  defp atom_flag(overrides \\ %{}) do
    %{
      key: "test-flag",
      enabled: true,
      rollout_percentage: 100,
      variants: [%{name: "control"}, %{name: "treatment"}]
    }
    |> Map.merge(overrides)
  end

  # Helper to build a flag with string keys
  defp string_flag(overrides \\ %{}) do
    %{
      "key" => "test-flag",
      "enabled" => true,
      "rollout_percentage" => 100,
      "variants" => [%{"name" => "control"}, %{"name" => "treatment"}]
    }
    |> Map.merge(overrides)
  end

  describe "evaluate/3 — disabled flags" do
    test "returns nil when flag is disabled (atom keys)" do
      flag = atom_flag(%{enabled: false})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end

    test "returns nil when flag is disabled (string keys)" do
      flag = string_flag(%{"enabled" => false})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end

    test "returns nil when enabled key is nil" do
      flag = %{key: "f", enabled: nil, rollout_percentage: 100, variants: [%{name: "v"}]}
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end
  end

  describe "evaluate/3 — rollout percentage" do
    test "returns variant when rollout is 100%" do
      flag = atom_flag(%{rollout_percentage: 100})
      result = Evaluator.evaluate(flag, "user-123")
      refute result == nil
    end

    test "returns nil when rollout is 0%" do
      flag = atom_flag(%{rollout_percentage: 0})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end

    test "bucket below rollout returns a variant" do
      # user-123 + test-flag bucket is ~51.9%, so rollout of 100 includes them
      flag = atom_flag(%{rollout_percentage: 100, variants: [%{name: "only"}]})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == %{name: "only"}
    end

    test "bucket above rollout returns nil" do
      # user-123 + test-flag bucket is ~51.9%, so rollout of 50 excludes them
      flag = atom_flag(%{rollout_percentage: 50})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end
  end

  describe "evaluate/3 — variants" do
    test "returns nil when variants list is empty" do
      flag = atom_flag(%{rollout_percentage: 100, variants: []})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end

    test "returns the single variant when only one exists" do
      flag = atom_flag(%{rollout_percentage: 100, variants: [%{name: "solo"}]})
      result = Evaluator.evaluate(flag, "user-123")
      assert result == %{name: "solo"}
    end

    test "returns one of the variants (not nil) for 100% rollout" do
      flag = atom_flag(%{rollout_percentage: 100, variants: [%{name: "a"}, %{name: "b"}]})
      result = Evaluator.evaluate(flag, "user-123")
      assert result in [%{name: "a"}, %{name: "b"}]
    end

    test "variant selection is deterministic for same user" do
      flag = atom_flag(%{rollout_percentage: 100, variants: [%{name: "a"}, %{name: "b"}, %{name: "c"}]})
      r1 = Evaluator.evaluate(flag, "user-stable")
      r2 = Evaluator.evaluate(flag, "user-stable")
      assert r1 == r2
    end

    test "different users may get different variants" do
      flag = atom_flag(%{rollout_percentage: 100, variants: [%{name: "a"}, %{name: "b"}]})
      results = for i <- 1..20, do: Evaluator.evaluate(flag, "user-#{i}")
      variant_names = Enum.map(results, &(&1[:name] || &1["name"])) |> Enum.uniq()
      # With 20 different users and 2 variants, we expect to see both
      assert length(variant_names) > 1
    end
  end

  describe "evaluate/3 — key formats" do
    test "works with atom keys in flag map" do
      flag = %{key: "atom-flag", enabled: true, rollout_percentage: 100, variants: [%{name: "v"}]}
      result = Evaluator.evaluate(flag, "user-1")
      assert result == %{name: "v"}
    end

    test "works with string keys in flag map" do
      flag = %{"key" => "str-flag", "enabled" => true, "rollout_percentage" => 100, "variants" => [%{"name" => "v"}]}
      result = Evaluator.evaluate(flag, "user-1")
      assert result == %{"name" => "v"}
    end

    test "rollout_percentage defaults to 0 when missing" do
      flag = %{key: "f", enabled: true, variants: [%{name: "v"}]}
      result = Evaluator.evaluate(flag, "user-123")
      assert result == nil
    end
  end

  describe "evaluate/3 — attributes" do
    test "accepts empty attributes map" do
      flag = atom_flag()
      result = Evaluator.evaluate(flag, "user-123", %{})
      refute result == nil
    end

    test "accepts non-empty attributes map (reserved for future targeting)" do
      flag = atom_flag()
      result = Evaluator.evaluate(flag, "user-123", %{country: "US", plan: "pro"})
      refute result == nil
    end
  end

  describe "hash_user/2" do
    test "returns float in [0.0, 1.0)" do
      result = Evaluator.hash_user("user-123", "my-flag")
      assert is_float(result)
      assert result >= 0.0
      assert result < 1.0
    end

    test "matches the cross-SDK known vector" do
      result = Evaluator.hash_user("user-123", "my-flag")
      assert_in_delta result, 0.6927449859213084, 1.0e-10
    end
  end
end
