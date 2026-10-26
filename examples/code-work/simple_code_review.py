"""Critique one file with one read-only agent call.

    python simple_code_review.py /path/to/project ranger/__init__.py

The reviewer reads the real file and returns concrete findings about bugs,
risks, security issues, and missing tests. This script makes no edits.
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
    print(critic.critique(str(subject)))


if __name__ == "__main__":
    main()
