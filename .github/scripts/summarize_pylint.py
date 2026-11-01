"""Summarize a pylint json2 report in the job log and GitHub step summary."""
import json
import os
import sys

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
    if not os.path.exists(report_path):
        print(f"No pylint report found at {report_path}; pylint likely crashed.")
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

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(to_markdown(status, score, counts, messages))


if __name__ == "__main__":
    main()
