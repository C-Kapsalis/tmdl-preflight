"""Advisory gating contract (C-pytest-advisory-demotion): ``advisory``
demotes, it does not delete.

The tmdl-preflight pytest plugin reads ``[tool.tmdl-preflight] advisory`` and
rewrites only a FAILED test-body report whose subject is an advisory model
into an xfail. Passes stay passes (not xpass) and every other model stays
hard-gated. All three are pinned together: a hook that demoted everything
would pass a one-case test while throwing away the suite's signal.
"""
from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

ADVISORY_ID = "alpha-pilot"
GATED_CLIENT = "spinout-10"   # any non-advisory model


def test_conftest_hook_demotes_only_failures_on_advisory_clients(pytester):
    pytester.makepyprojecttoml(f"""
        [tool.tmdl-preflight]
        advisory = ["{ADVISORY_ID}"]
    """)
    pytester.makepyfile(f"""
        import pytest

        @pytest.mark.parametrize("subject", [{ADVISORY_ID!r}, {GATED_CLIENT!r}])
        def test_fails(subject):
            assert False

        @pytest.mark.parametrize("subject", [{ADVISORY_ID!r}])
        def test_passes(subject):
            assert True
    """)
    result = pytester.runpytest()  # plugin auto-loads via its pytest11 entry point
    # advisory failure -> xfail; gated failure -> still a failure;
    # advisory pass -> still a pass (NOT xpass)
    result.assert_outcomes(failed=1, xfailed=1, passed=1)


def test_setup_failure_on_advisory_model_stays_a_failure(pytester):
    """Spec detection 3: only the call phase is demoted; infrastructure
    failures in setup stay red for everyone."""
    pytester.makepyprojecttoml(f"""
        [tool.tmdl-preflight]
        advisory = ["{ADVISORY_ID}"]
    """)
    pytester.makepyfile(f"""
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("infrastructure")

        @pytest.mark.parametrize("subject", [{ADVISORY_ID!r}])
        def test_needs_setup(subject, broken):
            assert True
    """)
    result = pytester.runpytest()  # plugin auto-loads via its pytest11 entry point
    result.assert_outcomes(errors=1)


def test_no_advisory_config_disables_the_hook(pytester):
    pytester.makepyfile(f"""
        import pytest

        @pytest.mark.parametrize("subject", [{ADVISORY_ID!r}])
        def test_fails(subject):
            assert False
    """)
    result = pytester.runpytest()  # plugin auto-loads via its pytest11 entry point
    result.assert_outcomes(failed=1)
