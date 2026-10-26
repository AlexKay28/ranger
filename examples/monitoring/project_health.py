"""Read-only project health snapshot: tests, findings, and run telemetry.

    python project_health.py /path/to/project "python -m pytest -q"

The test command is mechanical and free. The one agent call is read-only: it
finds the most actionable current risk. No edits are made, so this is useful
before a work session or when handing a repository to another developer.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    test_command = sys.argv[2] if len(sys.argv) > 2 else "python -m pytest -q"
    agent = ranger.Ranger(cwd=target, stats=True, timeout=120)

    print("tests green:", agent.gate(test_command))
    findings = agent.search(
        "Read this repository without editing it. Report the three most "
        "actionable current risks: failing or missing tests, TODO/FIXME debt, "
        "or unhandled error paths. Include file paths and line numbers."
    )
    print("\nrisks:\n", findings)
    print("\nconfig call path:\n", agent.trace("Ranger._run"))
    print("\nhealth script role:\n", agent.read(
        "project_health.py", "What read-only checks does this script perform?"
    ))
    print("\nexample error diagnosis:\n", agent.diagnose(
        "Traceback (most recent call last):\nValueError: invalid project config"
    ))
    print("\nagent telemetry:", agent.last)


if __name__ == "__main__":
    main()
