# Standalone hash parity test — no mix.exs or dependencies needed.
# Run with: elixir sdk/elixir/test_standalone.exs
#
# This verifies that the Elixir hash formula matches all other SDK implementations.

defmodule HashTest do
  @moduledoc "Standalone cross-SDK hash parity verification."

  def hash_user(user_id, flag_key) do
    input = "#{user_id}:#{flag_key}"
    <<b0, b1, b2, b3, _rest::binary>> = :crypto.hash(:md5, input)
    v = b0 ||| (b1 <<< 8) ||| (b2 <<< 16) ||| (b3 <<< 24)
    v / 4_294_967_296.0
  end

  def run do
    tests = [
      {"user-123", "my-flag", 0.6927449859213084},
    ]

    IO.puts("=== Elixir SDK — Cross-SDK Hash Parity Test ===\n")

    results =
      Enum.map(tests, fn {uid, fk, expected} ->
        result = hash_user(uid, fk)
        diff = abs(result - expected)
        passed = diff < 1.0e-10

        status = if passed, do: "PASSED", else: "FAILED"
        IO.puts("  hash_user(#{inspect(uid)}, #{inspect(fk)})")
        IO.puts("    got:      #{result}")
        IO.puts("    expected: #{expected}")
        IO.puts("    diff:     #{diff}")
        IO.puts("    status:   #{status}\n")

        passed
      end)

    all_passed = Enum.all?(results)

    if all_passed do
      IO.puts("All hash parity checks PASSED.")
    else
      IO.puts("One or more hash parity checks FAILED.")
      System.halt(1)
    end
  end
end

HashTest.run()
