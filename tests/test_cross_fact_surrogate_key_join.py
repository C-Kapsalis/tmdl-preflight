"""
Layer 2 (DAX validity): two facts must never be joined on a surrogate key whose
dimension carries more than one row per real-world entity.

WHY THIS GATE EXISTS. `Sitemap Pages #` was written as:

    CALCULATE(
        DISTINCTCOUNT('Sitemap'[landing_page_x_id]),
        KEEPFILTERS(Sitemap[landing_page_x_id] IN VALUES('Queries Organic'[landing_page_x_id])))

`_Landing Pages` is grained (URL x domain x originating service), so ONE URL
carries several `landing_page_x_id` values (688 of 10,684 URLs on spinout-12).
`Sitemap` keys a page to whichever dimension row its own source produced;
`Queries Organic` keys the same page to a different one. The intersection is
therefore empty **by construction** and the measure returns blank, truthfully,
on a comparison that could never match. Nothing caught it: the DAX parses,
every table and column resolves, the model imports cleanly.

The cure is to compare at the grain the question is actually asked at -- the URL
-- via set algebra over `VALUES('_Landing Pages'[Landing Page])`.

SCOPE, deliberately narrow. Only keys listed in the rule's `multi_row_keys`
option are policed. Joining two facts on `account_x_id` is fine and must not be
flagged. Add a key only with the row-count evidence that justifies it.

Ported: the local regex scan is replaced by rule `cross-fact-multirow-key-join`
(spec E-cross-fact-multirow-key-join, proposed id X001) with
`multi_row_keys = ["landing_page_x_id"]` in the preflight config; model discovery
by the stand-in `tests/fixtures/test_cross_fact_surrogate_key_join_webshop`.
"""
from __future__ import annotations

import json

import pytest

from conftest import run_check, violations

FIXTURE = "test_cross_fact_surrogate_key_join_webshop"
RULE = "cross-fact-multirow-key-join"
MULTI_ROW_SURROGATE_KEYS = ["landing_page_x_id"]
CONFIG = {"rules": {RULE: {"multi_row_keys": MULTI_ROW_SURROGATE_KEYS}}}


def _materialize(stand_in, variant):
    root = stand_in(FIXTURE)
    for op in json.loads((root / "variants.json").read_text(encoding="utf-8"))[variant]:
        f = root / op["file"]
        text = f.read_text(encoding="utf-8")
        assert text.count(op["old"]) == 1
        f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    (root / "variants.json").unlink()
    return root / "WebShop.SemanticModel"


def _gate(model_dir):
    if not (model_dir / "definition" / "tables").is_dir():
        pytest.skip("model has no tables/")
    code, payload = run_check(model_dir, RULE, config=CONFIG)
    assert code in (0, 1), f"preflight usage error: {payload}"
    found = violations(payload)
    assert not found, (
        "DAX joins two different tables on a surrogate key whose dimension carries "
        "several rows per real-world entity. The two key spaces do not overlap, so "
        "the comparison silently evaluates to nothing and the measure returns blank "
        "without erroring.\n\n" + "\n".join(f"  - {v['message']}" for v in found)
    )


@pytest.mark.parametrize("variant,verdict", [
    ("keepfilters_in_values", "fail"),
    ("in_calculatetable_values", "fail"),
    ("same_table_case_insensitive", "pass"),
    ("commented_out", "pass"),
    ("unlisted_key", "pass"),
    ("url_set_algebra", "pass"),
])
def test_no_cross_fact_join_on_multi_row_surrogate_key(stand_in, variant, verdict):
    model_dir = _materialize(stand_in, variant)
    if verdict == "pass":
        _gate(model_dir)
    else:
        with pytest.raises(AssertionError):
            _gate(model_dir)
        code, payload = run_check(model_dir, RULE, config=CONFIG)
        assert len(violations(payload)) == 1
        assert code == 1
