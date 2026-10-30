"""Repair a failing test command with a hard, cheap acceptance gate.

    python fix_failing_tests.py /path/to/project "python -m pytest -q"

The shell command is the source of truth, not the agent's report. The
example first avoids an agent call if the suite is already green, then gives
the agent at most two repair attempts. It is useful for a small known failure
after you have checked out the relevant branch.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: fix_failing_tests.py /path/to/project 'test command'")
    target = Path(sys.argv[1]).resolve()
    command = sys.argv[2]
    agent = ranger.Ranger(cwd=target, timeout=180)

    print(agent.test())  # read-only diagnosis before choosing a repair loop
    print(agent.lint())  # read-only lint and format diagnosis

    if agent.gate(command):
        print("already green; no agent run needed")
        return

    result = agent.until(
        "Make this test command pass. First reproduce its failure, make the "
        "smallest correct fix, and rerun only relevant tests before reporting: "
        + command,
        gate_cmd=command,
        max_iter=2,
        rollback_on_fail=True,  # recoverable: a red budget restores the tree
    )
    print("passed:", result["achieved"], "attempts:", result["iterations"])
    if result.get("rolled_back"):
        print("rolled back to", result["rollback"]["tag"],
              "— restored", len(result["rollback"]["restored"]), "path(s)")
    print("last report:\n", result["report"])
    if not result["achieved"]:
        raise SystemExit("test command is still red; inspect the report and retry deliberately")


if __name__ == "__main__":
    main()
