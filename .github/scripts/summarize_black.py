"""Summarize `black --check --diff` in the job log and GitHub step summary.

    black --check --diff . > black.diff 2> black.log
    python summarize_black.py black.log black.diff [formatting-summary.md]

The optional third argument also writes the Markdown to a file, which the CI
workflow posts as a PR comment.
"""

import os
import sys

from summary_output import write_markdown

# GitHub comments stop at 65,536 characters, and the comment holds other sections.
MAX_DIFF = 20_000
FIX = "Run `black .` and commit the result."


def read(path):
    with open(path, encoding="utf-8") as file:
        return file.read()


def relative(text):
    """Black prints absolute paths; the comment reads better with repo paths."""
    return text.replace(os.getcwd() + os.sep, "")


def to_markdown(files, errors, diff):
    if errors:
        lines = [f"## ❌ Black couldn't read {len(errors)} file(s)", ""]
        lines += [f"- {error}" for error in errors]
        return "\n".join(lines) + "\n"
    if not files:
        return "## ✅ Formatted with Black\n"
    lines = [f"## ❌ {len(files)} file(s) need formatting", "", FIX, ""]
    lines += [f"- `{path}`" for path in files]
    if diff:
        shown = diff if len(diff) <= MAX_DIFF else diff[:MAX_DIFF] + "\n… (cut short)\n"
        lines += [
            "",
            "<details><summary>What Black would change</summary>",
            "",
            "```diff",
            shown.rstrip("\n"),
            "```",
            "</details>",
        ]
    return "\n".join(lines) + "\n"


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else "black.log"
    diff_path = sys.argv[2] if len(sys.argv) > 2 else "black.diff"
    markdown_path = sys.argv[3] if len(sys.argv) > 3 else None
    if not os.path.exists(log_path):
        message = f"No Black output found at {log_path}; Black likely didn't run."
        print(message)
        write_markdown(f"## ⚠️ No formatting results\n\n{message}\n", markdown_path)
        return

    log = read(log_path).splitlines()
    files = [
        relative(line.removeprefix("would reformat "))
        for line in log
        if line.startswith("would reformat ")
    ]
    errors = [
        relative(line.removeprefix("error: "))
        for line in log
        if line.startswith("error:")
    ]
    diff = relative(read(diff_path)) if os.path.exists(diff_path) else ""

    if errors:
        print(f"Black couldn't read {len(errors)} file(s)")
    elif files:
        print(f"{len(files)} file(s) need formatting. {FIX}")
    else:
        print("All files are formatted with Black")
    for path in files:
        print(f"  {path}")

    write_markdown(to_markdown(files, errors, diff), markdown_path)


if __name__ == "__main__":
    main()
