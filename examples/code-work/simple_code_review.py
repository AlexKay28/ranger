"""Review one file with one agent call and a structured verdict.

    python simple_code_review.py /path/to/project ranger/__init__.py

The reviewer reads the real file and returns APPROVE, REJECT, or
REQUEST_CHANGES with findings and concrete changes. This script makes no
edits. Its exit code is 0 only for APPROVE, so it also works as a small
pre-commit or CI-adjacent manual check.
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: simple_code_review.py /path/to/project path/to/file.py")
    target = Path(sys.argv[1]).resolve()
    path = Path(sys.argv[2])
    full_path = (target / path).resolve()
    try:
        subject = full_path.relative_to(target)
    except ValueError:
        raise SystemExit("file must be inside the target project") from None
    if not full_path.is_file():
        raise SystemExit(f"not a file: {subject}")

    critic = ranger.Ranger(cwd=target, timeout=120)
    result = critic.review(
        f"{subject}: check correctness, edge cases, regressions, and tests. "
        "Read the file and relevant local code; do not edit anything."
    )
    print("verdict:", result["verdict"])
    print("findings:\n", result["findings"])
    print("changes:\n", result["changes"])
    if not result["passed"]:
        raise SystemExit("review needs changes")


if __name__ == "__main__":
    main()
