"""Summarize a coverage.py Cobertura XML report in the job log and step summary.

    python summarize_coverage.py coverage.xml [baseline.xml] [changed-files.txt]
        [coverage-summary.md]

baseline.xml is main's latest report, for the change in total coverage.
changed-files.txt lists the files the PR changes, one per line. Either may be
missing: the section leaves that part out. The optional last argument also writes
the Markdown to a file, which the CI workflow posts as a PR comment.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

from summary_output import write_markdown

# More rows than this and the changed-files table is collapsed.
MAX_OPEN_ROWS = 10


def fail_under(pytest_ini="pytest.ini"):
    """The gate from pytest.ini, so the ✅/❌ matches when CI fails."""
    try:
        match = re.search(r"--cov-fail-under=(\d+(?:\.\d+)?)", read(pytest_ini))
    except OSError:
        return None
    return float(match.group(1)) if match else None


def read(path):
    with open(path, encoding="utf-8") as file:
        return file.read()


def read_report(path):
    """Total and per-file coverage: {"total": percent, "files": {path: file}}.

    Each file is {"percent": ..., "missing": [...]}: untested line ranges and
    branches, e.g. ["4", "8→10"]. Percentages count branches as well as lines, as
    pytest-cov's gate does with --cov-branch. Paths are repo relative, as
    coverage.py writes them.
    """
    root = ET.parse(path).getroot()
    files = {}
    for cls in root.iter("class"):
        elements = sorted(cls.iter("line"), key=lambda line: int(line.get("number")))
        lines = [
            (int(line.get("number")), int(line.get("hits")) > 0) for line in elements
        ]
        covered = sum(1 for _, hit in lines if hit)
        branches = [branch_counts(line) for line in elements]
        files[cls.get("filename")] = {
            "percent": percent(
                covered + sum(taken for taken, _ in branches),
                len(lines) + sum(total for _, total in branches),
            ),
            "missing": sorted(
                ranges(lines) + partial_branches(elements, lines), key=first_line
            ),
        }
    total = percent(
        int(root.get("lines-covered")) + int(root.get("branches-covered", 0)),
        int(root.get("lines-valid")) + int(root.get("branches-valid", 0)),
    )
    return {"total": total, "files": files}


def branch_counts(line):
    """(taken, total) branches from a line's condition-coverage, e.g. "50% (1/2)"."""
    match = re.search(r"\((\d+)/(\d+)\)", line.get("condition-coverage") or "")
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def partial_branches(elements, lines):
    """Branches never taken from lines that ran, e.g. "8→10".

    Like coverage.py's report, a branch to a line that never ran is left out: that
    line is already listed as missing.
    """
    missed = {number for number, hit in lines if not hit}
    found = []
    for line in elements:
        if int(line.get("hits")) == 0 or not line.get("missing-branches"):
            continue
        for target in line.get("missing-branches").split(","):
            if not (target.isdigit() and int(target) in missed):
                found.append(f"{line.get('number')}→{target}")
    return found


def first_line(missing):
    return int(re.match(r"\d+", missing).group())


def percent(covered, valid):
    if not valid:
        return 100.0
    value = covered / valid * 100
    # Never round up to 100: "100.0%" with untested lines would read as covered.
    if covered < valid and round(value, 1) == 100.0:
        return 99.9
    return value


def ranges(lines):
    """Missing lines as ranges, e.g. ["41–44", "58"].

    lines is every statement line in order with whether it ran. A range runs
    across blank lines and comments, which aren't statements, until a statement
    that ran.
    """
    found, start, end = [], None, None
    for number, hit in lines:
        if hit:
            if start is not None:
                found.append(span(start, end))
            start = None
        elif start is None:
            start = end = number
        else:
            end = number
    if start is not None:
        found.append(span(start, end))
    return found


def span(start, end):
    return str(start) if start == end else f"{start}–{end}"


def change(total, baseline):
    difference = round(total - baseline, 1)
    if difference > 0:
        return f"▲ {difference:.1f}%"
    if difference < 0:
        return f"▼ {-difference:.1f}%"
    return "no change"


def to_markdown(report, gate, baseline=None, changed=None):
    total = report["total"]
    mark = "✅" if gate is None or total >= gate else "❌"
    lines = [f"## {mark} Coverage {total:.1f}%", ""]
    if baseline is None:
        lines.append("No coverage report from `main` to compare against.")
    else:
        lines.append(f"Against `main`: {change(total, baseline['total'])}")
    if gate is not None:
        lines[-1] += f" · CI fails under {gate:g}%"

    if changed is not None:
        measured = [path for path in changed if path in report["files"]]
        if not measured:
            lines += ["", "No measured files changed."]
        else:
            lines += ["", *changed_files(report["files"], measured)]
    return "\n".join(lines) + "\n"


def changed_files(files, paths):
    """The changed files with untested lines as a table; fully covered ones
    collapsed below it."""
    gaps = [path for path in paths if files[path]["missing"]]
    covered = [path for path in paths if not files[path]["missing"]]
    lines = []
    if gaps:
        table = [
            "| Changed file | Coverage | Untested lines and branches |",
            "|---|---|---|",
        ]
        for path in gaps:
            file = files[path]
            missing = ", ".join(file["missing"])
            table.append(f"| `{path}` | {file['percent']:.1f}% | {missing} |")
        if len(gaps) > MAX_OPEN_ROWS:
            summary = f"{len(gaps)} changed files with untested lines"
            table = [f"<details><summary>{summary}</summary>", "", *table, "</details>"]
        lines += table
    if covered:
        if lines:
            lines.append("")
        summary = f"✅ {len(covered)} changed file(s) fully covered"
        lines += [f"<details><summary>{summary}</summary>", ""]
        lines += [f"- `{path}`" for path in covered]
        lines.append("</details>")
    return lines


def main():
    args = sys.argv[1:] + [None] * 4
    report_path, baseline_path, changed_path, markdown_path = args[:4]
    report_path = report_path or "coverage.xml"
    if not os.path.exists(report_path):
        message = (
            f"No coverage report found at {report_path}; "
            "pytest likely failed before writing it."
        )
        print(message)
        write_markdown(f"## ⚠️ No coverage results\n\n{message}\n", markdown_path)
        return

    report = read_report(report_path)
    baseline = None
    if baseline_path and os.path.exists(baseline_path):
        baseline = read_report(baseline_path)
    changed = None
    if changed_path and os.path.exists(changed_path):
        changed = [line.strip() for line in read(changed_path).splitlines()]
        changed = [path for path in changed if path]

    print(f"Coverage {report['total']:.1f}%")
    if baseline is not None:
        print(f"Against main: {change(report['total'], baseline['total'])}")
    for path in changed or []:
        file = report["files"].get(path)
        if file and file["missing"]:
            print(f"  {path}: missing {', '.join(file['missing'])}")

    write_markdown(to_markdown(report, fail_under(), baseline, changed), markdown_path)


if __name__ == "__main__":
    main()
