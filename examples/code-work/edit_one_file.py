"""Make one bounded edit to an existing file.

    python edit_one_file.py /path/to/project src/parser.py "Handle empty input"
"""

import sys
from pathlib import Path

import ranger


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: edit_one_file.py PROJECT FILE INSTRUCTION")
    project, file, instruction = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    agent = ranger.Ranger(cwd=project, timeout=180)
    print(agent.edit(file, instruction))


if __name__ == "__main__":
    main()
