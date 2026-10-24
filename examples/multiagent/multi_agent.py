"""Multi-agent interactions: the expected patterns, ready to use.

    python multi_agent.py /path/to/target      # real agent runs, ~10 calls

Showcases the v0.6 interaction surface between two (or three) agents —
a builder and a critic, plus one debate with a judge:

  1. second_opinion — same question, two agents; disagreement is signal
  2. review         — critic judges verified facts, verdict is grammar
  3. refine_with    — do -> review -> address changes -> repeat
  4. challenge     — one agent adversarially attacks another's claim
  5. debate         — positions exchanged; an optional judge digests

All verdicts ride frozen reply contracts parsed mechanically — an
unparseable reply raises, it never guesses.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    builder = ranger.Ranger(cwd=str(target))
    critic = ranger.Ranger(cwd=str(target))

    # 1. two answers to one question — plain comparison, no winner
    both = builder.second_opinion(critic, "in one sentence: what is in this directory?")
    print("[second_opinion] differs:", both["differs"])
    print("  builder:", both["mine"].strip()[:90])
    print("  critic :", both["theirs"].strip()[:90])

    # 2. review: the critic verifies the builder's latest claim itself
    verdict = critic.review("the state of this directory", author=builder)
    print("[review]", verdict["verdict"], "· passed:", verdict["passed"])
    print("  findings:", verdict["findings"][:110])
    if not verdict["passed"] and verdict["changes"]:
        print("  changes wanted:", verdict["changes"][:110])

    # 3. the two-agent until: do, get reviewed, address changes, repeat
    outcome = builder.refine_with(
        critic,
        "create a file named AGENTS_NOTE.txt with one line: reviewed by rangers",
        max_iter=3,
    )
    print("[refine_with] approved:", outcome["approved"],
          "in", outcome["iterations"], "iteration(s)")

    # 4. adversarial: the critic attacks the builder's latest claim
    duel = critic.challenge(builder, rounds=1)
    print("[challenge] claim survived:", duel["survived"])
    for r in duel["rounds"]:
        print("  attack :", r["attack"][:100])
        print("  ruling :", r["ruling"])

    # 5. symmetric debate over a topic, digested by a third agent
    skeptic = ranger.Ranger(cwd=str(target))
    round_table = ranger.debate(
        builder, critic,
        "should tiny libraries pin their dependency versions?",
        rounds=1,
        judge=skeptic,
    )
    print("[debate] rounds:", len(round_table["transcript"]))
    if round_table["digest"]:
        print("  judge digest:", round_table["digest"][:150])


if __name__ == "__main__":
    main()
