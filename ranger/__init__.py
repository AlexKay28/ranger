"""ranger — agent-as-a-library.

Run the opencode harness headlessly from plain Python code, for agentic-loop
prototyping. No chat, no interactivity: you write code, ranger runs the agent.

Live progress: every command prints a colored step line with a spinner and
elapsed clock (▶ … ⠹ 00:12 … ✓) straight to stderr, so returned strings stay
clean. Disable with Ranger(..., pretty=False) or per call (..., pretty=False).

    import ranger

    agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
    summary = agent.summarize("notes.md")
    path = agent.write("a one-page report on X")
    result = agent.do("rename all *.txt files in data/ to *.md")
    hits = agent.search("where do we parse config files?")
    ok = agent.check("all tests pass")     # bool: YES/NO verdict, never guessed
    green = agent.gate("python -m pytest -q")  # bool: pure exit-code gate

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
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

__all__ = ["Ranger", "RangerError"]
__version__ = "0.3.0"

DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-4.5"

# Settings every run accepts as a per-call override.
_RUN_KEYS = (
    "model", "timeout", "auto", "session", "agent", "title", "thinking",
    "pretty", "memory",
)

# How many characters of recorded context a run may recall, max.
_MEMORY_BUDGET = 20000


class RangerError(RuntimeError):
    """Raised when the underlying opencode run fails."""


# ---------------------------------------------------------------------- #
# live terminal UI (stderr only; auto-off outside a TTY; NO_COLOR honored)

_NO_COLOR = bool(os.environ.get("NO_COLOR"))
_RESET = "\033[0m"
_COLORS = {"cyan": "\033[36m", "green": "\033[32m", "red": "\033[31m",
           "dim": "\033[2m", "bold": "\033[1m"}


def _c(text: str, color: str) -> str:
    if _NO_COLOR:
        return text
    return f"{_COLORS.get(color, '')}{text}{_RESET if color in _COLORS else ''}"


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


class _Spinner:
    """One morphing terminal line per command, opencode-wizard style.

    While running:  `⠹ search · TODO items in this… · 00:03`
    Stopped: the line is cleared so _run can print the final ✓/✗ line.
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str, preview: str) -> None:
        self._label = _c(label, "cyan")
        self._preview = _clip(preview, 40)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        start = time.time()
        i = 0
        while not self._stop.is_set():
            mm, ss = divmod(int(time.time() - start), 60)
            sys.stderr.write(
                f"\r  {_c(self.FRAMES[i % len(self.FRAMES)], 'cyan')}"
                f" {self._label} {_c('·', 'dim')} {self._preview}"
                f" {_c('·', 'dim')} {_c(f'{mm:02d}:{ss:02d}', 'dim')}   "
            )
            sys.stderr.flush()
            self._stop.wait(0.1)
            i += 1
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)


