"""A no-model, no-login Ranger example: deterministic local gates.

    python mechanical_gates.py

`gate()` is part of Ranger but does not invoke a coding agent. It is handy for
wrapping an existing command in ordinary Python control flow, and makes a
safe first run before trying the live examples.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import ranger


def main() -> None:
    with TemporaryDirectory(prefix="ranger-gate-") as directory:
        project = Path(directory)
        (project / "answer.txt").write_text("42\n")
        agent = ranger.Ranger(cwd=project)

        print("file exists:", agent.gate("test -f answer.txt"))
        print("content is 42:", agent.gate("grep -qx 42 answer.txt"))
        print("missing file:", agent.gate("test -f does-not-exist.txt"))


if __name__ == "__main__":
    main()
