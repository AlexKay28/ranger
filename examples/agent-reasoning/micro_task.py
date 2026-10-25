#!/usr/bin/env python
"""Temporal micro-task resolver — the distilled sprint-resolver protocol
an AI agent writes when IT must get one specific thing done and needs to
report honestly.

Three honesty rules from the field (see issue #1 in the repository history):

1. pre-flight: verify the goal is not already satisfied — until() and
   attempt() both report already_green for a vacuously green gate instead
   of faking agent work
2. compound gate: bare "tests pass" is not a goal; the gate must demand
   the feature itself AND leave the rest of the suite green — pass a
   LIST of commands and last_gate.parts will name the exact red part
3. tri-state report: pass the caller's verdict on achieved/FAILED plus
   last_gate evidence — never trust the agent's own narration alone

Default mode is the bounded multi-iteration repair loop until(max_iter=3);
pass --attempt for the single-shot sibling attempt() — ONE do(), then the
mechanical verdict, honest PASS or FAIL either way.

For new code, check agent.resolve() first — it ships this entire protocol
(pre-flight + one plan + bounded plan-guided rounds, tri-state status) as a
single library call; this script stays as the transparent, inspectable form.

    python examples/agent-reasoning/micro_task.py /path/to/project \
        "write CHANGELOG.md with today's date in the header" \
        "test -f CHANGELOG.md && grep -q 20 CHANGELOG.md && python -m pytest -q"

    python examples/agent-reasoning/micro_task.py --attempt /path/to/project \
        "add a one-line note to README.md" \
        "grep -q 'note' README.md"
"""

import sys

import ranger


def main() -> None:
    attempt_mode = "--attempt" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--attempt"]
    if len(args) < 3:
        sys.exit(__doc__)
    project, goal, gate = args[0], args[1], args[2]

    agent = ranger.Ranger(cwd=project, memory=False)

    if attempt_mode:
        # single-shot honest sibling: pre-check, ONE do(), mechanical verdict
        outcome = agent.attempt(goal, gate_cmd=gate)

        if outcome.get("already_green"):
            print("ALREADY_GREEN: goal satisfied before any agent work")
            print("no run consumed")
            sys.exit(0)

        print("PASS: goal achieved in one attempt" if outcome["passed"]
              else "FAILED: single attempt did not pass the gate")
        if outcome["report"]:
            print("agent's report (narration, unverified):")
            print(outcome["report"])

        _print_gate(outcome["last_gate"])
        sys.exit(0 if outcome["passed"] else 1)

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

    _print_gate(outcome["last_gate"])
    sys.exit(0 if outcome["achieved"] else 1)


def _print_gate(gate_ev) -> None:
    # the mechanical evidence — why the gate said what it said
    print(f"\ngate: {gate_ev['kind']} -> {'ok' if gate_ev['ok'] else 'RED'}")
    if gate_ev["output"]:
        print("gate evidence (clipped):")
        print(gate_ev["output"])


if __name__ == "__main__":
    main()
