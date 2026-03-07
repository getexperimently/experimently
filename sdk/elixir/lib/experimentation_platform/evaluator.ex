defmodule ExperimentationPlatform.Evaluator do
  @moduledoc """
  Core evaluator for feature flags and experiment assignment.

  Implements the cross-SDK consistent hashing algorithm based on MD5:
  - Input: "{userId}:{flagKey}"
  - Hash: MD5 -> first 4 bytes as little-endian uint32
  - Output: value in [0.0, 1.0)

  ## Hash Formula

  The hashing is consistent across all SDKs (JS, Python, Java, Go, etc.):

      hash_user("user-123", "my-flag") == 0.6927449859213084
  """

  @doc """
  Hash a user+flag combination to a float in [0.0, 1.0).

  Uses MD5 of "{user_id}:{flag_key}", reads first 4 bytes as little-endian uint32,
  and divides by 2^32 to get a value in [0.0, 1.0).

  This function must produce the same result as equivalent implementations
  in JavaScript, Python, Java, Go, and other supported SDKs.

  ## Examples

      iex> Evaluator.hash_user("user-123", "my-flag")
      0.6927449859213084

      iex> result = Evaluator.hash_user("user-abc", "feature-xyz")
      iex> result >= 0.0 and result < 1.0
      true
  """
  @spec hash_user(String.t(), String.t()) :: float()
  def hash_user(user_id, flag_key) do
    input = "#{user_id}:#{flag_key}"
    <<b0, b1, b2, b3, _rest::binary>> = :crypto.hash(:md5, input)
    v = b0 ||| (b1 <<< 8) ||| (b2 <<< 16) ||| (b3 <<< 24)
    v / 4_294_967_296.0
  end

  @doc """
  Evaluate a feature flag for a given user.

  Returns the variant map if the user is in the rollout, or nil if not.

  The flag map may use atom keys or string keys.

  ## Parameters
  - `flag` - Feature flag map (from API response)
  - `user_id` - The user identifier to evaluate for
  - `attributes` - Optional user attributes map (reserved for future targeting rules)

  ## Returns
  - A variant map (e.g., `%{"name" => "treatment", "value" => "new_design"}`) if the user is in rollout
  - `nil` if the flag is disabled, the user is not in rollout, or there are no variants

  ## Examples

      iex> flag = %{enabled: true, key: "my-flag", rollout_percentage: 100, variants: [%{name: "control"}]}
      iex> Evaluator.evaluate(flag, "user-123")
      %{name: "control"}

      iex> flag = %{enabled: false, key: "my-flag", rollout_percentage: 100, variants: [%{name: "control"}]}
      iex> Evaluator.evaluate(flag, "user-123")
      nil
  """
  @spec evaluate(map(), String.t(), map()) :: map() | nil
  def evaluate(flag, user_id, _attributes \\ %{}) do
    flag_key = flag[:key] || flag["key"]
    enabled = flag[:enabled] || flag["enabled"]
    rollout = flag[:rollout_percentage] || flag["rollout_percentage"] || 0
    variants = flag[:variants] || flag["variants"] || []

    cond do
      not enabled ->
        nil

      variants == [] ->
        nil

      true ->
        bucket = hash_user(user_id, flag_key) * 100.0

        if bucket < rollout do
          variant_hash = hash_user(user_id, "#{flag_key}:variant")
          idx = trunc(variant_hash * length(variants))
          # Clamp index just in case of floating point edge case at exactly 1.0
          safe_idx = min(idx, length(variants) - 1)
          Enum.at(variants, safe_idx)
        else
          nil
        end
    end
  end

  @doc """
  Evaluate experiment assignment for a given user.

  Returns the variant/treatment assignment if the user is allocated to the experiment,
  or nil if not.

  ## Parameters
  - `experiment` - Experiment map (from API response)
  - `user_id` - The user identifier to evaluate for
  - `attributes` - Optional user attributes map

  ## Returns
  - A variant map if the user is assigned, nil otherwise
  """
  @spec evaluate_experiment(map(), String.t(), map()) :: map() | nil
  def evaluate_experiment(experiment, user_id, _attributes \\ %{}) do
    experiment_key = experiment[:key] || experiment["key"]
    status = experiment[:status] || experiment["status"]
    traffic = experiment[:traffic_allocation] || experiment["traffic_allocation"] || 0
    variants = experiment[:variants] || experiment["variants"] || []

    if status not in ["running", :running] or variants == [] do
      nil
    else
      bucket = hash_user(user_id, experiment_key)

      traffic_float =
        cond do
          is_float(traffic) and traffic <= 1.0 -> traffic
          is_integer(traffic) and traffic <= 100 -> traffic / 100.0
          true -> traffic / 100.0
        end

      if bucket < traffic_float do
        variant_hash = hash_user(user_id, "#{experiment_key}:variant")
        idx = trunc(variant_hash * length(variants))
        safe_idx = min(idx, length(variants) - 1)
        Enum.at(variants, safe_idx)
      else
        nil
      end
    end
  end
end
