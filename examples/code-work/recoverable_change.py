"""Recoverable change: explicit snapshot tag -> do() -> manual rollback.

    python recoverable_change.py /path/to/project

`fix_failing_tests.py` chains rollback into `until(rollback_on_fail=...)`;
this recipe shows the MANUAL pair for exploratory work where you decide
after reading the diff:

  1. snapshot(tag=...) — commit the working tree to a named restore
     point (git plumbing underneath; nothing about your branch changes)
  2. do(goal) — a bounded mutation inside an allow-list
  3. your verdict, not the agent's report: if the gate stays red or the
     change is wrong, rollback(tag) restores every touched path and
     lists exactly what it restored
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    gate_cmd = "python -m pytest -q"
    agent = ranger.Ranger(
        cwd=target,
        allow=["docs/*"],          # rail the mutation to documentation only
        snapshots=True,
        timeout=180,
    )

    tag = agent.snapshot(tag="before-doc-pass")
    print("snapshot:", tag["tag"], tag["sha"][:8])

    report = agent.do(
        "Fix only the spelling and broken-markdown errors in docs/; "
        "make no factual rewrites."
    )
    print("agent report head:", report.splitlines()[0] if report else "(empty)")

    gates = agent.gate(gate_cmd)
    if gates:
        print("gate green — change keeps")
        return

    # the caller owns the verdict: red gate -> restore, no negotiation
    restored = agent.rollback("before-doc-pass")
    print("rolled back to", restored["tag"], "— restored",
          len(restored["restored"]), "path(s)")


if __name__ == "__main__":
    main()
