"""Shared constants, exceptions and small helpers for the whole package."""
from __future__ import annotations

import logging
import fnmatch
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_MODEL = "openrouter/anthropic/claude-sonnet-4.5"

# Module-level logger. ranger configures NO handlers: stdlib logging's
# last-resort stderr handler (or the host app's own config) decides where
# records go. The pretty stderr spinner UI is separate and untouched.
_LOG = logging.getLogger("ranger")

_RUN_KEYS = (
    "model", "timeout", "auto", "session", "agent", "mode", "title", "thinking",
    "pretty", "memory", "skills", "effort", "stats", "backend", "memory_budget",
    "retries", "env", "allow", "deny", "dry_run",
)

def _normalize_patterns(name: str, value) -> "list[str] | None":
    """Validate an allow/deny spec: None, or a non-empty list of path globs."""
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        raise TypeError(
            f"{name} must be a list of glob patterns, got a bare {type(value).__name__} "
            f"— wrap it: {name}=[{value!r}]"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a list of glob patterns, got {value!r}")
    pats = []
    for p in value:
        if not isinstance(p, (str, Path)):
            raise TypeError(f"{name} patterns must be str/Path, got {p!r}")
        pats.append(str(p))
        if not pats[-1]:
            raise ValueError(f"{name} must not contain empty patterns")
    return pats or None

def _path_matches(path: "Path | str", patterns, root=None) -> bool:
    """True when the path hits any glob — repo/cwd-relative or absolute."""
    p = Path(path)
    if p.is_absolute():
        forms = [p.resolve().as_posix()]
        if root:
            try:
                forms.append(p.resolve().relative_to(
                    Path(root).resolve()).as_posix())
            except ValueError:
                pass
    else:
        forms = [p.as_posix(),
                (Path(root or Path.cwd()) / p).as_posix()]
    return any(
        fnmatch.fnmatch(form, pat)
        for pat in (patterns or [])
        for form in forms
    )


class RangerError(RuntimeError):
    """Raised when the underlying opencode run fails."""


class RangerTimeout(RangerError):
    """Raised when a run exceeds its `timeout`.

    A subclass of `RangerError`, so existing `except RangerError` code
    keeps working unchanged.
    """


class RangerHarnessError(RangerError):
    """Raised when the harness CLI is missing or fails unexpectedly.

    Covers a CLI that is not on PATH, cannot be spawned, or exits with
    an unexpected failure. Subclass of `RangerError`, so existing
    `except RangerError` code keeps working unchanged.
    """


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


def _kill_tree(proc: "subprocess.Popen") -> None:
    """Kill a start_new_session child AND its whole process group.

    Best-effort by design: a dead or already-reaped process must not
    turn cleanup into a new failure. Reap afterwards so the child never
    lingers as a zombie.
    """
    try:
        # start_new_session=True made proc.pid the process-group leader,
        # so one killpg reaches the shell AND its entire pipeline
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:  # noqa: BLE001 — cleanup must never mask the exit
        pass


def _interrupt_payload(caller: str, partial: dict) -> str:
    """Human-readable cancel note for a loop interrupted mid-flight.

    Cancellation is honest by construction: nothing is claimed achieved
    ("survived": None / achieved False) — but the progress already paid
    for survives in the message instead of evaporating.
    """
    return (f"{caller}() cancelled — nothing claimed complete; "
            f"partial state: {partial!r}")


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


