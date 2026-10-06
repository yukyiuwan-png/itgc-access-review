"""The six access tests.

Each function answers one question an IT auditor asks of an active-user
export. Presence in that export is treated as "the account is active":
this tool does not see a separate disabled-user list.

The checks share one signature so rules.yaml can turn them on by type.
Some tests do not use the review date; it is still passed in so the
caller does not special-case them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from access_review.loader import Config, Rule, normalize_accounts, normalize_hr

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


@dataclass
class Finding:
    """One exception row. Every field is already a display string."""

    rule_id: str
    rule_name: str
    severity: str
    control_objective: str
    control_domain: str
    iso_controls: str
    username: str
    employee_id: str
    employee_name: str
    department: str
    manager: str
    hr_status: str
    roles: str
    is_admin: str
    last_login: str
    created_date: str
    approval_ticket: str
    evidence: str
    remediation: str


@dataclass
class ReviewResult:
    """Population totals plus the exception list."""

    organization: str
    system_name: str
    review_date: pd.Timestamp
    control_domain: str
    hr_source: str
    accounts_source: str
    rules_source: str
    employee_count: int
    active_employees: int
    terminated_employees: int
    account_count: int
    rules: list[Rule]
    findings: list[Finding]

    def for_rule(self, rule_id: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.rule_id == rule_id]

    @property
    def enabled_rules(self) -> list[Rule]:
        return [rule for rule in self.rules if rule.enabled]

    @property
    def disabled_rules(self) -> list[Rule]:
        return [rule for rule in self.rules if not rule.enabled]

    @property
    def accounts_with_exceptions(self) -> int:
        return len({finding.username for finding in self.findings})

    @property
    def overall_rating(self) -> str:
        """Highest severity among the exceptions, or Satisfactory when there are none."""
        best = 99
        label = "Satisfactory"
        for finding in self.findings:
            score = SEVERITY_ORDER.get(finding.severity, 9)
            if score < best:
                best = score
                label = finding.severity
        return label


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
    except TypeError:
        missing = False
    if missing is True:
        return ""
    return str(value).strip()


def _has_date(value: object) -> bool:
    return _text(value) != "" and not pd.isna(value)


def _fmt_date(value: object) -> str:
    if not _has_date(value):
        return ""
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return ""
    return stamp.strftime("%Y-%m-%d")


def _days_between(later: object, earlier: object) -> int:
    return int((pd.Timestamp(later).normalize() - pd.Timestamp(earlier).normalize()).days)


def _split_roles(value: object) -> list[str]:
    return [part.strip() for part in _text(value).split(";") if part.strip()]


def make_finding(row: dict, rule: Rule, evidence: str) -> Finding:
    """Copy the evidence fields off one joined account row."""
    matched = bool(row.get("_matched"))
    return Finding(
        rule_id=rule.id,
        rule_name=rule.name,
        severity=rule.severity,
        control_objective=rule.control_objective,
        control_domain=rule.control_domain,
        iso_controls=rule.iso_text(),
        username=_text(row.get("username")),
        employee_id=_text(row.get("employee_id")),
        employee_name=_text(row.get("name")) if matched else "",
        department=_text(row.get("department")) if matched else "",
        manager=_text(row.get("manager")) if matched else "",
        hr_status=_text(row.get("status")) if matched else "no HR record",
        roles=_text(row.get("roles")),
        is_admin="Yes" if bool(row.get("is_admin")) else "No",
        last_login=_fmt_date(row.get("last_login")),
        created_date=_fmt_date(row.get("created_date")),
        approval_ticket=_text(row.get("approval_ticket")),
        evidence=evidence,
        remediation=rule.remediation,
    )


def terminated_with_access(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """A leaver is still on the active account export."""
    del review_date  # This test compares status, not the review date.
    findings: list[Finding] = []
    for row in population.to_dict(orient="records"):
        if not row.get("_matched") or _text(row.get("status")) != "terminated":
            continue
        term = _fmt_date(row.get("termination_date"))
        when = f" on {term}" if term else ", with no termination date recorded"
        evidence = (
            f"HR status is terminated{when}, and username {_text(row.get('username'))} "
            "is still on the active account export."
        )
        findings.append(make_finding(row, rule, evidence))
    return findings


def orphan_account(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """The account's employee id is blank or missing from HR."""
    del review_date
    findings: list[Finding] = []
    for row in population.to_dict(orient="records"):
        if row.get("_matched"):
            continue
        shown = _text(row.get("employee_id")) or "(blank)"
        evidence = (
            f"Username {_text(row.get('username'))} has employee_id {shown}, "
            "which does not match any row in the HR roster."
        )
        findings.append(make_finding(row, rule, evidence))
    return findings


