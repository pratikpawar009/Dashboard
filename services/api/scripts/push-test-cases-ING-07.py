#!/usr/bin/env python3
"""Phase 4b — push ING-07 test cases as GitHub issues, cap=15, per issue-tracking-github SKILL."""
import json
import pathlib
import re
import subprocess
import sys

REPO = "pratikpawar009/Dashboard"
PARENT_NUM = 46
PARENT_KEY = f"{REPO}#{PARENT_NUM}"
CAP = 15
# Resolve relative to repo root: this file lives at services/api/scripts/
# → parents[3] is the repo root (mirrors generate_rollup_golden_snapshots.py's
# API_ROOT = Path(__file__).resolve().parent.parent convention, extended one
# level up because we point outside the api service tree).
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TC_PATH = REPO_ROOT / "docs/test-cases/ING-07.json"

SECRET_PATTERNS = [r"ghp_", r"xoxb-", r"sk_live_", r"AKIA"]
SUSPECT_KEYS = re.compile(r"password|token|secret|apikey|pin", re.IGNORECASE)


def scan_for_secrets(case: dict) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")
        elif isinstance(obj, str):
            for p in SECRET_PATTERNS:
                if re.search(p, obj):
                    hits.append((path, obj[:60]))
                    return

    walk(case, "")
    return hits


def render_body(case: dict) -> str:
    obj = case.get("objective") or case.get("title", "")
    preconds = case.get("preconditions") or []
    test_data = case.get("test_data") or {}
    steps = case.get("steps") or []
    expected = case.get("expected_results") or []
    tags = case.get("tags") or []
    ttype = case.get("type", "")
    category = case.get("category", "")
    priority = case.get("priority", "")

    parts = [f"Test case for #{PARENT_NUM}", "", f"**Objective:** {obj}", ""]
    if preconds:
        parts.append("**Preconditions:**")
        for p in preconds:
            parts.append(f"- {p}")
        parts.append("")
    if test_data:
        rendered = ", ".join(f"{k}={v}" for k, v in test_data.items())
        parts.append(f"**Test Data:** {rendered}")
        parts.append("")
    if steps:
        parts.append("**Steps:**")
        for i, s in enumerate(steps, 1):
            parts.append(f"{i}. {s}")
        parts.append("")
    if expected:
        parts.append("**Expected Results:**")
        for e in expected:
            parts.append(f"- {e}")
        parts.append("")
    parts.append(
        f"**Type:** {ttype} · **Category:** {category} · "
        f"**Priority:** {priority} · **Tags:** {', '.join(tags) if tags else '—'}"
    )
    return "\n".join(parts)


def gh_run(args: list[str], input_text: str | None = None) -> str:
    result = subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def create_issue(title: str, body: str) -> tuple[int, int]:
    """Create issue via gh api (safer than gh issue create — bypasses label pre-check).
    Returns (issue_number, rest_id)."""
    payload = json.dumps({"title": title, "body": body, "labels": ["TestCase"]})
    out = gh_run(
        ["gh", "api", "--method", "POST", f"/repos/{REPO}/issues", "--input", "-"],
        input_text=payload,
    )
    data = json.loads(out)
    return data["number"], data["id"]


def link_sub_issue(sub_rest_id: int) -> None:
    subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"/repos/{REPO}/issues/{PARENT_NUM}/sub_issues",
            "-F",
            f"sub_issue_id={sub_rest_id}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def main() -> int:
    doc = json.loads(TC_PATH.read_text())
    cases = doc.get("cases") or doc.get("test_cases") or []
    print(f"Loaded {len(cases)} cases from {TC_PATH}")

    ensure_label()

    pushed = 0
    dropped_secret: list[str] = []
    skipped_already: list[str] = []
    remaining: list[str] = []

    for case in cases:
        cid = case.get("id", "?")

        # Idempotency: already pushed
        if case.get("tracker_test"):
            skipped_already.append(cid)
            continue

        # Cap reached — collect remainder
        if pushed >= CAP:
            remaining.append(cid)
            continue

        # Pre-push secret scan (per-case, defensive)
        hits = scan_for_secrets(case)
        if hits:
            dropped_secret.append(f"{cid} ({hits[0][0]})")
            print(f"  DROP {cid} — secret pattern at {hits[0][0]}", file=sys.stderr)
            continue

        title = f"{cid}: {case.get('title', '').strip()}"
        body = render_body(case)

        print(f"  push {cid} → creating issue …", end=" ", flush=True)
        try:
            num, rest_id = create_issue(title, body)
        except subprocess.CalledProcessError as e:
            print(f"CREATE FAILED\n  stderr: {e.stderr}", file=sys.stderr)
            return 1
        try:
            link_sub_issue(rest_id)
        except subprocess.CalledProcessError as e:
            # Recorded before link per SKILL — still record the key
            case["tracker_test"] = f"{REPO}#{num}"
            TC_PATH.write_text(json.dumps(doc, indent=2) + "\n")
            print(
                f"CREATED #{num} but LINK FAILED\n  stderr: {e.stderr}",
                file=sys.stderr,
            )
            return 1

        case["tracker_test"] = f"{REPO}#{num}"
        TC_PATH.write_text(json.dumps(doc, indent=2) + "\n")
        print(f"#{num} ✓")
        pushed += 1

    total_candidates = len(cases) - len(skipped_already) - len(dropped_secret)
    print()
    print(f"Pushed:            {pushed}/{total_candidates} candidates (cap={CAP})")
    print(f"Skipped (already): {len(skipped_already)} — {skipped_already}")
    print(f"Dropped (secret):  {len(dropped_secret)} — {dropped_secret}")
    print(f"Remaining:         {len(remaining)} — {remaining}")
    return 0


def ensure_label() -> None:
    """Best-effort create the TestCase label."""
    subprocess.run(
        [
            "gh",
            "label",
            "create",
            "TestCase",
            "--repo",
            REPO,
            "--color",
            "5319e7",
            "--description",
            "Individual test case",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


if __name__ == "__main__":
    sys.exit(main())
