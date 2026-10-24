"""Draft release notes from the repository's actual git history.

    python draft_release_notes.py /path/to/project [from-ref]

For example, pass the previous release tag as `from-ref`. The agent reads the
history and writes only the requested Markdown draft; the exact path is
verified by Ranger.write() before it returns.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    from_ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD~10"
    agent = ranger.Ranger(cwd=target, timeout=120)

    path = agent.write(
        "Read the git log and diffs from " + from_ref + " through HEAD. "
        "Write concise Markdown release notes with Added, Changed, Fixed, and "
        "Breaking changes sections. Include only changes you can verify from "
        "the repository; omit empty sections. Do not edit any other file.",
        path="RELEASE_NOTES_DRAFT.md",
    )
    print("draft written:", path)
    print(agent.summarize(path))


if __name__ == "__main__":
    main()
