"""The committed sample population still contains the planted exceptions."""

from pathlib import Path

from access_review.engine import run_review
from access_review.loader import load_accounts, load_hr, load_rules

ROOT = Path(__file__).resolve().parents[1]

# Kept in step with the comments in scripts/generate_sample_data.py.
EXPECTED = {
    "TER-01": {"mhale", "pnanda", "hcho", "obriggs", "lvoss"},
    "ORP-01": {
        "svc_nightly",
        "temp_contractor",
        "jdoe_old",
        "admin_legacy",
        "intern_2024",
        "vendor_portal",
        "audit_temp",
        "shared_inbox",
        "svc_payroll",
    },
    "ADM-01": {"pnanda", "rokonkwo", "cfernandez", "admin_legacy"},
    "DRM-01": {"hcho", "jdoe_old", "dbrooks", "felsayed", "hmartins"},
    "SOD-01": {"obriggs", "gibarra", "twitek", "ahaddad"},
    "PST-01": {"hcho", "lvoss"},
}


def review():
    return run_review(
        load_hr(ROOT / "sample_data" / "hr.csv"),
        load_accounts(ROOT / "sample_data" / "accounts.csv"),
        load_rules(ROOT / "rules.yaml"),
    )


def test_sample_population_size_and_review_date():
    result = review()
    assert result.employee_count == 72
    assert result.active_employees == 64
    assert result.terminated_employees == 8
    assert result.account_count == 102
    assert str(result.review_date.date()) == "2026-09-30"
    assert result.overall_rating == "High"


def test_each_planted_rule_matches_the_sample():
    result = review()
    for rule_id, expected in EXPECTED.items():
        found = {finding.username for finding in result.for_rule(rule_id)}
        assert found == expected, rule_id


def test_controls_that_are_operating_are_not_exceptions():
    """Admins with tickets, split duties, a new joiner, and removed leavers stay clear."""
    result = review()
    admin_names = {finding.username for finding in result.for_rule("ADM-01")}
    assert {"wchen", "hberg", "polsen", "svc_payroll"}.isdisjoint(admin_names)

    sod_names = {finding.username for finding in result.for_rule("SOD-01")}
    assert {"bcho", "slind", "polsen"}.isdisjoint(sod_names)

    dormant_names = {finding.username for finding in result.for_rule("DRM-01")}
    assert "mpark" not in dormant_names
    assert "mhale" not in dormant_names

    # Samuel Adeyemi, Nora Feldman, and Chris Dalton were removed from the export.
    assert "Samuel Adeyemi" not in {finding.employee_name for finding in result.findings}
    assert result.accounts_with_exceptions == 22
    assert len(result.findings) == 29
