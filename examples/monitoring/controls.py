"""Command & control demo: check, gate, until, and the settings that steer runs.

Run from this directory against a target project (real agent runs):

    python controls.py /path/to/project

Demonstrates, in order:
  1. gate()      — mechanical booleans, no model at all
  2. check()     — agent-verified YES/NO verdicts
  3. until()     — the plan -> do -> verify loop with a mechanical gate
  4. stats=True  — telemetry: agent.last after each command
  5. mode/effort — per-run depth and agent-flavor control
  6. skills      — an operating grant injected into the run
"""

import sys
from pathlib import Path

import ranger

MODEL_ENV_IS_FINE = True  # RANGER_MODEL env or explicit model= both work


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    agent = ranger.Ranger(cwd=target, stats=True)

    # 1. gate(): pure subprocess, zero tokens
    print("gate('test -f README.md') ->", agent.gate("test -f README.md"))
    print("gate('python --version')   ->", agent.gate("python --version"))

    # 2. check(): the agent verifies for real and must answer YES/NO
    print("check('README mentions the license') ->",
          agent.check("README mentions the license"))
    print("telemetry after check:", agent.last)

    # 3. until(): loop with a mechanical gate — honesty by construction
    outcome = agent.until(
        "create a file named ranger_demo.txt containing the word done",
        gate_cmd="test -f ranger_demo.txt",
        max_iter=3,
    )
    print("until outcome:", outcome["achieved"], "in", outcome["iterations"], "iterations")

    # 4. memory + compact: keep long interactions bounded
    agent.context_compact()
    print("context after compact:", len(agent.context), "message(s)")

    # 5. mode/effort as per-call overrides (mode= picks the opencode agent)
    brief = agent.ask("in one sentence, what is a linter?", effort="low", mode="general")
    print("low-effort answer:", brief)
    print("telemetry:", agent.last)

    # 6. skills: a prose operating grant for a single run
    styled = agent.ask(
        "explain what a diff is",
        skills=["Answer in exactly three bullet points, each under 12 words."],
    )
    print("grant-constrained answer:", styled.splitlines()[:3])


if __name__ == "__main__":
    main()
