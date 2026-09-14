defmodule Experimently.MixProject do
  use Mix.Project

  # test/support holds helpers the test files share; compiled for :test only.
  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  def project do
    [
      app: :experimently,
      version: "0.1.0",
      elixir: "~> 1.14",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      description: "Elixir SDK for Experimently — A/B testing and feature flags",
      package: package(),
      name: "Experimently",
      source_url: "https://github.com/getexperimently/experimently",
      docs: [
        main: "Experimently",
        extras: ["README.md"]
      ]
    ]
  end

  def application do
    [
      extra_applications: [:logger, :crypto, :inets, :ssl]
    ]
  end

  defp deps do
    [
      {:jason, "~> 1.4"},
      {:ex_doc, "~> 0.31", only: :dev, runtime: false}
    ]
  end

  defp package do
    [
      licenses: ["MIT"],
      links: %{"GitHub" => "https://github.com/getexperimently/experimently"}
    ]
  end
end
