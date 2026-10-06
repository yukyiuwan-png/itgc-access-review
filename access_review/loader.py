"""Load the HR roster, the account export, and rules.yaml.

pandas reads the two populations. PyYAML reads the rule file. Headers are
matched in a forgiving way so a spreadsheet column named "Employee ID" or
"role(s)" still loads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# Columns the review actually uses. Extra columns in the files are ignored.
HR_COLUMNS = [
    "employee_id",
    "name",
    "department",
    "status",
    "termination_date",
    "manager",
]
ACCOUNT_COLUMNS = [
    "username",
    "employee_id",
    "roles",
    "is_admin",
    "last_login",
    "created_date",
    "approval_ticket",
]

# Spreadsheet exports rarely use the same header twice.
HEADER_ALIASES = {
    "role(s)": "roles",
    "role": "roles",
    "isadmin": "is_admin",
}

RULE_TYPES = {
    "terminated_with_access",
    "orphan_account",
    "privileged_without_approval",
    "dormant_account",
    "segregation_of_duties",
    "created_after_termination",
}

SEVERITIES = {"High", "Medium", "Low"}


@dataclass
class Rule:
    """One configured test. The type selects the Python check; the rest is text."""

    id: str
    type: str
    name: str
    enabled: bool
    severity: str
    control_objective: str
    control_domain: str
    iso_controls: list[str]
    remediation: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def iso_text(self) -> str:
        if not self.iso_controls:
            return "Not mapped"
        return "; ".join(self.iso_controls)


@dataclass
class Config:
    """The review settings from rules.yaml."""

    organization: str
    system_name: str
    review_date: pd.Timestamp
    control_domain: str
    rules: list[Rule]


def _text(value: object) -> str:
    """Return a stripped string, or "" when the cell is empty."""
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
    except TypeError:
        missing = False
    if missing is True:
        return ""
    return str(value).strip()


def _canon_header(header: object) -> str:
    key = _text(header).lower().replace(" ", "_")
    return HEADER_ALIASES.get(key, key)


def _as_id(value: object) -> str | None:
    """Normalise an employee id. Blank becomes None so it cannot match another blank."""
    text = _text(value)
    if text.lower() in {"", "nan", "none", "<na>"}:
        return None
    # Spreadsheets sometimes store 1001 as 1001.0.
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    return text in {"true", "t", "yes", "y", "1"}


def _parse_dates(series: pd.Series, column: str) -> pd.Series:
    text = series.map(_text)
    parsed = pd.to_datetime(text.where(text != ""), errors="coerce")
    bad = text.ne("") & parsed.isna()
    if bad.any():
        examples = text[bad].head(3).tolist()
        raise ValueError(f"Could not read {column} as a date. Examples: {examples}.")
    return parsed


def _rename_headers(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(columns={col: _canon_header(col) for col in df.columns})
    duplicates = renamed.columns[renamed.columns.duplicated()].tolist()
    if duplicates:
        raise ValueError(f"Duplicate columns after renaming headers: {duplicates}.")
    return renamed


def _require_columns(df: pd.DataFrame, required: list[str], label: str) -> pd.DataFrame:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}.")
    return df[required].copy()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    # utf-8-sig drops the BOM Excel adds when it saves a CSV.
    # keep_default_na=False so a username is never turned into NaN by itself;
    # we decide which blanks are missing inside the normalisers.
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"{path} is empty.") from exc
    except UnicodeError as exc:
        raise ValueError(f"Could not read {path} as UTF-8.") from exc
    return _rename_headers(frame)


def normalize_hr(df: pd.DataFrame) -> pd.DataFrame:
    """Check the roster and return the columns the tests use."""
    frame = _require_columns(_rename_headers(df), HR_COLUMNS, "HR roster")
    frame["employee_id"] = frame["employee_id"].map(_as_id)
    if frame["employee_id"].isna().any():
        raise ValueError("Every HR row needs an employee_id.")
    duplicate_ids = frame.loc[frame["employee_id"].duplicated(), "employee_id"].tolist()
    if duplicate_ids:
        raise ValueError(f"Duplicate employee_id in the HR roster: {duplicate_ids}.")

    frame["name"] = frame["name"].map(_text)
    frame["department"] = frame["department"].map(_text)
    frame["manager"] = frame["manager"].map(_text)
    if frame["name"].eq("").any():
        raise ValueError("Every HR row needs a name.")

    frame["status"] = frame["status"].map(_text).str.lower()
    invalid = sorted(set(frame.loc[~frame["status"].isin(["active", "terminated"]), "status"]))
    if invalid:
        raise ValueError(
            "HR status must be active or terminated (case is ignored). "
            f"Found: {invalid}."
        )
    frame["termination_date"] = _parse_dates(frame["termination_date"], "termination_date")
    return frame.reset_index(drop=True)


def normalize_accounts(df: pd.DataFrame) -> pd.DataFrame:
    """Check the account export and return the columns the tests use."""
    frame = _require_columns(_rename_headers(df), ACCOUNT_COLUMNS, "Account export")
    frame["username"] = frame["username"].map(_text)
    if frame["username"].eq("").any():
        raise ValueError("Every account needs a username.")
    duplicate_names = frame.loc[frame["username"].duplicated(), "username"].tolist()
    if duplicate_names:
        raise ValueError(f"Duplicate username in the account export: {duplicate_names}.")

    frame["employee_id"] = frame["employee_id"].map(_as_id)
    frame["roles"] = frame["roles"].map(_text)
    frame["is_admin"] = frame["is_admin"].map(_parse_bool)
    frame["approval_ticket"] = frame["approval_ticket"].map(_text)
    frame["last_login"] = _parse_dates(frame["last_login"], "last_login")
    frame["created_date"] = _parse_dates(frame["created_date"], "created_date")
    return frame.reset_index(drop=True)


def load_hr(path: Path) -> pd.DataFrame:
    return normalize_hr(_read_csv(path))


def load_accounts(path: Path) -> pd.DataFrame:
    return normalize_accounts(_read_csv(path))


def _as_timestamp(value: object, label: str) -> pd.Timestamp:
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        raise ValueError(f"{label} is not a date: {value!r}. Use YYYY-MM-DD.")
    return pd.Timestamp(stamp).normalize()


def _yaml_text(value: object, label: str) -> str:
    text = _text(value)
    if not text:
        raise ValueError(f"{label} is required in rules.yaml.")
    return " ".join(text.split())


def _check_parameters(rule_id: str, rule_type: str, parameters: dict[str, Any]) -> None:
    if rule_type == "dormant_account" and "inactive_days" in parameters:
        days = parameters["inactive_days"]
        # bool is a subclass of int, so reject it explicitly.
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError(
                f"Rule {rule_id} inactive_days must be a positive whole number, got {days!r}."
            )
    if rule_type == "segregation_of_duties":
        pairs = parameters.get("conflict_pairs")
        if not pairs:
            raise ValueError(
                f"Rule {rule_id} needs conflict_pairs. A SoD test with no pairs "
                "would pass every user and give false assurance."
            )
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError(
                    f"Rule {rule_id} conflict pairs must be two role names, got {pair!r}."
                )
            if not _text(pair[0]) or not _text(pair[1]):
                raise ValueError(f"Rule {rule_id} has a blank role in a conflict pair.")


def load_rules(path: Path) -> Config:
    """Read rules.yaml into a Config. Unknown test types are rejected."""
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a YAML mapping.")

    control_domain = _yaml_text(
        raw.get("control_domain", "Access to programs and data"),
        "control_domain",
    )
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("rules.yaml needs a non-empty rules list.")

    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for entry in rules_raw:
        if not isinstance(entry, dict):
            raise ValueError("Each rule must be a YAML mapping.")
        rule_id = _yaml_text(entry.get("id"), "rule id")
        if rule_id in seen_ids:
            raise ValueError(f"Duplicate rule id: {rule_id}.")
        seen_ids.add(rule_id)
        rule_type = _yaml_text(entry.get("type"), f"type for {rule_id}")
        if rule_type not in RULE_TYPES:
            known = ", ".join(sorted(RULE_TYPES))
            raise ValueError(f"Rule {rule_id} has unknown type {rule_type!r}. Expected one of: {known}.")
        severity = _yaml_text(entry.get("severity"), f"severity for {rule_id}").title()
        if severity not in SEVERITIES:
            raise ValueError(f"Rule {rule_id} severity must be High, Medium, or Low.")
        parameters = entry.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError(f"Rule {rule_id} parameters must be a mapping.")
        _check_parameters(rule_id, rule_type, parameters)
        iso_raw = entry.get("iso_controls") or []
        if not isinstance(iso_raw, list):
            raise ValueError(f"Rule {rule_id} iso_controls must be a list.")
        rules.append(
            Rule(
                id=rule_id,
                type=rule_type,
                name=_yaml_text(entry.get("name"), f"name for {rule_id}"),
                enabled=bool(entry.get("enabled", True)),
                severity=severity,
                control_objective=_yaml_text(
                    entry.get("control_objective"),
                    f"control_objective for {rule_id}",
                ),
                control_domain=_yaml_text(entry.get("control_domain", control_domain), "control_domain"),
                iso_controls=[_yaml_text(item, f"iso control for {rule_id}") for item in iso_raw],
                remediation=_yaml_text(entry.get("remediation"), f"remediation for {rule_id}"),
                parameters=parameters,
            )
        )

    return Config(
        organization=_yaml_text(raw.get("organization"), "organization"),
        system_name=_yaml_text(raw.get("system_name"), "system_name"),
        review_date=_as_timestamp(raw.get("review_date"), "review_date"),
        control_domain=control_domain,
        rules=rules,
    )
