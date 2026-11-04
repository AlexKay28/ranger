"""Shared constants, exceptions and small helpers for the whole package."""
from __future__ import annotations

import logging
import fnmatch
import os
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
    "retries", "env", "allow", "deny", "dry_run", "skills_budget",
    "evidence", "env_deny",
)

# Quote/clip lengths (chars) — one named place per frozen number, so an
# evidence policy or UI width change is a one-line edit.
ANSWER_EXCERPT = 300      # agent reply quoted in error evidence (law 5)
ROW_EXCERPT = 150         # one offending row quoted in error evidence
RAISED_PATHS_LISTED = 8    # violation paths listed in a do() rails error
UI_NOTE_CLIP = 90         # stderr/first-line shown in live progress marks
UI_RETRY_CLIP = 70        # exception text shown in retry progress lines
LOG_SHA_CLIP = 10          # commit sha prefix in log lines
LOG_MSG_CLIP = 60          # commit message shown in log lines

# quote()'s input-token estimate: chars divided by this rough divisor.
# Plainly an estimate, never a bill — output tokens are unguessable.
APPROX_CHARS_PER_TOKEN = 4

# Subprocess timeouts (seconds) and post-kill grace waits.
KILL_WAIT_S = 5          # cleanup grace after SIGKILL (transport only)
MODELS_TIMEOUT_S = 60    # `models` listing call per backend

# Recall accounting: per-message overhead added alongside content length.
RECALL_MSG_OVERHEAD = 16

# Live progress rendering: elapsed clock and clipped note/preview texts.
SECONDS_PER_MIN = 60     # mm:ss elapsed divisor (progress + spinner)
RUN_NOTE_CLIP = 84       # live-run note shown next to the progress mark
SPINNER_PREVIEW_CLIP = 40
SPINNER_FRAME_S = 0.1    # spinner frame interval

# Evidence clips quoted into results/errors.
GATE_OUT_CLIP = 400      # gate stdout+stderr shown in gate() result
DIAGNOSIS_CLIP = 800     # diagnosis fed to fix() rounds
CLAIM_CLIP = 80          # one claim truncated in verify_claims logs

# Generated-file names for write()/ensure_written().
SLUG_CLIP = 40           # task slug kept in the generated filename
UUID_HEX_CLIP = 6        # uuid hex suffix in generated filenames
SNAP_HEX_CLIP = 8        # uuid hex suffix in snapshot git-index names
SNAP_TIME_DECIMALS = 3   # snapshot timestamp precision

# git status --porcelain v1 record anatomy: "XY <path>" (or, with -z,
# "XY<path>\0"), path starts at col 3; a shorter record carries no path.
PORCELAIN_MIN = 4
PORCELAIN_PATH_AT = 3

def _normalize_patterns(name: str, value) -> "list[str] | None":
    """Validate an allow/deny spec: None, or a non-empty list of path globs."""
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        got = type(value).__name__
        example = f"{name}=[{value!r}]"
        raise TypeError(
            f"{name} must be a list of glob patterns, got a bare {got} "
            f"— wrap it: {example}"
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

def _normalize_env_names(name: str, value) -> "list[str] | None":
    """Validate an env-NAME deny spec: None, or a non-empty list of names."""
    if value is None:
        return None
    if isinstance(value, str):
        raise TypeError(
            f"{name} must be a list of environment names, got a bare "
            f"{type(value).__name__} — wrap it: {name}=[{value!r}]"
        )
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{name} must be a list of environment names, got {value!r}")
    names = []
    for n in value:
        if not isinstance(n, str):
            raise TypeError(f"{name} entries must be str, got {n!r}")
        names.append(n)
        if not names[-1]:
            raise ValueError(f"{name} must not contain empty names")
    return names or None


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


def _porcelain_changed_z(out: str) -> "dict[str, str]":
    """Map every changed path -> its XY status pair from `-z` records.

    Same parsing rules as `_porcelain_paths_z` (which is built on this):
    -z records are NUL-terminated and never quoted, so paths with
    spaces, non-ASCII names and uppercase rename/copy records survive
    intact. A rename/copy record (X or Y is R/C) carries BOTH paths —
    `git status --porcelain -z` emits the NEW path first, then the old
    one (`"R  new\\0old\\0"`) — and both sides inherit the record's XY
    pair, so a change AWAY from a rail path looks like its own change.
    """
    changed: "dict[str, str]" = {}
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if len(rec) < PORCELAIN_MIN:
            continue
        xy = rec[:PORCELAIN_PATH_AT - 1]
        p = rec[PORCELAIN_PATH_AT:].rstrip("/")
        if p:
            changed[p] = xy
        # rename/copy: the record owns the NEXT field too (the old path)
        if ("R" in rec[:2] or "C" in rec[:2]) and i < len(fields):
            old = fields[i].rstrip("/")
            i += 1
            if old:
                changed[old] = xy
    return changed


def _porcelain_paths_z(out: str) -> "list[str]":
    """Every changed path from `git status --porcelain -z` (issue #25).

    -z records are NUL-terminated and never quoted, so paths with
    spaces, non-ASCII names and rename `old -> new` arrows survive
    intact. A rename/copy record (X or Y is R/C) carries BOTH paths —
    real `git status --porcelain -z` emits the NEW path first, then
    the old one (`"R  new\\0old\\0"`) — and a rename counts as touching
    both sides: moving a file AWAY from a denied path or INTO one is
    equally outside the rails. Every other record is one path.
    """
    return list(_porcelain_changed_z(out))


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

    Honest platform limit: without ``os.killpg`` (Windows) containment
    degrades to killing the DIRECT child only — grandchildren the CLI
    spawned may escape the blast; POSIX platforms keep the full
    process-group kill.
    """
    killpg = getattr(os, "killpg", None)
    try:
        if killpg is None:
            # Windows degradation: no process groups to signal — the
            # direct child dies, grandchildren may survive
            proc.kill()
        else:
            # start_new_session=True made proc.pid the process-group
            # leader, so one killpg reaches the shell AND its pipeline
            killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.communicate(timeout=KILL_WAIT_S)
    except (subprocess.TimeoutExpired, OSError):
        # narrow, honest cleanup catch: only transport-level failures occur
        # here — cleanup must never mask the original exception
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
        self._preview = _clip(preview, SPINNER_PREVIEW_CLIP)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        start = time.time()
        i = 0
        while not self._stop.is_set():
            mm, ss = divmod(int(time.time() - start), SECONDS_PER_MIN)
            frame = _c(self.FRAMES[i % len(self.FRAMES)], 'cyan')
            dot = _c('·', 'dim')
            clock = _c(f'{mm:02d}:{ss:02d}', 'dim')
            head = f"\r  {frame} {self._label}"
            mid = f" {dot} {self._preview}"
            tail = f" {dot} {clock}   "
            sys.stderr.write(head + mid + tail)
            sys.stderr.flush()
            self._stop.wait(SPINNER_FRAME_S)
            i += 1
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)


