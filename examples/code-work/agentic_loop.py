"""A runnable agentic loop: the README's growth loop as an application.

Run from this directory:

    python agentic_loop.py "clean up this repo" [passes]

Strategy (one thing per pass, fixed order):
    search -> find rough edges
    ask    -> pick exactly ONE and produce a one-line work order
    do     -> execute that work order against the filesystem
    repeat

Costs a real agent run per step, so passes default to 2.
"""

import sys

import ranger

DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-4.5"
DEFAULT_PASSES = 2


def pick_work_order(agent: ranger.Ranger, goal: str, findings: str) -> str:
    prompt = (
        f"Overall goal: {goal}\n"
        f"Current findings:\n{findings}\n\n"
        "Pick exactly ONE small, well-defined piece of work from these "
        "findings that moves the goal forward. Reply with a single-line, "
        "self-contained work order an agent could execute with file tools, "
        "and nothing else."
    )
    return agent.ask(prompt).strip()


def run_loop(goal: str, passes: int, **config) -> None:
    agent = ranger.Ranger(model=DEFAULT_MODEL, **config)
    for i in range(passes):
        print(f"[pass {i + 1}/{passes}] searching...")
        findings = agent.search(f"concrete rough edges relevant to: {goal}")

        print(f"[pass {i + 1}/{passes}] planning...")
        work_order = pick_work_order(agent, goal, findings)
        print(f"[pass {i + 1}/{passes}] work order: {work_order}")

        print(f"[pass {i + 1}/{passes}] doing...")
        report = agent.do(work_order)
        print(f"[pass {i + 1}/{passes}] report:\n{report}\n")


def main() -> None:
    goal = sys.argv[1] if len(sys.argv) > 1 else "tidy this repository"
    passes = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PASSES
    run_loop(goal, passes, cwd=".")


if __name__ == "__main__":
    main()
