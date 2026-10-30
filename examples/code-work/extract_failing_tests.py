"""extract(): structured rows out of a failing test suite — no prose parsing.

    python extract_failing_tests.py [pytest-target]   # default: tests/

The agent verifies facts read-only and must reply with exactly one JSON
array of objects carrying the named keys; ranger parses it mechanically
or raises. Turns a wall of failure text into loop-ready data:

    for row in rows:
        print(row["file"], row["test_id"], "->", row["reason"])
"""

import sys

import ranger


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "tests/"
    agent = ranger.Ranger(cwd=".", timeout=180)

    rows = agent.extract(
        f"failing tests under {target} (all passing is a valid answer)",
        keys=["file", "test_id", "reason"],
    )
    if not rows:
        print("[extract] no failing tests found")
        return
    for row in rows:
        print(f"[extract] {row['file']} :: {row['test_id']} -> {row['reason']}")

    # the rows are ordinary dicts: gate on them, group them, feed until()
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["file"], []).append(row["test_id"])
    print("[grouped]", grouped)


if __name__ == "__main__":
    main()
