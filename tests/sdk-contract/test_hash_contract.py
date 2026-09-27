"""Tests of the comparison in hash_contract.py itself.

The SDKs are checked by running ``hash_contract.py <sdk>`` (the SDK Contract
Tests job); these check that the comparison rejects what it must, so a wrong
SDK answer cannot pass it. They need only pytest.

Run: python -m pytest tests/sdk-contract -o addopts="" -q
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "hash_contract", Path(__file__).parent / "hash_contract.py"
)
hc = importlib.util.module_from_spec(_spec)
sys.modules["hash_contract"] = hc  # dataclasses look their module up here
_spec.loader.exec_module(hc)

ONE_BUCKET = 1 / 2**32


@pytest.fixture
def vectors():
    return hc.load_vectors()


def _correct(hash_vectors, rollout_vectors, with_md5=True):
    all_vectors = hash_vectors + rollout_vectors
    return {
        "hashes": [v["expected_hash"] for v in all_vectors],
        "md5_hex": (
            [v.get("md5_hex") for v in hash_vectors] + [None] * len(rollout_vectors)
            if with_md5
            else None
        ),
    }


def test_the_vector_file_has_the_pinned_counts(vectors):
    hash_vectors, rollout_vectors = vectors
    assert len(hash_vectors) == hc.EXPECTED_HASH_VECTORS
    assert len(rollout_vectors) == hc.EXPECTED_ROLLOUT_VECTORS


def test_correct_answers_pass_and_report_the_counts(vectors):
    lines = hc.check_results("sdk", *vectors, _correct(*vectors))
    assert lines == [
        f"sdk: OK -- {hc.EXPECTED_HASH_VECTORS}/{hc.EXPECTED_HASH_VECTORS} hash vectors, "
        f"{hc.EXPECTED_ROLLOUT_VECTORS}/{hc.EXPECTED_ROLLOUT_VECTORS} rollout vectors, "
        f"{hc.EXPECTED_HASH_VECTORS}/{hc.EXPECTED_HASH_VECTORS} md5 digests"
    ]


def test_an_sdk_without_a_digest_says_so(vectors):
    (line,) = hc.check_results("sdk", *vectors, _correct(*vectors, with_md5=False))
    assert line.endswith("md5: the SDK exports no digest function")


@pytest.mark.parametrize("index", [0, 4, 8, 9, 10])
def test_a_hash_one_bucket_off_fails(vectors, index):
    result = _correct(*vectors)
    result["hashes"][index] += ONE_BUCKET
    with pytest.raises(hc.ContractError, match="expected"):
        hc.check_results("sdk", *vectors, result)


def test_a_wrong_digest_fails(vectors):
    result = _correct(*vectors)
    result["md5_hex"][3] = "0" * 32
    with pytest.raises(hc.ContractError, match="md5"):
        hc.check_results("sdk", *vectors, result)


def test_too_few_answers_fail(vectors):
    result = _correct(*vectors, with_md5=False)
    result["hashes"].pop()
    with pytest.raises(hc.ContractError, match="returned 10 hashes for 11 inputs"):
        hc.check_results("sdk", *vectors, result)


def test_no_answers_fail(vectors):
    with pytest.raises(hc.ContractError, match="returned None hashes"):
        hc.check_results("sdk", *vectors, {"md5_hex": None})


def test_a_truncated_vector_file_fails(tmp_path):
    parsed = json.loads(hc.VECTORS_PATH.read_text())
    parsed["hash_vectors"].pop()
    short = tmp_path / "golden-vectors.json"
    short.write_text(json.dumps(parsed))
    with pytest.raises(hc.ContractError, match="has 8 hash_vectors, expected 9"):
        hc.load_vectors(short)


def test_every_sdk_directory_is_classified():
    dirs = [p.name for p in (hc.REPO_ROOT / "sdk").iterdir() if p.is_dir()]
    lines = hc.classify(dirs)
    assert len(lines) == len(dirs)


def test_an_unclassified_sdk_directory_fails():
    dirs = [*hc.RUNNERS, *hc.NOT_RUN, "cobol"]
    with pytest.raises(hc.ContractError, match="does not classify: \\['cobol'\\]"):
        hc.classify(dirs)


def test_a_classified_sdk_with_no_directory_fails():
    dirs = [d for d in [*hc.RUNNERS, *hc.NOT_RUN] if d != "go"]
    with pytest.raises(hc.ContractError, match="no directory under sdk/: \\['go'\\]"):
        hc.classify(dirs)
