# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The CI comment's coverage section: .github/scripts/summarize_coverage.py."""

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / ".github" / "scripts"


@pytest.fixture
def cov(monkeypatch):
    """The script as a module (it imports summary_output from its own folder)."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return importlib.import_module("summarize_coverage")


def cobertura(files):
    """A coverage.py-shaped report. files maps a path to {line number: hits}."""
    classes, covered, valid = [], 0, 0
    for path, lines in files.items():
        rows = "".join(f'<line number="{n}" hits="{h}"/>' for n, h in lines.items())
        classes.append(
            f'<class name="{path}" filename="{path}"><lines>{rows}</lines></class>'
        )
        covered += sum(1 for hits in lines.values() if hits)
        valid += len(lines)
    return (
        f'<?xml version="1.0" ?><coverage lines-valid="{valid}" '
        f'lines-covered="{covered}"><packages><package name="."><classes>'
        f'{"".join(classes)}</classes></package></packages></coverage>'
    )


def write_report(tmp_path, name, files):
    path = tmp_path / name
    path.write_text(cobertura(files), encoding="utf-8")
    return path


FULL = {"src/a.py": {1: 1, 2: 1}}
GAPS = {"src/b.py": {1: 1, 3: 0, 4: 0, 7: 0, 9: 1, 12: 0}}


# --- reading the report ----------------------------------------------------------


def test_missing_lines_become_ranges(cov):
    # 5, 6 and 8 aren't statements (blank lines, comments), so 3-7 is one gap.
    lines = [(1, True), (3, False), (4, False), (7, False), (9, True), (12, False)]
    assert cov.ranges(lines) == ["3–7", "12"]


def test_a_file_with_every_line_run_has_no_ranges(cov):
    assert not cov.ranges([(1, True), (2, True)])


def test_read_report_has_the_total_and_each_file(cov, tmp_path):
    report = cov.read_report(write_report(tmp_path, "c.xml", {**FULL, **GAPS}))
    assert report["total"] == pytest.approx(4 / 8 * 100)
    assert report["files"]["src/a.py"] == {"percent": 100.0, "missing": []}
    assert report["files"]["src/b.py"]["missing"] == ["3–7", "12"]


def test_percent_never_rounds_up_to_100(cov):
    assert cov.percent(9999, 10000) == 99.9
    assert cov.percent(10, 10) == 100.0
    assert cov.percent(0, 0) == 100.0


def test_the_gate_comes_from_pytest_ini(cov, tmp_path):
    assert cov.fail_under() == 95  # the repo's own pytest.ini
    assert cov.fail_under(str(tmp_path / "missing.ini")) is None
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\naddopts = --cov=src\n", encoding="utf-8")
    assert cov.fail_under(str(ini)) is None


# --- the Markdown ----------------------------------------------------------------


def report(total, files=None):
    return {"total": total, "files": files or {}}


@pytest.mark.parametrize(
    "total, heading", [(97.4, "## ✅ Coverage 97.4%"), (94.9, "## ❌ Coverage 94.9%")]
)
def test_the_heading_matches_the_gate(cov, total, heading):
    assert cov.to_markdown(report(total), 95).startswith(heading + "\n")


@pytest.mark.parametrize(
    "baseline, line",
    [
        (97.1, "Against `main`: ▲ 0.3%"),
        (98.5, "Against `main`: ▼ 1.1%"),
        (97.4, "Against `main`: no change"),
    ],
)
def test_the_change_against_main(cov, baseline, line):
    markdown = cov.to_markdown(report(97.4), 95, report(baseline))
    assert f"{line} · CI fails under 95%" in markdown


def test_without_a_baseline_it_says_so(cov):
    markdown = cov.to_markdown(report(97.4), None)
    assert "No coverage report from `main` to compare against." in markdown
    assert "CI fails under" not in markdown


def test_changed_files_with_gaps_are_a_table(cov):
    files = {
        "src/a.py": {"percent": 100.0, "missing": []},
        "src/b.py": {"percent": 50.0, "missing": ["3–7", "12"]},
    }
    markdown = cov.to_markdown(report(97.4, files), 95, None, ["src/b.py", "src/a.py"])
    assert "| `src/b.py` | 50.0% | 3–7, 12 |" in markdown
    assert "<summary>✅ 1 changed file(s) fully covered</summary>" in markdown
    assert "- `src/a.py`" in markdown


def test_changed_files_coverage_doesnt_measure_are_left_out(cov):
    # Tests, migrations and these scripts aren't in --cov.
    markdown = cov.to_markdown(report(100.0), 95, None, ["tests/test_x.py"])
    assert "No measured files changed." in markdown


def test_a_long_table_is_collapsed(cov):
    files = {f"src/f{i}.py": {"percent": 50.0, "missing": ["1"]} for i in range(11)}
    markdown = cov.to_markdown(report(90.0, files), 95, None, list(files))
    assert "<summary>11 changed files with untested lines</summary>" in markdown


def test_without_a_changed_files_list_there_is_no_table(cov):
    # Pushes to main: there's no PR to compare.
    files = {"src/b.py": {"percent": 50.0, "missing": ["3–7"]}}
    markdown = cov.to_markdown(report(97.4, files), 95)
    assert "Changed file" not in markdown
    assert "measured" not in markdown


# --- running it ------------------------------------------------------------------


def run(cov, monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", *map(str, args)])
    cov.main()


def test_main_writes_the_section(cov, monkeypatch, tmp_path, capsys):
    current = write_report(tmp_path, "coverage.xml", {**FULL, **GAPS})
    baseline = write_report(tmp_path, "baseline.xml", FULL)
    changed = tmp_path / "changed.txt"
    changed.write_text("src/b.py\n\ntests/test_b.py\n", encoding="utf-8")
    output = tmp_path / "coverage-summary.md"

    run(cov, monkeypatch, current, baseline, changed, output)

    markdown = output.read_text(encoding="utf-8")
    assert markdown.startswith("## ❌ Coverage 50.0%")
    assert "Against `main`: ▼ 50.0%" in markdown
    assert "| `src/b.py` | 33.3% | 3–7, 12 |" in markdown
    log = capsys.readouterr().out
    assert "Coverage 50.0%" in log
    assert "src/b.py: missing 3–7, 12" in log


def test_main_skips_a_baseline_and_changed_list_that_dont_exist(
    cov, monkeypatch, tmp_path
):
    current = write_report(tmp_path, "coverage.xml", FULL)
    output = tmp_path / "coverage-summary.md"
    run(cov, monkeypatch, current, tmp_path / "none.xml", tmp_path / "none.txt", output)
    markdown = output.read_text(encoding="utf-8")
    assert "No coverage report from `main`" in markdown
    assert "Changed file" not in markdown


def test_main_without_a_report_still_writes_a_section(cov, monkeypatch, tmp_path):
    output = tmp_path / "coverage-summary.md"
    run(cov, monkeypatch, tmp_path / "coverage.xml", "", "", output)
    assert output.read_text(encoding="utf-8").startswith("## ⚠️ No coverage results")


def test_main_also_writes_the_step_summary(cov, monkeypatch, tmp_path):
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run(cov, monkeypatch, write_report(tmp_path, "coverage.xml", FULL))
    assert summary.read_text(encoding="utf-8").startswith("## ✅ Coverage 100.0%")
