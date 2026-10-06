"""Each access test, including the cases that should pass."""

from __future__ import annotations

import pandas as pd
import pytest

from access_review.engine import run_review
from access_review.loader import Config, Rule

REVIEW = pd.Timestamp("2026-09-30")


def rule(**overrides) -> Rule:
    data = {
        "id": "X-01",
        "type": "terminated_with_access",
        "name": "Test rule",
        "enabled": True,
        "severity": "High",
        "control_objective": "Test objective.",
        "control_domain": "Access to programs and data",
        "iso_controls": ["5.18 Access rights"],
        "remediation": "Do the remediation.",
        "parameters": {},
    }
    data.update(overrides)
    return Rule(**data)


def config(*rules: Rule, **overrides) -> Config:
    data = {
        "organization": "Sample Org (fictional)",
        "system_name": "LedgerOne",
        "review_date": REVIEW,
        "control_domain": "Access to programs and data",
        "rules": list(rules),
    }
    data.update(overrides)
    return Config(**data)


def people(*rows: dict) -> pd.DataFrame:
    """One HR row per dict. No arguments means a single active employee."""
    base = {
        "employee_id": "E1001",
        "name": "Wei Chen",
        "department": "Information Technology",
        "status": "active",
        "termination_date": "",
        "manager": "Alex Rowan (Director)",
    }
    if not rows:
        rows = ({},)
    return pd.DataFrame([{**base, **row} for row in rows])


def accounts(*rows: dict) -> pd.DataFrame:
    """One account per dict. No arguments means that employee's current account."""
    base = {
        "username": "wchen",
        "employee_id": "E1001",
        "roles": "view_reports",
        "is_admin": "FALSE",
        "last_login": "2026-09-15",
        "created_date": "2024-01-10",
        "approval_ticket": "",
    }
    if not rows:
        rows = ({},)
    return pd.DataFrame([{**base, **row} for row in rows])


def names(result, rule_id: str | None = None) -> list[str]:
    findings = result.findings if rule_id is None else result.for_rule(rule_id)
    return [finding.username for finding in findings]


def test_terminated_employee_with_an_account_is_an_exception():
    result = run_review(
        people(
            {"employee_id": "E1", "name": "Marcus Hale", "status": "terminated", "termination_date": "2026-06-15"},
            {"employee_id": "E2", "name": "Mina Park", "status": "active"},
            {"employee_id": "E3", "name": "Samuel Adeyemi", "status": "terminated", "termination_date": "2026-05-20"},
        ),
        accounts(
            {"username": "mhale", "employee_id": "E1"},
            {"username": "mpark", "employee_id": "E2"},
        ),
        config(rule()),
    )
    assert names(result) == ["mhale"]
    finding = result.findings[0]
    assert finding.rule_id == "X-01"
    assert finding.control_objective == "Test objective."
    assert finding.iso_controls == "5.18 Access rights"
    assert finding.remediation == "Do the remediation."
    assert "terminated on 2026-06-15" in finding.evidence
    assert finding.employee_name == "Marcus Hale"


def test_terminated_status_is_matched_without_regard_to_case():
    result = run_review(
        people({"status": "Terminated", "termination_date": "2026-06-15"}),
        accounts(),
        config(rule()),
    )
    assert names(result) == ["wchen"]


def test_orphan_accounts_are_blank_ids_and_unknown_ids():
    result = run_review(
        people({"employee_id": "E1", "name": "Wei Chen"}),
        accounts(
            {"username": "wchen", "employee_id": "E1"},
            {"username": "svc_nightly", "employee_id": ""},
            {"username": "temp_contractor", "employee_id": "C-8841"},
        ),
        config(rule(id="ORP-01", type="orphan_account", severity="Medium")),
    )
    assert names(result) == ["svc_nightly", "temp_contractor"]
    blank = result.for_rule("ORP-01")[0]
    assert "(blank)" in blank.evidence
    assert blank.hr_status == "no HR record"
    assert blank.employee_name == ""


def test_admin_without_a_ticket_is_an_exception_and_a_ticket_clears_it():
    result = run_review(
        people(
            {"employee_id": "E1", "name": "Ruth Okonkwo"},
            {"employee_id": "E2", "name": "Wei Chen"},
            {"employee_id": "E3", "name": "Ben Cho"},
        ),
        accounts(
            {"username": "rokonkwo", "employee_id": "E1", "is_admin": "TRUE", "approval_ticket": ""},
            {"username": "wchen", "employee_id": "E2", "is_admin": "yes", "approval_ticket": "ACC-2024-1180"},
            {"username": "bcho", "employee_id": "E3", "is_admin": "FALSE", "approval_ticket": ""},
            {"username": "spaces", "employee_id": "E1", "is_admin": "TRUE", "approval_ticket": "   "},
        ),
        config(rule(id="ADM-01", type="privileged_without_approval")),
    )
    # spaces shares E1 with rokonkwo. Duplicate employee ids on accounts are allowed.
    assert names(result) == ["rokonkwo", "spaces"]


