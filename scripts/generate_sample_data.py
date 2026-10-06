#!/usr/bin/env python3
"""Write the fictional HR roster and LedgerOne account export.

Harbor & Pine Trading is not a real company. Names are mixed from two
lists and are not real people. The review date assumed here is
2026-09-30, which matches rules.yaml. Dormant means more than 90 days
without a login before that date.

Planted exceptions (see tests/test_sample.py):

  TER-01  mhale, pnanda, hcho, obriggs, lvoss
          Three other leavers (E1070, E1071, E1072) have no account.
  ORP-01  svc_nightly, temp_contractor, jdoe_old, admin_legacy,
          intern_2024, vendor_portal, audit_temp, shared_inbox, svc_payroll
  ADM-01  pnanda, rokonkwo, cfernandez, admin_legacy
          wchen, hberg, polsen, and svc_payroll are admins with a ticket.
  DRM-01  hcho, jdoe_old, dbrooks, felsayed, hmartins
          mpark joined on 2026-09-01 and has never logged in: inside 90 days.
  SOD-01  obriggs, gibarra, twitek, ahaddad
          bcho can create payments and slind can approve them, not both.
  PST-01  hcho, lvoss

Run from the repository root:

    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HR_PATH = ROOT / "sample_data" / "hr.csv"
ACCOUNTS_PATH = ROOT / "sample_data" / "accounts.csv"

REVIEW = date(2026, 9, 30)
DORMANT_DAYS = 90
DIRECTOR = "Alex Rowan (Director)"

DEPARTMENTS = [
    "Finance",
    "Information Technology",
    "Human Resources",
    "Procurement",
    "Operations",
    "Sales",
    "Legal",
    "Internal Audit",
]

# One role from the department list, never both sides of a conflict pair.
SAFE_ROLES = {
    "Finance": ["view_ledger", "create_journal", "create_payment", "view_reports"],
    "Information Technology": ["view_reports", "request_access"],
    "Human Resources": ["view_reports"],
    "Procurement": ["view_ledger", "create_vendor"],
    "Operations": ["view_ledger", "view_reports"],
    "Sales": ["view_reports"],
    "Legal": ["view_reports"],
    "Internal Audit": ["view_ledger", "view_reports"],
}

FIRST_NAMES = [
    "Avery", "Jordan", "Riley", "Quinn", "Parker", "Skyler", "Rowan", "Emery",
    "Hayden", "Reese", "Blake", "Cameron", "Drew", "Finley", "Harper", "Jules",
    "Kai", "Logan", "Marlow", "Nico", "Oakley", "Payton", "Remy", "Shiloh",
    "Tatum", "Yael", "Blair", "Casey", "Devon", "Eden", "Frankie", "Gray",
    "Indigo", "Kit", "Lane", "Micah", "Noel", "Perry", "River", "Sage",
]
LAST_NAMES = [
    "Adeyemi", "Bergstrom", "Diallo", "Esposito", "Farouk", "Gupta", "Jensen",
    "Kowalski", "Lindqvist", "Moreau", "Nakamura", "Okafor", "Petrov", "Quintero",
    "Rahman", "Silva", "Tanaka", "Ueda", "Vasquez", "Walsh", "Xu", "Yamamoto",
    "Zimmerman", "Andersson", "Bhandari", "Costa", "Duval", "Engel", "Fischer",
    "Horvat", "Ivanov", "Johansson", "Khan", "Larsen", "Mbeki", "Novak",
    "Papadopoulos", "Rossi", "Sato", "Tremblay", "Vogel", "Yilmaz", "Zhou",
]

# Active employees whose account is hand-written so the exception is deliberate.
SPECIAL_ACTIVE = [
    # Ticket on file: privileged access that should pass ADM-01.
    dict(employee_id="E1001", name="Wei Chen", department="Information Technology",
         username="wchen", roles="manage_users", is_admin=True,
         approval_ticket="ACC-2024-1180", last_login="2026-09-28", created_date="2022-04-11"),
    dict(employee_id="E1008", name="Hannah Berg", department="Information Technology",
         username="hberg", roles="manage_users", is_admin=True,
         approval_ticket="ACC-2025-0044", last_login="2026-09-21", created_date="2023-01-16"),
    dict(employee_id="E1015", name="Patrick Olsen", department="Information Technology",
         username="polsen", roles="manage_users;approve_access", is_admin=True,
         approval_ticket="ACC-2025-0210", last_login="2026-09-12", created_date="2021-11-02"),
    # ADM-01: admin, no ticket, still employed.
    dict(employee_id="E1010", name="Ruth Okonkwo", department="Information Technology",
         username="rokonkwo", roles="manage_users", is_admin=True,
         approval_ticket="", last_login="2026-09-18", created_date="2024-02-01"),
    dict(employee_id="E1022", name="Carmen Fernandez", department="Finance",
         username="cfernandez", roles="manage_users;view_ledger", is_admin=True,
         approval_ticket="", last_login="2026-09-03", created_date="2023-08-19"),
    # DRM-01: last login, or no login at all, outside the 90-day window.
    dict(employee_id="E1030", name="Daniel Brooks", department="Sales",
         username="dbrooks", roles="view_reports", is_admin=False,
         approval_ticket="", last_login="2026-01-15", created_date="2022-06-01"),
    dict(employee_id="E1031", name="Fatima El-Sayed", department="Operations",
         username="felsayed", roles="view_ledger", is_admin=False,
         approval_ticket="", last_login="", created_date="2024-06-01"),
    dict(employee_id="E1032", name="Hugo Martins", department="Procurement",
         username="hmartins", roles="create_vendor", is_admin=False,
         approval_ticket="", last_login="2026-05-01", created_date="2021-09-14"),
    # New starter inside the window. No login yet, and that is not dormant.
    dict(employee_id="E1040", name="Mina Park", department="Human Resources",
         username="mpark", roles="view_reports", is_admin=False,
         approval_ticket="", last_login="", created_date="2026-09-01"),
    # SOD-01: both sides of a pair on one user.
    dict(employee_id="E1045", name="Grace Ibarra", department="Finance",
         username="gibarra", roles="create_payment;approve_payment", is_admin=False,
         approval_ticket="", last_login="2026-09-16", created_date="2022-02-02"),
    dict(employee_id="E1046", name="Tomasz Witek", department="Procurement",
         username="twitek", roles="create_vendor;approve_vendor", is_admin=False,
         approval_ticket="", last_login="2026-09-11", created_date="2023-05-23"),
    dict(employee_id="E1047", name="Amira Haddad", department="Finance",
         username="ahaddad", roles="create_journal;approve_journal", is_admin=False,
         approval_ticket="", last_login="2026-08-30", created_date="2020-10-10"),
    # The same duties, split across two people. These should pass SOD-01.
    dict(employee_id="E1048", name="Ben Cho", department="Finance",
         username="bcho", roles="create_payment", is_admin=False,
         approval_ticket="", last_login="2026-09-22", created_date="2024-01-08"),
    dict(employee_id="E1049", name="Sara Lind", department="Finance",
         username="slind", roles="approve_payment", is_admin=False,
         approval_ticket="", last_login="2026-09-19", created_date="2023-03-03"),
]

# Leavers. account=None means access was removed, which is the control working.
TERMINATED = [
    dict(employee_id="E1065", name="Marcus Hale", department="Finance",
         termination_date="2026-06-15",
         account=dict(username="mhale", roles="create_journal", is_admin=False,
                      approval_ticket="", last_login="2026-08-20", created_date="2024-02-01")),
    dict(employee_id="E1066", name="Priya Nandakumar", department="Information Technology",
         termination_date="2026-08-01",
         account=dict(username="pnanda", roles="manage_users", is_admin=True,
                      approval_ticket="", last_login="2026-07-20", created_date="2023-11-01")),
    dict(employee_id="E1067", name="Helen Cho", department="Procurement",
         termination_date="2026-01-10",
         account=dict(username="hcho", roles="create_vendor", is_admin=False,
                      approval_ticket="", last_login="", created_date="2026-03-01")),
    dict(employee_id="E1068", name="Owen Briggs", department="Operations",
         termination_date="2026-09-01",
         account=dict(username="obriggs", roles="create_payment;approve_payment", is_admin=False,
                      approval_ticket="", last_login="2026-08-28", created_date="2022-05-01")),
    dict(employee_id="E1069", name="Lena Voss", department="Sales",
         termination_date="2026-04-01",
         account=dict(username="lvoss", roles="view_reports", is_admin=False,
                      approval_ticket="", last_login="2026-09-15", created_date="2026-04-15")),
    dict(employee_id="E1070", name="Samuel Adeyemi", department="Human Resources",
         termination_date="2026-05-20", account=None),
    dict(employee_id="E1071", name="Nora Feldman", department="Legal",
         termination_date="2026-07-01", account=None),
    dict(employee_id="E1072", name="Chris Dalton", department="Operations",
         termination_date="2026-02-28", account=None),
]

# No HR row. svc_payroll has a ticket, so it is an orphan but not ADM-01.
ORPHANS = [
    dict(username="svc_nightly", employee_id="", roles="view_reports", is_admin=False,
         last_login="2026-09-28", created_date="2024-01-15", approval_ticket=""),
    dict(username="temp_contractor", employee_id="C-8841", roles="view_ledger", is_admin=False,
         last_login="2026-09-10", created_date="2026-08-01", approval_ticket=""),
    dict(username="jdoe_old", employee_id="E0007", roles="view_reports", is_admin=False,
         last_login="2025-11-02", created_date="2022-03-01", approval_ticket=""),
    dict(username="admin_legacy", employee_id="", roles="manage_users", is_admin=True,
         last_login="2026-09-20", created_date="2019-06-01", approval_ticket=""),
    dict(username="intern_2024", employee_id="E7777", roles="view_ledger", is_admin=False,
         last_login="2026-09-01", created_date="2024-06-01", approval_ticket=""),
    dict(username="vendor_portal", employee_id="V-100", roles="view_reports", is_admin=False,
         last_login="2026-08-15", created_date="2025-01-01", approval_ticket=""),
    dict(username="audit_temp", employee_id="X-22", roles="view_ledger", is_admin=False,
         last_login="2026-09-25", created_date="2026-09-01", approval_ticket=""),
    dict(username="shared_inbox", employee_id="", roles="view_reports", is_admin=False,
         last_login="2026-08-20", created_date="2020-01-01", approval_ticket=""),
    dict(username="svc_payroll", employee_id="", roles="manage_users", is_admin=True,
         last_login="2026-09-27", created_date="2021-04-04", approval_ticket="ACC-2023-0881"),
]

CONFLICT_PAIRS = [
    ("create_payment", "approve_payment"),
    ("create_vendor", "approve_vendor"),
    ("create_journal", "approve_journal"),
    ("request_access", "approve_access"),
]
PLANTED_SOD = {"obriggs", "gibarra", "twitek", "ahaddad"}
PLANTED_DORMANT = {"hcho", "jdoe_old", "dbrooks", "felsayed", "hmartins"}
PLANTED_ADMIN_GAP = {"pnanda", "rokonkwo", "cfernandez", "admin_legacy"}


def _rand_date(rng: random.Random, start: date, end: date) -> str:
    span = (end - start).days
    return (start + timedelta(days=rng.randrange(span + 1))).isoformat()


def _base_username(name: str) -> str:
    parts = [part for part in name.replace("-", " ").split() if part]
    last = "".join(char for char in parts[-1] if char.isalpha())
    return (parts[0][0] + last).lower()


def _unique_username(name: str, used: set[str]) -> str:
    base = _base_username(name)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _hr_row(employee_id: str, name: str, department: str, status: str, termination_date: str) -> dict:
    return {
        "employee_id": employee_id,
        "name": name,
        "department": department,
        "status": status,
        "termination_date": termination_date,
        "manager": "",
    }


def _account_row(username, employee_id, roles, is_admin, last_login, created_date, approval_ticket) -> dict:
    return {
        "username": username,
        "employee_id": employee_id,
        "roles": roles,
        "is_admin": "TRUE" if is_admin else "FALSE",
        "last_login": last_login,
        "created_date": created_date,
        "approval_ticket": approval_ticket,
    }


def _assign_managers(employees: list[dict]) -> None:
    """The lowest active id in a department manages the rest. The head reports to the director."""
    heads: dict[str, str] = {}
    active = [person for person in employees if person["status"] == "active"]
    for person in sorted(active, key=lambda item: item["employee_id"]):
        department = person["department"]
        if department not in heads:
            heads[department] = person["name"]
            person["manager"] = DIRECTOR
        else:
            person["manager"] = heads[department]
    for person in employees:
        if person["status"] != "terminated":
            continue
        person["manager"] = heads.get(person["department"], DIRECTOR)


def build_population(seed: int = 42) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    specials = {person["employee_id"]: person for person in SPECIAL_ACTIVE}
    reserved_names = {person["name"] for person in SPECIAL_ACTIVE}
    reserved_names.update(person["name"] for person in TERMINATED)
    used_usernames = {person["username"] for person in SPECIAL_ACTIVE}
    used_usernames.update(person["account"]["username"] for person in TERMINATED if person["account"])
    used_usernames.update(account["username"] for account in ORPHANS)

    employees: list[dict] = []
    department_cursor = 0
    for number in range(1, 65):
        employee_id = f"E{1000 + number}"
        special = specials.get(employee_id)
        if special is not None:
            employees.append(
                _hr_row(employee_id, special["name"], special["department"], "active", "")
            )
            continue
        name = _fresh_name(rng, reserved_names)
        department = DEPARTMENTS[department_cursor % len(DEPARTMENTS)]
        department_cursor += 1
        employees.append(_hr_row(employee_id, name, department, "active", ""))

    for person in TERMINATED:
        employees.append(
            _hr_row(
                person["employee_id"],
                person["name"],
                person["department"],
                "terminated",
                person["termination_date"],
            )
        )
    _assign_managers(employees)

    accounts: list[dict] = []
    primary_username: dict[str, str] = {}
    generated = {person["employee_id"]: person for person in employees if person["status"] == "active"}

    for employee_id in sorted(generated):
        special = specials.get(employee_id)
        if special is not None:
            primary_username[employee_id] = special["username"]
            accounts.append(
                _account_row(
                    special["username"],
                    employee_id,
                    special["roles"],
                    special["is_admin"],
                    special["last_login"],
                    special["created_date"],
                    special["approval_ticket"],
                )
            )
            continue
        person = generated[employee_id]
        username = _unique_username(person["name"], used_usernames)
        primary_username[employee_id] = username
        role = rng.choice(SAFE_ROLES[person["department"]])
        accounts.append(
            _account_row(
                username,
                employee_id,
                role,
                False,
                _rand_date(rng, date(2026, 8, 1), date(2026, 9, 29)),
                _rand_date(rng, date(2021, 2, 1), date(2026, 5, 31)),
                "",
            )
        )

    # A second, read-only id for the first 24 active employees.
    for number in range(1, 25):
        employee_id = f"E{1000 + number}"
        username = f"{primary_username[employee_id]}_rpt"
        if username in used_usernames:
            raise SystemExit(f"Report-account username already used: {username}")
        used_usernames.add(username)
        accounts.append(
            _account_row(username, employee_id, "view_reports", False, "2026-09-10", "2024-05-01", "")
        )

    for person in TERMINATED:
        account = person["account"]
        if account is None:
            continue
        accounts.append(
            _account_row(
                account["username"],
                person["employee_id"],
                account["roles"],
                account["is_admin"],
                account["last_login"],
                account["created_date"],
                account["approval_ticket"],
            )
        )

    for orphan in ORPHANS:
        accounts.append(
            _account_row(
                orphan["username"],
                orphan["employee_id"],
                orphan["roles"],
                orphan["is_admin"],
                orphan["last_login"],
                orphan["created_date"],
                orphan["approval_ticket"],
            )
        )

    employees.sort(key=lambda item: item["employee_id"])
    accounts.sort(key=lambda item: item["username"])
    _check_population(employees, accounts)
    return employees, accounts


def _fresh_name(rng: random.Random, reserved: set[str]) -> str:
    for _ in range(1000):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in reserved:
            reserved.add(name)
            return name
    raise RuntimeError("Could not draw a unique fictional name.")


def _is_dormant(last_login: str, created: str) -> bool:
    if last_login:
        return (REVIEW - date.fromisoformat(last_login)).days > DORMANT_DAYS
    if created:
        return (REVIEW - date.fromisoformat(created)).days > DORMANT_DAYS
    return True


def _has_conflict(roles: str) -> bool:
    held = {role.strip().lower() for role in roles.split(";") if role.strip()}
    return any(left in held and right in held for left, right in CONFLICT_PAIRS)


def _check_population(employees: list[dict], accounts: list[dict]) -> None:
    """Fail the generator if the filler rows accidentally become exceptions."""
    if len(employees) != 72:
        raise SystemExit(f"Expected 72 employees, got {len(employees)}.")
    if len(accounts) != 102:
        raise SystemExit(f"Expected 102 accounts, got {len(accounts)}.")
    usernames = [row["username"] for row in accounts]
    if len(usernames) != len(set(usernames)):
        raise SystemExit("Duplicate username in the generated export.")

    by_id = {person["employee_id"]: person for person in employees}
    dormant = set()
    conflicts = set()
    admin_gaps = set()
    for row in accounts:
        if _is_dormant(row["last_login"], row["created_date"]):
            dormant.add(row["username"])
        if _has_conflict(row["roles"]):
            conflicts.add(row["username"])
        if row["is_admin"] == "TRUE" and not row["approval_ticket"]:
            admin_gaps.add(row["username"])
        employee_id = row["employee_id"]
        if employee_id and employee_id in by_id:
            person = by_id[employee_id]
            if person["status"] == "terminated" and row["created_date"] > person["termination_date"]:
                if row["username"] not in {"hcho", "lvoss"}:
                    raise SystemExit(f"Unexpected post-termination account: {row['username']}")
    if dormant != PLANTED_DORMANT:
        raise SystemExit(f"Dormant usernames drifted: {sorted(dormant)}")
    if conflicts != PLANTED_SOD:
        raise SystemExit(f"SoD usernames drifted: {sorted(conflicts)}")
    if admin_gaps != PLANTED_ADMIN_GAP:
        raise SystemExit(f"Admin-without-ticket usernames drifted: {sorted(admin_gaps)}")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    employees, accounts = build_population()
    _write_csv(
        HR_PATH,
        employees,
        ["employee_id", "name", "department", "status", "termination_date", "manager"],
    )
    _write_csv(
        ACCOUNTS_PATH,
        accounts,
        ["username", "employee_id", "roles", "is_admin", "last_login", "created_date", "approval_ticket"],
    )
    print(f"Wrote {len(employees)} employees to {HR_PATH}")
    print(f"Wrote {len(accounts)} accounts to {ACCOUNTS_PATH}")


if __name__ == "__main__":
    main()
