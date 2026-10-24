"""ranger — agent-as-a-library.

Run the opencode harness headlessly from plain Python code, for agentic-loop
prototyping. No chat, no interactivity: you write code, ranger runs the agent.

    import ranger

    agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
    summary = agent.summarize("notes.md")
    path = agent.write("a one-page report on X")
    result = agent.do("rename all *.txt files in data/ to *.md")
    hits = agent.search("where do we parse config files?")

Discover available models and configure runs:

    print(ranger.Ranger.models(match="claude"))

    fast = ranger.Ranger(model="openrouter/google/gemini-2.5-flash")
    smart = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")

    fast.search("todo items", title="quick scan")       # per-call override
    smart.do("refactor auth", timeout=1800)            # longer leash
    builder = smart.with_config(agent="build")          # configured copy
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

__all__ = ["Ranger", "RangerError"]
__version__ = "0.1.1"

DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-4.5"

# Settings every run accepts as a per-call override.
_RUN_KEYS = ("model", "timeout", "auto", "session", "agent", "title", "thinking")


class RangerError(RuntimeError):
    """Raised when the underlying opencode run fails."""


class Ranger:
    """A runnable coding agent backed by the opencode harness.

    Each method call spawns one headless `opencode run` in the working
    directory and returns the agent's final answer as a string.

    Args:
        model: opencode model ID in "provider/model" form (see
            `Ranger.models()`).
        cwd: working directory for the agent (defaults to os.getcwd()).
        timeout: seconds to wait for each run (default 10 min).
        auto: auto-approve tool permissions so the agent can actually
            read/write files without an interactive prompt.
        session: optional opencode session ID to continue across calls.
        agent: optional opencode agent name (e.g. "build", "plan", "general").
        title: optional session title for opencode runs.
        thinking: request thinking blocks in the model's output.

    Every command method also accepts any of these as a keyword override for
    that single call, e.g. `agent.do(goal, model=..., timeout=...)`.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        cwd: str | Path | None = None,
        timeout: float = 600.0,
        auto: bool = True,
        session: str | None = None,
        agent: str | None = None,
        title: str | None = None,
        thinking: bool = False,
    ) -> None:
        self.model = model
        self.cwd = str(Path(cwd).resolve()) if cwd else None
        self.timeout = timeout
        self.auto = auto
        self.session = session
        self.agent = agent
        self.title = title
        self.thinking = thinking

    # ------------------------------------------------------------------ #
    # discovery & configuration

    @staticmethod
    def models(match: str | None = None) -> list[str]:
        """List available opencode model IDs from `opencode models`.

        Args:
            match: optional substring filter (case-insensitive).
        """
        try:
            proc = subprocess.run(
                ["opencode", "models"],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            raise RangerError(
                "opencode CLI not found on PATH — install it from https://opencode.ai"
            ) from None
        if proc.returncode != 0:
            raise RangerError(f"opencode models failed:\n{proc.stderr.strip()}")
        ids = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if match:
            needle = match.lower()
            ids = [i for i in ids if needle in i.lower()]
        return ids

    def with_config(self, **overrides) -> "Ranger":
        """Return a copy of this Ranger with run settings overridden.

        Useful for keeping configured variants side by side:

            smart = Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
            builder = smart.with_config(agent="build", auto=True)
        """
        for key in overrides:
            if key not in _RUN_KEYS and key != "cwd":
                raise TypeError(f"unknown config key: {key!r} (valid: {', '.join(_RUN_KEYS + ('cwd',))})")
        clone = Ranger.__new__(Ranger)
        clone.__dict__ = dict(self.__dict__)
        for key, value in overrides.items():
            if key == "cwd":
                value = str(Path(value).resolve())
            setattr(clone, key, value)
        return clone

    # ------------------------------------------------------------------ #
    # commands

    def ask(self, prompt: str, **ov) -> str:
        """Send an arbitrary prompt to the agent and return its answer."""
        return self._run(prompt, **ov)

    def summarize(self, file: str | Path, **ov) -> str:
        """Read a file and return a concise text summary of its contents."""
        path = Path(file)
        prompt = (
            f"Read the file at {path.resolve()}. "
            "Then reply with a concise summary of what it contains. "
            "Reply with the summary text only, no preamble."
        )
        return self._run(prompt, **ov)

    def write(self, task: str, path: str | Path | None = None, **ov) -> str:
        """Have the agent produce a written document/answer as a file.

        Returns the path of the file that was written.
        """
        if path is None:
            slug = task.strip().lower().replace(" ", "_")[:40] or "ranger_out"
            out = Path(self.cwd or Path.cwd()) / f"ranger_{slug}_{int(time.time())}.md"
        else:
            out = Path(path)
        prompt = (
            f"{task}\n\n"
            f"Write your complete answer as a file at exactly: {Path(out).resolve()}\n"
            "Do not print the answer to stdout; the file IS the answer. "
            "When done, reply with the file path only."
        )
        self._run(prompt, **ov)
        if not out.exists():
            raise RangerError(f"agent did not write the expected file: {out}")
        return str(out)

    def do(self, goal: str, **ov) -> str:
        """Execute a goal against the filesystem like a CLI agent run.

        The agent may create, edit and delete files and run shell commands
        in the working directory. Returns its final report.
        """
        prompt = (
            f"Accomplish this goal in the current directory: {goal}\n"
            "Use your file and shell tools to actually do the work. "
            "When finished, reply with a short report: what you did, "
            "which files changed, and anything that failed."
        )
        return self._run(prompt, **ov)

    def search(self, goal: str, **ov) -> str:
        """Search the working directory and report where/what matches.

        Returns a multiline report: file paths, line numbers and snippets.
        """
        prompt = (
            f"Search this codebase to answer: {goal}\n"
            "Use grep/glob tools over the working directory. "
            "Reply with a plain multiline report: each match as "
            "`file:line` followed by the matching line or a short note. "
            "No code changes."
        )
        return self._run(prompt, **ov)

    # ------------------------------------------------------------------ #
    # plumbing

    def _run(self, prompt: str, **ov) -> str:
        opts = {k: getattr(self, k) for k in _RUN_KEYS}
        opts.update({k: v for k, v in ov.items() if k in _RUN_KEYS})
        unknown = set(ov) - set(_RUN_KEYS)
        if unknown:
            raise TypeError(f"unknown run option(s): {', '.join(sorted(unknown))}")

        cmd = ["opencode", "run", "--model", opts["model"]]
        if opts["agent"]:
            cmd += ["--agent", opts["agent"]]
        if opts["auto"]:
            cmd.append("--auto")
        if opts["session"]:
            cmd += ["--session", opts["session"]]
        if opts["title"]:
            cmd += ["--title", opts["title"]]
        if opts["thinking"]:
            cmd.append("--thinking")
        cmd.append(prompt)

        try:
            proc = subprocess.run(
                cmd,
                cwd=self.cwd,
                env={**os.environ, "PWD": self.cwd} if self.cwd else None,
                capture_output=True,
                text=True,
                timeout=opts["timeout"],
            )
        except FileNotFoundError:
            raise RangerError(
                "opencode CLI not found on PATH — install it from https://opencode.ai"
            ) from None
        except subprocess.TimeoutExpired:
            raise RangerError(
                f"opencode run timed out after {opts['timeout']}s"
            ) from None

        if proc.returncode != 0:
            raise RangerError(
                f"opencode run failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
            )
        return proc.stdout.strip()
