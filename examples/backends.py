"""Backends demo: the same API over different harnesses.

    python backends.py [backend]      # default: opencode

Works with any registered harness. `codex` requires the Codex CLI
(https://github.com/openai/codex) and a logged-in session.

Also shows `ranger.register_backend` — the extension point that made
adding codex a translation exercise, not surgery.
"""

import sys

import ranger


def main() -> None:
    backend = sys.argv[1] if len(sys.argv) > 1 else "opencode"
    agent = ranger.Ranger(backend=backend, stats=True)

    # identical contract, different data plane underneath
    print("[ask]", agent.ask("reply with the single word ok").strip())
    print("[stats]", agent.last)

    # prove the paradigm: python owns the loop, whatever the harness
    print("[gate]", agent.gate("test -d ."))

    # registration is public too — one class + one call = a new harness
    print("[registered]", ranger.backends())


if __name__ == "__main__":
    main()
