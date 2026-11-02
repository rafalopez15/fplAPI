"""Summarize a pylint json2 report in the job log and GitHub step summary.

    python summarize_pylint.py pylint-report.json [pylint-summary.md]

The optional second argument also writes the Markdown to a file, which the CI
workflow posts as a PR comment.
"""
import json
import os
import sys

from summary_output import write_markdown

CATEGORIES = ["fatal", "error", "warning", "refactor", "convention", "info"]


def to_markdown(status, score, counts, messages):
    lines = [
        f"## {status}",
        "",
        "| Score | " + " | ".join(c.capitalize() for c in CATEGORIES) + " |",
        "|---|" + "---|" * len(CATEGORIES),
        f"| {score:.2f}/10 | " + " | ".join(str(counts.get(c, 0)) for c in CATEGORIES) + " |",
    ]
    if messages:
        lines += ["", "### Issues", "", "| Location | Code | Message |", "|---|---|---|"]
        for msg in messages:
            escaped = msg["message"].replace("|", r"\|")
            lines.append(
                f"| `{msg['path']}:{msg['line']}` | `{msg['messageId']}` {msg['symbol']} "
                f"| {escaped} |"
            )
    return "\n".join(lines) + "\n"


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "pylint-report.json"
    markdown_path = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.exists(report_path):
        message = f"No pylint report found at {report_path}; pylint likely crashed."
        print(message)
        write_markdown(f"## ⚠️ No pylint results\n\n{message}\n", markdown_path)
        return

    with open(report_path, encoding="utf-8") as report:
        data = json.load(report)
    stats = data["statistics"]
    score = stats.get("score") or 0.0
    counts = stats["messageTypeCount"]
    messages = data["messages"]

    status = f"❌ {len(messages)} pylint issue(s)" if messages else "✅ No pylint issues"
    breakdown = ", ".join(f"{counts.get(c, 0)} {c}" for c in CATEGORIES if counts.get(c))
    print(f"{status}: score {score:.2f}/10" + (f" ({breakdown})" if breakdown else ""))
    for msg in messages:
        print(f"  {msg['path']}:{msg['line']} {msg['messageId']} {msg['symbol']}: {msg['message']}")

    write_markdown(to_markdown(status, score, counts, messages), markdown_path)


if __name__ == "__main__":
    main()
