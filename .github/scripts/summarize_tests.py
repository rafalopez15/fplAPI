"""Summarize a pytest JUnit XML report in the job log and GitHub step summary."""
import os
import sys
import xml.etree.ElementTree as ET


def read_results(report_path):
    root = ET.parse(report_path).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    return {
        "total": total,
        "passed": total - failed - skipped,
        "failed": failed,
        "skipped": skipped,
        "failures": list(find_failures(suite)),
    }


def find_failures(suite):
    for case in suite.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is not None:
            message = (problem.get("message") or "").splitlines()[0][:200]
            yield f"{case.get('classname')}::{case.get('name')}", message


def to_markdown(results, status, percent):
    lines = [
        f"## {status}",
        "",
        "| Total | Passed | Failed | Skipped | Pass rate |",
        "|---|---|---|---|---|",
        f"| {results['total']} | {results['passed']} | {results['failed']} "
        f"| {results['skipped']} | {percent:.1f}% |",
    ]
    if results["failures"]:
        lines += ["", "### Failures", "", "| Test | Error |", "|---|---|"]
        for name, message in results["failures"]:
            escaped = message.replace("|", r"\|")
            lines.append(f"| `{name}` | {escaped} |")
    return "\n".join(lines) + "\n"


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "test-results.xml"
    if not os.path.exists(report_path):
        print(f"No test report found at {report_path}; pytest likely failed before running tests.")
        return

    results = read_results(report_path)
    percent = results["passed"] / results["total"] * 100 if results["total"] else 0.0
    if results["failed"]:
        status = f"❌ {results['failed']} test(s) failed"
    else:
        status = "✅ All tests passed"

    print(f"{status}: {results['passed']}/{results['total']} passed ({percent:.1f}%), "
          f"{results['skipped']} skipped")
    for name, message in results["failures"]:
        print(f"  FAILED {name}: {message}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(to_markdown(results, status, percent))


if __name__ == "__main__":
    main()