def test_dormant_window_is_more_than_n_days_and_new_accounts_are_spared():
    dormant_rule = rule(
        id="DRM-01",
        type="dormant_account",
        severity="Medium",
        parameters={"inactive_days": 90},
    )
    result = run_review(
        people(
            {"employee_id": "E1", "name": "Old Login"},
            {"employee_id": "E2", "name": "Cutoff"},
            {"employee_id": "E3", "name": "Just Over"},
            {"employee_id": "E4", "name": "New Starter"},
            {"employee_id": "E5", "name": "Never Used"},
            {"employee_id": "E6", "name": "No Dates"},
        ),
        accounts(
            # 2026-07-02 is exactly 90 days before 2026-09-30, so it passes.
            {"username": "cutoff", "employee_id": "E2", "last_login": "2026-07-02"},
            {"username": "just_over", "employee_id": "E3", "last_login": "2026-07-01"},
            {"username": "old_login", "employee_id": "E1", "last_login": "2026-01-15"},
            {"username": "new_starter", "employee_id": "E4", "last_login": "", "created_date": "2026-09-01"},
            {"username": "never_used", "employee_id": "E5", "last_login": "", "created_date": "2024-06-01"},
            {"username": "no_dates", "employee_id": "E6", "last_login": "", "created_date": ""},
        ),
        config(dormant_rule),
    )
    assert names(result) == ["just_over", "never_used", "no_dates", "old_login"]
    old = next(item for item in result.findings if item.username == "old_login")
    assert "258 days" in old.evidence
    assert "threshold 90 days" in old.evidence


def test_dormant_threshold_comes_from_the_rule_file():
    short_window = rule(type="dormant_account", parameters={"inactive_days": 30})
    result = run_review(
        people(),
        accounts({"last_login": "2026-08-01"}),
        config(short_window),
    )
    assert names(result) == ["wchen"]

    default_window = rule(type="dormant_account", parameters={})
    result = run_review(
        people(),
        accounts({"last_login": "2026-08-01"}),
        config(default_window),
    )
    assert names(result) == []


def test_segregation_conflict_is_one_finding_per_pair_and_split_duties_pass():
    sod = rule(
        id="SOD-01",
        type="segregation_of_duties",
        parameters={
            "conflict_pairs": [
                ["create_payment", "approve_payment"],
                ["create_vendor", "approve_vendor"],
            ]
        },
    )
    result = run_review(
        people(
            {"employee_id": "E1", "name": "Grace Ibarra"},
            {"employee_id": "E2", "name": "Ben Cho"},
            {"employee_id": "E3", "name": "Sara Lind"},
            {"employee_id": "E4", "name": "Both Pairs"},
        ),
        accounts(
            {"username": "gibarra", "employee_id": "E1", "roles": "Create_Payment; Approve_Payment"},
            {"username": "bcho", "employee_id": "E2", "roles": "create_payment"},
            {"username": "slind", "employee_id": "E3", "roles": "approve_payment"},
            {
                "username": "both",
                "employee_id": "E4",
                "roles": "create_payment;approve_payment;create_vendor;approve_vendor",
            },
        ),
        config(sod),
    )
    flagged = [(item.username, item.evidence) for item in result.findings]
    assert ("bcho",) not in [(name,) for name, _ in flagged]
    assert any(name == "gibarra" and "create_payment and approve_payment" in evidence for name, evidence in flagged)
    both = [evidence for name, evidence in flagged if name == "both"]
    assert len(both) == 2


def test_custom_conflict_pair_is_what_the_yaml_says():
    sod = rule(
        type="segregation_of_duties",
        parameters={"conflict_pairs": [["request_access", "approve_access"]]},
    )
    result = run_review(
        people({"employee_id": "E1"}, {"employee_id": "E2", "name": "Other"}),
        accounts(
            {"username": "payer", "employee_id": "E1", "roles": "create_payment;approve_payment"},
            {"username": "access", "employee_id": "E2", "roles": "request_access;approve_access"},
        ),
        config(sod),
    )
    assert names(result) == ["access"]


