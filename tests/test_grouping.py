"""Golden regression: the server-side grouping must reproduce, exactly, the
partition the original frontend clusterLegs() produced. This locks behavior
across the JS->Python refactor.

The fixtures are SYNTHETIC — anonymized from a real account snapshot so the
grouping structure (order chains, relative strikes, quantity ratios, put/call
mix, expirations) is preserved while tickers are renamed and cost basis is
stripped. Never commit real position data; these tests only need shapes.
"""

import json
import pathlib

import pytest

from app.grouping import cluster_legs, classify, is_condor_shape, fingerprint

FIX = pathlib.Path(__file__).parent / "fixtures"
POSITIONS = json.loads((FIX / "positions_synthetic.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((FIX / "grouping_golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("underlying", sorted(GOLDEN))
def test_grouping_matches_frontend_golden(underlying):
    got = fingerprint(POSITIONS[underlying])
    assert got == GOLDEN[underlying], (
        f"{underlying} grouping drifted from the frontend golden")


def test_all_fixture_underlyings_covered():
    # every position in the snapshot has a golden entry (no silent gaps)
    assert set(POSITIONS) == set(GOLDEN)


def test_condor_merge_across_chains():
    # two put spreads (different chains) that together form a put condor merge
    def mk(qty, k, chain):
        return {"qty": qty, "strike": k, "option_type": "P", "chain": chain,
                "expiration": "2026-09-01", "symbol": f"X{k}", "dte_years": 0.1}
    legs = [mk(1, 90, 1), mk(-1, 95, 1), mk(-1, 105, 2), mk(1, 110, 2)]
    clusters = cluster_legs(legs)
    assert len(clusters) == 1
    assert clusters[0]["label"].startswith("Put Condor")


def test_stacked_iron_condors_stay_separate():
    def leg(qty, k, t, chain):
        return {"qty": qty, "strike": k, "option_type": t, "chain": chain,
                "expiration": "2026-09-01", "symbol": f"{t}{k}c{chain}", "dte_years": 0.1}
    legs = [
        leg(1, 90, "P", 1), leg(-1, 95, "P", 1), leg(-1, 105, "C", 1), leg(1, 110, "C", 1),
        leg(1, 80, "P", 2), leg(-1, 85, "P", 2), leg(-1, 115, "C", 2), leg(1, 120, "C", 2),
    ]
    labels = [c["label"] for c in cluster_legs(legs)]
    assert labels.count("Iron Condor · 36d") == 2 or \
        all(l.startswith("Iron Condor") for l in labels) and len(labels) == 2
