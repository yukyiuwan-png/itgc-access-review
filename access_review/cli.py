"""Command line entry point for the access review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from access_review.engine import run_review
from access_review.loader import load_accounts, load_hr, load_rules
from access_review.report import format_console, write_excel, write_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m access_review",
        description=(
            "Run an ITGC user access review. "
            "Joins an HR roster to a system account export and writes the exceptions."
        ),
    )
    parser.add_argument("--hr", required=True, help="HR roster CSV")
    parser.add_argument("--accounts", required=True, help="System account export CSV")
    parser.add_argument("--rules", required=True, help="Rule configuration YAML")
    parser.add_argument("--out", required=True, help="Directory for the Excel and HTML reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)
    excel_path = out_dir / "itgc_access_review.xlsx"
    html_path = out_dir / "itgc_access_review.html"
    try:
        hr_path = Path(args.hr)
        accounts_path = Path(args.accounts)
        rules_path = Path(args.rules)
        config = load_rules(rules_path)
        result = run_review(
            load_hr(hr_path),
            load_accounts(accounts_path),
            config,
            hr_source=str(hr_path),
            accounts_source=str(accounts_path),
            rules_source=str(rules_path),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        write_excel(result, excel_path)
        write_html(result, html_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_console(result, excel_path, html_path))
    return 0
