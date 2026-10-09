"""Opt-in real Godot oracle. Missing runtime fails this explicit integration job."""
import os
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import review_support as review

pytestmark = pytest.mark.skipif(os.environ.get("GM_REAL_GODOT") != "1", reason="Explicit real-engine job required (GM_REAL_GODOT=1)")


def test_same_real_assertions_detect_all_four_faults():
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests/fixtures/one_room_loop"
    output = root / "review-evidence" / ("integration-" + uuid.uuid4().hex[:12])
    results = []
    for variant in review.VARIANTS:
        result = review.smoke(fixture, output / variant, variant, timeout=60)
        results.append(result)
        expected = "PASS" if variant == "baseline" else "FAIL"
        assert result["result"] == expected, result
        assertions = review.load_json(output / variant / "reports/assertions.json")
        assert len(assertions["cases"]) >= 28
        assert {case["mechanic"] for case in assertions["cases"]} == {f"FX-M{i}" for i in range(1, 7)}
        assert any(case["status"] == "FAIL" for case in assertions["cases"]) == (variant != "baseline")
        assert result["environment"]["input_source"] == "semantic_action"
        assert "human_experience_acceptance" in result["not_proven"]
    assert len({result["fixture_spec_digest"] for result in results}) == 1
    assert len({result["test_digest"] for result in results}) == 1
    assert len({result["source_digest"] for result in results}) == 5