class Ranger:
    """A runnable coding agent backed by the opencode harness.

    Each method call spawns one headless `opencode run` in the working
    directory and returns the agent's final answer as a string.

    Args:
        model: opencode model ID in "provider/model" form; defaults to
            the RANGER_MODEL environment variable, then the package
            default (see `Ranger.models()`).
        cwd: working directory for the agent (defaults to os.getcwd()).
        timeout: seconds to wait for each run (default 10 min).
        auto: auto-approve tool permissions so the agent can actually
            read/write files without an interactive prompt.
        session: optional opencode session ID to continue across calls.
        agent: optional opencode agent name (e.g. "build", "plan", "general").
        title: optional session title for opencode runs.
        thinking: request thinking blocks in the model's output.
        pretty: live terminal progress (spinner, colors, clocks) on stderr
            while each command runs; off automatically when stderr is not a
            TTY or NO_COLOR is set.
        memory: record every command exchange to `self.context` (OpenAI
            message format) and recall recent context in later runs within
            a character budget. Manage with `context_summarize()` /
            `context_compact()` / `context_clear()`.

    Every command method also accepts any of these as a keyword override for
    that single call, e.g. `agent.do(goal, model=..., timeout=...)`.
    """

    def __init__(
        self,
        model: str | None = None,
        cwd: str | Path | None = None,
        timeout: float = 600.0,
        auto: bool = True,
        session: str | None = None,
        agent: str | None = None,
        title: str | None = None,
        thinking: bool = False,
        pretty: bool = True,
        memory: bool = True,
        memory_budget: int = _MEMORY_BUDGET,
    ) -> None:
        self.model = model or os.environ.get("RANGER_MODEL") or DEFAULT_MODEL
        self.cwd = str(Path(cwd).resolve()) if cwd else None
        self.timeout = timeout
        self.auto = auto
        self.session = session
        self.agent = agent
        self.title = title
        self.thinking = thinking
        self.pretty = pretty
        self.memory = memory
        self.memory_budget = memory_budget
        #: OpenAI-format conversation state: {"role", "content"} dicts.
        self.context: list[dict] = []

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
    # context management

    def context_summarize(self) -> str:
        """Ask the agent for a text digest of the recorded context.

        History is left untouched. Returns "" when nothing is recorded.
        """
        if not self.context:
            return ""
        transcript = "\n\n".join(f"[{m['role']}] {m['content']}" for m in self.context)
        digest = self._run(
            "Summarize the following session history into a compact digest: "
            "commands issued, what was learned/decided, files touched, facts "
            "worth keeping. Plain text, bullet points.\n\n"
            + transcript,
            label="summarize",
        )
        return digest

    def context_compact(self) -> str:
        """Collapse the whole history into one system summary message.

        The digest replaces self.context, so future runs recall a bounded
        summary instead of the full transcript. Returns the digest.
        """
        digest = self.context_summarize()
        self.context = [{"role": "system", "content": digest}] if digest else []
        return digest

    def context_clear(self) -> list[dict]:
        """Wipe the recorded context; returns what was cleared."""
        old, self.context = self.context, []
        return old

    # ------------------------------------------------------------------ #
    # commands

    def ask(self, prompt: str, **ov) -> str:
        """Send an arbitrary prompt to the agent and return its answer."""
        return self._run(prompt, label="ask", **ov)

    def summarize(self, file: str | Path, **ov) -> str:
        """Read a file and return a concise text summary of its contents.

        Relative paths resolve against the agent's cwd, not the Python
        process's.
        """
        path = Path(file)
        if not path.is_absolute():
            path = Path(self.cwd or Path.cwd()) / path
        prompt = (
            f"Read the file at {path.resolve()}. "
            "Then reply with a concise summary of what it contains. "
            "Reply with the summary text only, no preamble."
        )
        return self._run(prompt, label="summarize", **ov)

    def write(self, task: str, path: str | Path | None = None, **ov) -> str:
        """Have the agent produce a written document/answer as a file.

        Returns the path of the file that was written.
        """
        if path is None:
            slug = task.strip().lower().replace(" ", "_")[:40] or "ranger_out"
            out = Path(self.cwd or Path.cwd()) / f"ranger_{slug}_{int(time.time())}.md"
        else:
            out = Path(path)
            if not out.is_absolute():
                out = Path(self.cwd or Path.cwd()) / out
        prompt = (
            f"{task}\n\n"
            f"Write your complete answer as a file at exactly: {Path(out).resolve()}\n"
            "Do not print the answer to stdout; the file IS the answer. "
            "When done, reply with the file path only."
        )
        self._run(prompt, label="write", **ov)
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
        return self._run(prompt, label="do", **ov)

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
        return self._run(prompt, label="search", **ov)

    def check(self, condition: str, **ov) -> bool:
        """Verify a claim about repo state; return True or False.

        The agent may run whatever it needs (commands, file reads) to
        establish the truth, but its answer contract is strict: the first
        word of the reply must be YES or NO. Anything else raises
        RangerError rather than guessing.

            agent.check("all tests pass")        # -> bool
            agent.check("README mentions the license")
        """
        prompt = (
            f"Decide whether this condition is TRUE in the current directory: "
            f"{condition}\n"
            "Actually verify it with file reads or shell commands — never "
            "guess. Reply with YES or NO as the first word, then one short "
            "line of evidence. No other preamble."
        )
        answer = self._run(prompt, label="check", **ov)
        match = re.match(r"\W*(yes|no)\b", answer.strip(), re.IGNORECASE)
        if not match:
            raise RangerError(
                f"check() could not parse a YES/NO verdict from:\n{answer[:300]}"
            )
        return match.group(1).upper() == "YES"

    def gate(self, command: str, timeout: float | None = None) -> bool:
        """Mechanical boolean gate: run a shell command, return exit==0.

        No model involved — pure subprocess. Use for checkable success
        conditions in your loops.

            if agent.gate("python -m pytest -q"):
                ...
        """
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                env={**os.environ, "PWD": self.cwd} if self.cwd else None,
                capture_output=True,
                timeout=timeout if timeout is not None else self.timeout,
            )
        except subprocess.TimeoutExpired:
            return False
        return proc.returncode == 0

    # ------------------------------------------------------------------ #
    # plumbing

    def _run(self, prompt: str, label: str = "run", **ov) -> str:
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

        # context recall: prepend recent recorded history (bounded), then
        # record the raw request/answer pair after a successful run
        use_memory = opts["memory"]
        full_prompt = prompt
        if use_memory and self.context:
            selected, total = [], 0
            for msg in reversed(self.context):
                total += len(msg["content"]) + 16
                if total > self.memory_budget:
                    break
                selected.append(msg)
            selected.reverse()
            if selected:
                transcript = "\n\n".join(
                    f"[{m['role']}] {m['content']}" for m in selected
                )
                full_prompt = (
                    "## Previous interaction in this session\n"
                    + transcript
                    + "\n\n## Current request\n"
                    + prompt
                )
        cmd.append(full_prompt)

        # live progress UI — stderr only; never a TTY in tests/pipes
        use_ui = opts["pretty"] and getattr(sys.stderr, "isatty", lambda: False)()
        spinner = None
        t0 = time.time()
        if use_ui:
            spinner = _Spinner(label, prompt)
            spinner.start()

        def _finish(mark: str, color: str, note: str = "") -> None:
            if not use_ui:
                return
            if spinner:
                spinner.stop()
            mm, ss = divmod(int(time.time() - t0), 60)
            note_part = f" {_c('·', 'dim')} {_clip(note, 84)}" if note else ""
            sys.stderr.write(
                f"  {_c(mark, color)} {_c(label, color)}"
                f" {_c('·', 'dim')} {_c(f'{mm:02d}:{ss:02d}', 'dim')}{note_part}\n"
            )
            sys.stderr.flush()

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
            _finish("✗", "red", "opencode CLI not found")
            raise RangerError(
                "opencode CLI not found on PATH — install it from https://opencode.ai"
            ) from None
        except subprocess.TimeoutExpired:
            _finish("✗", "red", f"timed out after {opts['timeout']}s")
            raise RangerError(
                f"opencode run timed out after {opts['timeout']}s"
            ) from None

        if proc.returncode != 0:
            _finish("✗", "red", _clip(proc.stderr, 90) or f"exit {proc.returncode}")
            raise RangerError(
                f"opencode run failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
            )
        first = proc.stdout.strip().splitlines()
        _finish("✓", "green", _clip(first[0], 90) if first else "")
        answer = proc.stdout.strip()
        if use_memory:
            self.context.append({"role": "user", "content": prompt})
            self.context.append({"role": "assistant", "content": answer})
        return answer
