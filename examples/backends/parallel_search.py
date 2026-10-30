"""Parallel independent searches — the async twins without losing the sync core.

    python parallel_search.py [query]      # default: "where is usage documented"

Sync ranger is deliberately blocking; but independent calls with no data
dependency may overlap safely. `par_map` is a helper, not a scheduler —
plain asyncio.gather under a semaphore, one result slot per input, honest
per-item exceptions (an exception instance sits in that slot; siblings
are untouched). Requires an authenticated harness CLI.
"""

import asyncio
import sys

import ranger


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "where is usage documented"
    agent = ranger.Ranger(cwd=".", timeout=180)

    calls = [
        # read-only facts fan out: three independent lookups, max two at
        # a time, same frozen prompts as the sync search()/check()
        {"method": "search", "args": [query]},
        {"method": "search", "args": ["nearest competitor libraries"]},
        {"method": "check", "args": ["the readme links the API reference"]},
    ]
    results = asyncio.run(agent.par_map(calls, max_concurrency=2))

    names = ("search", "search", "check")
    for name, slot in zip(names, results):
        if isinstance(slot, BaseException):
            print(f"[{name}] FAILED: {slot}")
        else:
            print(f"[{name}] {str(slot).strip().splitlines()[:12]}")

    # the sync core is untouched and stays the primary API
    followup = agent.ask("in one sentence, what is the most interesting finding?")
    print("[ask]", followup.strip())


if __name__ == "__main__":
    main()
