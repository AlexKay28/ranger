"""The full repair tier: diagnose → fix → transform → commit, rail-gated.

    python ship_fix.py /path/to/project "python -m pytest -q -k tokens"

Shows the shipped primitives composing: `fix()` with a mechanical gate,
`transform()` batch edits rail-checked per file, and `commit()` staging
only the allowed paths. Requires an authenticated harness CLI.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: ship_fix.py /path/to/project 'failing test command'")
    target = Path(sys.argv[1]).resolve()
    command = sys.argv[2]

    agent = ranger.Ranger(
        cwd=target, timeout=600,
        allow=["src/**", "tests/**"],           # only these may change
        deny=["**/.env", "**/secrets*"],        # never these; deny wins
        snapshots=True,                         # recoverable rounds
    )

    agent.costs_reset()
    result = agent.fix(f"this command fails: {command}",
                       gate_cmd=command, max_iter=2)
    print("fix:", result["status"], "·", result["iterations"], "round(s)")
    if result["status"] != "FIXED":
        print("diagnosis tail:", result["diagnosis"][-400:])
        return

    # batch touch-up with per-file honesty: an error entry never stops
    # the batch, and rails refuse anything outside allow/deny first
    for row in agent.transform("src/**/*.py", "add a one-line module docstring "
                               "if missing", max_files=20):
        if "error" in row:
            print("skip:", row["file"], "->", row["error"][:80])
        else:
            print("done:", row["file"])

    # stage + commit only the allowed paths; never a push anywhere
    print("commit:", agent.commit(
        "fix: " + command[:60],
        allow=["src/**", "tests/**"]))
    print("this run cost:", agent.costs)


if __name__ == "__main__":
    main()
