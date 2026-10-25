#!/usr/bin/env python
"""Temporal claim verification — a deep-research pass an agent runs to
ground its own beliefs before it reports anything.

The pattern is now one shipped command: verify_claims() extracts
verifiable claims about one topic, then verifies EVERY claim mechanically
against the repository. Each check() is memory-free, so each verdict is
about the code, never about the conversation; an unparseable or uncertain
answer becomes UNCERTAIN instead of a guess.

    python examples/agent-reasoning/verify_claims.py /path/to/project \
        "the config parser handles errors"
"""

import sys

import ranger


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    project, topic = sys.argv[1], sys.argv[2]

    agent = ranger.Ranger(cwd=project, memory=False)
    results = agent.verify_claims(topic)

    passed = 0
    for i, r in enumerate(results, 1):
        mark = {"PASS": "PASS    ", "FAIL": "FAIL    "}.get(r["verdict"],
                                                            "UNCERTAIN")
        print(f"{mark} claim {i}: {r['claim']}")
        if r["verdict"] == "PASS":
            passed += 1

    bad = [r for r in results if r["verdict"] in ("FAIL", "UNCERTAIN")]
    print(f"\nverified {passed}/{len(results)}")
    if bad:
        print("unverified claims — dig deeper before relying on them")
        sys.exit(1)


if __name__ == "__main__":
    main()
