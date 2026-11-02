"""Where the summary scripts write their Markdown."""
import os


def write_markdown(markdown, markdown_path=None):
    """Append to the step summary (when running in Actions) and write markdown_path.

    markdown_path is the file the CI workflow posts as a PR comment.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(markdown)
    if markdown_path:
        with open(markdown_path, "w", encoding="utf-8") as output:
            output.write(markdown)
