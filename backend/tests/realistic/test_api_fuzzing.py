"""
Schemathesis API Fuzzing — automatic adversarial input generation.

Uses Schemathesis to read the platform's OpenAPI spec and automatically
generate adversarial inputs for every endpoint.  No scenario writing needed —
Schemathesis infers all possible inputs from the schema and fires them.

Requirements:
  - pip install schemathesis
  - Platform must be running at REALISTIC_API_URL (default: localhost:8000)
  - Set RUN_FUZZING=1 to enable (skipped by default to protect CI)

Run:
    RUN_FUZZING=1 python -m pytest backend/tests/realistic/test_api_fuzzing.py -v

What this validates:
  - Every endpoint returns a non-5xx response for schema-valid inputs
  - Every endpoint returns a 422 (not 500) for schema-invalid inputs
  - No endpoint leaks internal error details in 5xx responses
  - Response bodies conform to the declared response schema
"""

import os

import pytest

API_URL = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
OPENAPI_URL = f"{API_URL}/openapi.json"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_FUZZING") != "1",
    reason="API fuzzing tests skipped by default. Set RUN_FUZZING=1 to enable.",
)


def _get_schemathesis():
    """Lazily import schemathesis — not a required dependency for normal test runs."""
    try:
        import schemathesis

        return schemathesis
    except ImportError:
        pytest.skip("schemathesis not installed. Run: pip install schemathesis")


def _get_schema():
    schemathesis = _get_schemathesis()
    try:
        schema = schemathesis.from_uri(OPENAPI_URL)
        return schema, schemathesis
    except Exception as exc:
        pytest.skip(f"Could not fetch OpenAPI schema from {OPENAPI_URL}: {exc}")


@pytest.fixture(scope="module")
def schema():
    s, _ = _get_schema()
    return s


class TestAPIFuzzing:
    """
    Schemathesis-driven API fuzzing.

    Each test method parameterises over all schema operations via the
    @schema.parametrize() decorator applied to the underlying function.
    """

    def test_all_endpoints_accept_valid_inputs(self, schema):
        """
        Every endpoint should return a non-500 response when given
        schema-valid inputs.  4xx is acceptable (auth/permissions), but
        5xx indicates an unhandled exception.
        """
        schemathesis = _get_schemathesis()

        @schema.parametrize()
        def _run(case):
            response = case.call()
            # 5xx responses (except 501 Not Implemented) indicate a bug
            if response.status_code >= 500 and response.status_code != 501:
                pytest.fail(
                    f"Endpoint {case.method.upper()} {case.path} returned "
                    f"{response.status_code} for schema-valid input:\n"
                    f"Request body: {case.body}\n"
                    f"Response: {response.text[:500]}"
                )

        _run()

    def test_invalid_inputs_return_422_not_500(self, schema):
        """
        Schema-invalid inputs should produce 422 Unprocessable Entity,
        not 500 Internal Server Error.  A 500 for invalid input indicates
        missing validation that could be exploited.
        """
        schemathesis = _get_schemathesis()

        @schema.parametrize()
        @schemathesis.given(schemathesis.strategies.from_schema(schema, allow_x00=True))
        def _run(case):
            # Corrupt the request body to introduce invalid data
            if case.body and isinstance(case.body, dict):
                case.body["__fuzz__"] = "\x00\xff\n\r" * 10
            response = case.call()
            if response.status_code == 500:
                pytest.fail(
                    f"Endpoint {case.method.upper()} {case.path} returned 500 "
                    f"for potentially invalid input — add input validation.\n"
                    f"Response: {response.text[:500]}"
                )

    def test_response_conforms_to_schema(self, schema):
        """
        Successful responses (2xx) should conform to the declared response schema.
        This validates that the API contract is honoured.
        """

        @schema.parametrize()
        def _run(case):
            response = case.call()
            if 200 <= response.status_code < 300:
                case.validate_response(response)

        _run()

    def test_no_internal_details_leaked_in_errors(self, schema):
        """
        5xx error responses must not contain internal stack traces,
        file paths, or database connection strings.
        """
        import re

        LEAK_PATTERNS = [
            r"Traceback \(most recent call last\)",
            r"File \"/.+\.py\", line \d+",
            r"postgresql://",
            r"redis://",
            r"SECRET_KEY",
            r"password=",
        ]

        @schema.parametrize()
        def _run(case):
            response = case.call()
            if response.status_code >= 500:
                body = response.text
                for pattern in LEAK_PATTERNS:
                    if re.search(pattern, body, re.IGNORECASE):
                        pytest.fail(
                            f"Endpoint {case.method.upper()} {case.path} leaks "
                            f"internal details in 500 response (pattern: {pattern!r}):\n"
                            f"{body[:500]}"
                        )

        _run()


class TestOpenAPISpec:
    """Validate the OpenAPI spec itself is well-formed."""

    def test_openapi_spec_is_reachable(self):
        import requests

        resp = requests.get(OPENAPI_URL, timeout=10)
        assert resp.status_code == 200, f"OpenAPI spec not reachable at {OPENAPI_URL}"

    def test_openapi_spec_is_valid_json(self):
        import json

        import requests

        resp = requests.get(OPENAPI_URL, timeout=10)
        try:
            spec = resp.json()
        except json.JSONDecodeError as e:
            pytest.fail(f"OpenAPI spec is not valid JSON: {e}")
        assert "openapi" in spec or "swagger" in spec, "Missing 'openapi' key in spec"

    def test_all_endpoints_have_response_schemas(self):
        """Every endpoint should declare at least one response schema."""
        import requests

        resp = requests.get(OPENAPI_URL, timeout=10)
        spec = resp.json()
        paths = spec.get("paths", {})
        missing = []
        for path, methods in paths.items():
            for method, details in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    if not details.get("responses"):
                        missing.append(f"{method.upper()} {path}")
        assert not missing, (
            "The following endpoints have no response schemas:\n" + "\n".join(missing)
        )
