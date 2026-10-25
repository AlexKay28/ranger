#!/usr/bin/env python
"""Temporal micro-task resolver — the distilled sprint-resolver protocol
an AI agent writes when IT must get one specific thing done and needs to
report honestly.

Three honesty rules from the field (see issue #1 in the repository history):

1. pre-flight: verify the goal is not already satisfied — until() reports
   already_green for a vacuously green gate instead of faking agent work
2. compound gate: bare "tests pass" is not a goal; the gate must demand
   the feature itself AND leave the rest of the suite green
3. tri-state report: pass the caller's verdict on achieved/FAILED plus
   last_gate evidence — never trust the agent's own narration alone

    python examples/agent-reasoning/micro_task.py /path/to/project \
        "write CHANGELOG.md with today's date in the header" \
        "test -f CHANGELOG.md && grep -q 20 CHANGELOG.md && python -m pytest -q"
"""

import sys

import ranger


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    project, goal, gate = sys.argv[1], sys.argv[2], sys.argv[3]

    agent = ranger.Ranger(cwd=project, memory=False)

    outcome = agent.until(goal, max_iter=3, gate_cmd=gate)

    if outcome.get("already_green"):
        # the gate passed before any work — say so, claim no credit
        print("ALREADY_GREEN: goal satisfied before any agent work")
        print("no run consumed; steps:", outcome["steps"])
        sys.exit(0)

    if outcome["achieved"]:
        print("PASS: goal achieved in", outcome["iterations"], "iterations")
        print("steps taken:")
        for s in outcome["steps"]:
            print(f"  - {s}")
    else:
        print("FAILED: budget exhausted after", outcome["iterations"],
              "iterations")
        print("agent's last report (narration, unverified):")
        print(outcome["report"])

    # the mechanical evidence — why the gate said what it said
    gate_ev = outcome["last_gate"]
    print(f"\ngate: {gate_ev['kind']} -> {'ok' if gate_ev['ok'] else 'RED'}")
    if gate_ev["output"]:
        print("gate evidence (clipped):")
        print(gate_ev["output"])
    sys.exit(0 if outcome["achieved"] else 1)


if __name__ == "__main__":
    main()
