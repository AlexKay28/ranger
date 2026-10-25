#!/usr/bin/env python
"""Temporal claim verification — a deep-research pass an agent runs to
ground its own beliefs before it reports anything.

The pattern: extract verifiable claims about one topic, then verify EVERY
claim mechanically against the repository. check() is memory-free, so each
verdict is about the code, never about the conversation; an unparseable
or uncertain answer raises RangerError instead of guessing.

    python examples/agent-reasoning/verify_claims.py /path/to/project \
        "the config parser handles errors"
"""

import sys

import ranger
from ranger import RangerError


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    project, topic = sys.argv[1], sys.argv[2]

    agent = ranger.Ranger(cwd=project, memory=False)
    # ask() is the only dialogue command here; everything after runs
    # fact-pure (paradigm law 4).
    raw = agent.ask(
        f"Topic: {topic}\n\n"
        "List up to 5 claims about the CURRENT state of this repository "
        "that can be verified by reading code or running commands. One "
        "claim per line, 'CLAIM:' prefix, no commentary."
    )
    claims = [ln.split("CLAIM:", 1)[1].strip()
              for ln in raw.splitlines() if "CLAIM:" in ln][:5]
    if not claims:
        sys.exit("no verifiable claims extracted — nothing to verify")

    passed, failed = [], []
    for i, claim in enumerate(claims, 1):
        try:
            # each check is a fresh, history-independent verification
            ok = agent.check(claim)
        except RangerError as exc:
            print(f"UNCERTAIN  claim {i}: {claim}\n           {exc}")
            failed.append(claim)
            continue
        mark = "PASS    " if ok else "FAIL    "
        print(f"{mark} claim {i}: {claim}")
        (passed if ok else failed).append(claim)

    print(f"\nverified {len(passed)}/{len(claims)}")
    if failed:
        print("unverified claims — dig deeper before relying on them")
        sys.exit(1)


if __name__ == "__main__":
    main()
