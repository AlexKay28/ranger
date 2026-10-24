"""Quickstart: the five core ranger commands, one after another.

Run from this directory:

    python quickstart.py /path/to/your/project

Each call spawns one headless `opencode run` in the given directory.
Uses only the shipped API: ask, summarize, write, do, search.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5", cwd=target)

    # 1. search — read-only inventory
    print("--- search ---")
    print(agent.search("what does this project contain?"))

    # 2. summarize — digest one file
    some_file = next(target.rglob("*.md"), None) or next(target.rglob("*.py"), None)
    if some_file:
        print("--- summarize ---")
        print(agent.summarize(some_file))

    # 3. do — mutate the filesystem like a CLI agent
    print("--- do ---")
    print(agent.do("create a file named RANGER_NOTES.md listing the files in this directory"))

    # 4. write — answer delivered as a file, path returned and verified
    print("--- write ---")
    print("wrote:", agent.write("a haiku about code, as markdown"))

    # 5. ask — raw escape hatch
    print("--- ask ---")
    print(agent.ask("in one sentence, what is the capital-style purpose of README files?"))


if __name__ == "__main__":
    main()
