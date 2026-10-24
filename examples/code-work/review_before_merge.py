"""Ask a fresh critic to review local changes before opening a PR.

    python review_before_merge.py /path/to/project

It costs two bounded calls: one agent makes an evidence-bearing claims report;
the critic independently reads the diff and repository, then returns a strict
APPROVE/REJECT/REQUEST_CHANGES verdict. No agent is asked to edit files.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    author = ranger.Ranger(cwd=target, timeout=120)
    critic = ranger.Ranger(cwd=target, timeout=120)

    claims = author.ask(
        "Read the uncommitted git diff and relevant tests. Report only factual "
        "claims: files changed, behavioral intent, tests run, and known risks. "
        "Do not edit files."
    )
    verdict = critic.review(
        "the uncommitted git diff: verify correctness, regression risk, and "
        "whether the claimed tests actually cover the change",
        author=claims,
    )
    print("verdict:", verdict["verdict"])
    print("findings:\n", verdict["findings"])
    print("changes:\n", verdict["changes"])
    if not verdict["passed"]:
        raise SystemExit("do not merge yet: address the requested changes")


if __name__ == "__main__":
    main()