def test_account_created_after_termination_and_the_cases_that_pass():
    pst = rule(id="PST-01", type="created_after_termination")
    result = run_review(
        people(
            {"employee_id": "E1", "name": "Helen Cho", "status": "terminated", "termination_date": "2026-01-10"},
            {"employee_id": "E2", "name": "Marcus Hale", "status": "terminated", "termination_date": "2026-06-15"},
            {"employee_id": "E3", "name": "Same Day", "status": "terminated", "termination_date": "2026-06-15"},
            {"employee_id": "E4", "name": "Rehire", "status": "active", "termination_date": "2020-01-01"},
        ),
        accounts(
            # 2026-03-01 is after the 2026-01-10 termination. 2024-02-01 is before.
            {"username": "hcho", "employee_id": "E1", "created_date": "2026-03-01"},
            {"username": "mhale", "employee_id": "E2", "created_date": "2024-02-01"},
            {"username": "sameday", "employee_id": "E3", "created_date": "2026-06-15"},
            {"username": "rehire", "employee_id": "E4", "created_date": "2024-05-01"},
        ),
        config(pst),
    )
    assert names(result) == ["hcho"]
    assert "after the termination date 2026-01-10" in result.findings[0].evidence


def test_a_disabled_rule_does_not_fire_even_when_the_population_would_fail_it():
    population_hr = people({"status": "terminated", "termination_date": "2026-06-15"})
    population_accounts = accounts()
    result = run_review(
        population_hr,
        population_accounts,
        config(
            rule(id="TER-01", enabled=False),
            rule(id="DRM-01", type="dormant_account", severity="Medium"),
        ),
    )
    assert names(result) == []
    assert result.overall_rating == "Satisfactory"
    assert [item.id for item in result.disabled_rules] == ["TER-01"]


def test_rules_are_independent_on_the_same_account():
    result = run_review(
        people({"employee_id": "E1", "name": "Owen Briggs", "status": "terminated", "termination_date": "2026-09-01"}),
        accounts(
            {
                "username": "obriggs",
                "employee_id": "E1",
                "roles": "create_payment;approve_payment",
                "created_date": "2022-05-01",
                "last_login": "2026-08-28",
            }
        ),
        config(
            rule(id="TER-01", type="terminated_with_access"),
            rule(
                id="SOD-01",
                type="segregation_of_duties",
                parameters={"conflict_pairs": [["create_payment", "approve_payment"]]},
            ),
            rule(id="PST-01", type="created_after_termination"),
        ),
    )
    assert names(result, "TER-01") == ["obriggs"]
    assert names(result, "SOD-01") == ["obriggs"]
    assert names(result, "PST-01") == []


def test_overall_rating_is_the_highest_severity_present():
    result = run_review(
        people({"employee_id": "E1"}, {"employee_id": "E2", "name": "Other"}),
        accounts(
            {"username": "orphan", "employee_id": ""},
            {"username": "admin", "employee_id": "E2", "is_admin": "TRUE", "approval_ticket": ""},
        ),
        config(
            rule(id="ORP-01", type="orphan_account", severity="Medium"),
            rule(id="ADM-01", type="privileged_without_approval", severity="High"),
        ),
    )
    assert result.overall_rating == "High"
    assert result.accounts_with_exceptions == 2


def test_unknown_rule_type_is_rejected(tmp_path):
    from access_review.loader import load_rules

    path = tmp_path / "rules.yaml"
    path.write_text(
        """
organization: Sample
system_name: LedgerOne
review_date: "2026-09-30"
rules:
  - id: BAD-01
    type: not_a_test
    name: Bad
    severity: High
    control_objective: Objective.
    remediation: Fix it.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown type"):
        load_rules(path)


def test_duplicate_employee_id_and_missing_column_are_rejected():
    with pytest.raises(ValueError, match="Duplicate employee_id"):
        run_review(
            people({"employee_id": "E1"}, {"employee_id": "E1", "name": "Other"}),
            accounts({"employee_id": "E1"}),
            config(rule()),
        )
    with pytest.raises(ValueError, match="missing columns"):
        run_review(
            pd.DataFrame([{"employee_id": "E1", "name": "Wei Chen"}]),
            accounts(),
            config(rule()),
        )


def test_role_header_alias_and_bad_date_are_rejected(tmp_path):
    from access_review.loader import load_accounts

    good = tmp_path / "accounts.csv"
    good.write_text(
        "username,employee_id,role(s),is_admin,last_login,created_date,approval_ticket\n"
        "wchen,E1,view_reports,TRUE,2026-09-01,2024-01-01,ACC-1\n",
        encoding="utf-8",
    )
    loaded = load_accounts(good)
    assert loaded.loc[0, "roles"] == "view_reports"
    assert bool(loaded.loc[0, "is_admin"]) is True

    bad = tmp_path / "bad.csv"
    bad.write_text(
        "username,employee_id,roles,is_admin,last_login,created_date,approval_ticket\n"
        "wchen,E1,view_reports,FALSE,not-a-date,2024-01-01,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="last_login"):
        load_accounts(bad)
