#!/usr/bin/env python
"""Temporal research-and-plan script — the pre-work reasoning an AI agent
runs BEFORE touching anything.

An agent (or you) writes this kind of throwaway script for ONE specific
task: gather facts history-free, draft a plan constrained by those facts,
then red-team the plan with a second agent before acting on it. Facts come
from memory-free commands (paradigm law 4), so the plan is grounded in the
repository, not in chat history.

    python examples/agent-reasoning/research_and_plan.py /path/to/project \
        "add retry logic to the upload client"
"""

import sys

import ranger


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    project, task = sys.argv[1], sys.argv[2]

    # One task, one context: every agent below is stateless (memory=False),
    # so nothing bleeds between the research, planning and critique phases.
    researcher = ranger.Ranger(cwd=project, memory=False)
    planner = ranger.Ranger(cwd=project, memory=False)
    critic = ranger.Ranger(cwd=project, memory=False)

    # 1. Facts: read-only, history-independent. This is the "deep research"
    #    part — evidence collected before any opinion is formed.
    print("== evidence gathering ==")
    evidence = researcher.search(f"code relevant to this task: {task}")
    if "--" in evidence:                      # search returns a file:line report
        print(evidence)

    # 2. Planning: the plan must quote the evidence, not vibes.
    print("\n== plan (constrained by evidence) ==")
    plan = planner.ask(
        f"Task: {task}\n\n"
        f"Evidence found in the repository:\n{evidence}\n\n"
        "Write a short implementation plan. Every step must reference a "
        "concrete file or command from the evidence. End with the single "
        "riskiest assumption the plan makes."
    )
    print(plan)

    # 3. Red-team the plan: the critic runs WITHOUT the planner's chat
    #    history and sees only the plan text as unverified claims.
    print("\n== independent critique ==")
    both = planner.second_opinion(critic, task)
    if both["differs"]:
        print("critic disagrees with the planner's take on the task:")
        print(both["theirs"])
    duel = critic.challenge(planner, claim=plan, rounds=1)
    print("\n== adversarial check of the plan ==")
    print(duel.get("report") or duel)

    print("\n== decision material ready: evidence, plan, critique ==")
    print("Act next — e.g. agent.do() on the plan, gated by a test command.")


if __name__ == "__main__":
    main()