def privileged_without_approval(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """Admin access with no approval-ticket reference.

    The test checks that a ticket id is present. It cannot tell whether
    the ticket was approved by the right owner.
    """
    del review_date
    findings: list[Finding] = []
    for row in population.to_dict(orient="records"):
        if not bool(row.get("is_admin")):
            continue
        if _text(row.get("approval_ticket")):
            continue
        evidence = (
            f"Username {_text(row.get('username'))} is an admin account "
            "and the approval ticket is blank."
        )
        findings.append(make_finding(row, rule, evidence))
    return findings


def dormant_account(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """No login within the last N days (default 90).

    A login exactly N days before the review date is still inside the
    window. A brand-new account with no login yet is not dormant until
    the account itself is older than N days. If the created date is
    missing as well, there is no evidence of recent use, so it fails.
    """
    limit = int(rule.parameters.get("inactive_days", 90))
    findings: list[Finding] = []
    as_of = _fmt_date(review_date)
    for row in population.to_dict(orient="records"):
        last_login = row.get("last_login")
        created = row.get("created_date")
        if _has_date(last_login):
            idle = _days_between(review_date, last_login)
            if idle > limit:
                evidence = (
                    f"Last login {_fmt_date(last_login)} is {idle} days before "
                    f"the review date {as_of} (threshold {limit} days)."
                )
                findings.append(make_finding(row, rule, evidence))
            continue
        if _has_date(created):
            age = _days_between(review_date, created)
            if age > limit:
                evidence = (
                    f"No last login is recorded. The account was created on "
                    f"{_fmt_date(created)}, {age} days before the review date "
                    f"{as_of} (threshold {limit} days)."
                )
                findings.append(make_finding(row, rule, evidence))
            continue
        evidence = (
            "No last login and no created date are recorded, so the account "
            f"cannot be shown to have been used within {limit} days of {as_of}."
        )
        findings.append(make_finding(row, rule, evidence))
    return findings


def segregation_of_duties(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """The same user holds both roles in a conflicting pair.

    One exception is raised per pair, so the evidence names the conflict.
    Role names are compared without regard to case.
    """
    del review_date
    pairs = [
        (_text(pair[0]), _text(pair[1]))
        for pair in rule.parameters.get("conflict_pairs", [])
    ]
    findings: list[Finding] = []
    for row in population.to_dict(orient="records"):
        held = {role.lower() for role in _split_roles(row.get("roles"))}
        for left, right in pairs:
            if left.lower() in held and right.lower() in held:
                evidence = (
                    f"Username {_text(row.get('username'))} holds both {left} and {right}."
                )
                findings.append(make_finding(row, rule, evidence))
    return findings


def created_after_termination(
    population: pd.DataFrame, rule: Rule, review_date: pd.Timestamp
) -> list[Finding]:
    """The account was opened after the person's termination date.

    Only a current status of terminated is tested. An active employee
    with a leftover termination date (for example a rehire) is not an
    exception for this rule. Created on the termination date is allowed;
    the test is strictly after.
    """
    del review_date
    findings: list[Finding] = []
    for row in population.to_dict(orient="records"):
        if not row.get("_matched") or _text(row.get("status")) != "terminated":
            continue
        created = row.get("created_date")
        terminated = row.get("termination_date")
        if not _has_date(created) or not _has_date(terminated):
            continue
        if pd.Timestamp(created).normalize() <= pd.Timestamp(terminated).normalize():
            continue
        evidence = (
            f"Account created on {_fmt_date(created)}, after the "
            f"termination date {_fmt_date(terminated)}."
        )
        findings.append(make_finding(row, rule, evidence))
    return findings


CHECKERS: dict[str, Callable[[pd.DataFrame, Rule, pd.Timestamp], list[Finding]]] = {
    "terminated_with_access": terminated_with_access,
    "orphan_account": orphan_account,
    "privileged_without_approval": privileged_without_approval,
    "dormant_account": dormant_account,
    "segregation_of_duties": segregation_of_duties,
    "created_after_termination": created_after_termination,
}


def run_review(
    hr: pd.DataFrame,
    accounts: pd.DataFrame,
    config: Config,
    *,
    hr_source: str = "",
    accounts_source: str = "",
    rules_source: str = "",
) -> ReviewResult:
    """Join the populations and run every enabled rule.

    The join keeps every account. Blank employee ids are missing values,
    and pandas does not treat missing as equal to missing, so two accounts
    with no employee id do not match each other or the roster.
    """
    hr_ready = normalize_hr(hr)
    accounts_ready = normalize_accounts(accounts)
    population = accounts_ready.merge(hr_ready, on="employee_id", how="left", indicator=True)
    population["_matched"] = population["_merge"].eq("both")

    findings: list[Finding] = []
    for rule in config.rules:
        if not rule.enabled:
            continue
        checker = CHECKERS.get(rule.type)
        if checker is None:
            known = ", ".join(sorted(CHECKERS))
            raise ValueError(f"Rule {rule.id} has unknown type {rule.type!r}. Expected one of: {known}.")
        findings.extend(checker(population, rule, config.review_date))

    findings.sort(
        key=lambda finding: (
            SEVERITY_ORDER.get(finding.severity, 9),
            finding.rule_id,
            finding.username,
            finding.evidence,
        )
    )
    return ReviewResult(
        organization=config.organization,
        system_name=config.system_name,
        review_date=config.review_date,
        control_domain=config.control_domain,
        hr_source=hr_source,
        accounts_source=accounts_source,
        rules_source=rules_source,
        employee_count=len(hr_ready),
        active_employees=int((hr_ready["status"] == "active").sum()),
        terminated_employees=int((hr_ready["status"] == "terminated").sum()),
        account_count=len(accounts_ready),
        rules=list(config.rules),
        findings=findings,
    )
