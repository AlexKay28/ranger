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

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ._util import (DEFAULT_MODEL, _LOG, _NO_COLOR, _RESET, _COLORS, _c,
                    _clip, _interrupt_payload, _kill_tree, _Spinner,
                    _RUN_KEYS, _normalize_patterns,
                    _path_matches, RangerError, RangerTimeout,
                    RangerHarnessError)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS, _MEMORY_BUDGET,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)
from ._backends import (_Backend, _OpenCodeBackend, _CodexBackend,
                        _PiBackend, _OpenHandsBackend, _ClaudeBackend,
                        _BACKEND_CLASSES, backends, register_backend)
from ._debate import debate
from ._safety import SafetyMixin
from ._snapshots import SnapshotMixin
from ._loops import LoopsMixin
from ._multi import MultiMixin
from ._commands import CommandsMixin
from ._engine import EngineMixin

__all__ = ["Ranger", "RangerError", "RangerTimeout", "RangerHarnessError",
           "DEFAULT_MODEL", "register_backend", "backends", "debate"]
__version__ = "0.7.1"

# One-time staleness warning guard: a process that resolves a run to the
# baked DEFAULT_MODEL is told once (per process) that the id may be stale.
# Lives ON THE PACKAGE: tests patch this attribute directly.
_DEFAULT_MODEL_WARNED = False


def _warn_default_model() -> None:
    """Warn once per process when the baked DEFAULT_MODEL is chosen.

    The package default is frozen at release time and can go stale; an
    explicit `model=` or `RANGER_MODEL` always silences this. Uses the
    module logger only — ranger never adds logging handlers.
    """
    global _DEFAULT_MODEL_WARNED
    if _DEFAULT_MODEL_WARNED:
        return
    _DEFAULT_MODEL_WARNED = True
    _LOG.warning(
        "ranger: using baked DEFAULT_MODEL '%s' which may be stale; "
        "pass model= or set RANGER_MODEL", DEFAULT_MODEL,
    )



class Ranger(SafetyMixin, SnapshotMixin, LoopsMixin, MultiMixin,
             CommandsMixin, EngineMixin):
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
        skills: allow-list of skills/tools the agent may use for each
            run. Entries may be a path to a markdown/SKILL.md file
            (attached via opencode's --file flag), a directory (its
            SKILL.md and *.md files are attached), or a plain prose
            grant that is injected into the prompt as guidance.
        mode: opencode agent name to run as ("build", "plan", "general",
            or any custom agent defined in the project's opencode
            config). Legacy alias: `agent=`.
        effort: "low" | "medium" | "high" depth directive. "low" biases
            the prompt toward brevity; "high" forces thinking blocks and
            a verify-before-answering directive; "medium" is neutral.
        stats: request runs in JSON mode and record telemetry into
            `agent.last` (wall/model time, part count, answer size,
            opencode session id).
        backend: which harness to drive — "opencode" (default), "codex",
            "pi" or "openhands".
            The public API is identical; harness differences (CLI flags,
            sessions, stats schemas) are absorbed internally. See the
            Backends section of docs/API.md for the exact behavior map.
        retries: how many times to re-attempt a failed run when the
            failure is transport-class (`RangerTimeout` — the run
            exceeded its timeout, or `RangerHarnessError` — the CLI is
            missing or exited unexpectedly). Prompt-contract failures
            (plain `RangerError`) never retry and raise immediately.
            Default 0.
        env: optional dict of environment variables merged over the fully
            inherited `os.environ` for the child CLI process (extend, never
            replace). `None` (default) means the child inherits everything
            untouched. See the "Child process environment" section of
            docs/API.md.
        allow: safety rail — list of path globs the agent may touch.
            `None`/empty (default) keeps today's behavior; non-empty
            restricts mutating commands to matching paths (fully
            replaceable per call via `allow=[...]`). Pure-Python
            predicates, never prompt instructions (paradigm law 4).
        deny: safety rail — path globs the agent may NEVER touch.
            Checked BEFORE `allow` (deny always wins), for every target
            the caller names (edit/write) and every path a do() actually
            changed (verified post-run via git when rails are active).
        snapshots: opt in to best-effort git snapshots before mutating
            commands (`do`, `edit`, `write`): tracked+untracked-but-not-
            ignored state is committed to a hidden ref
            `refs/ranger/snapshots/<tag>` using a TEMPORARY index — the
            real index and working tree are never touched. Restore with
            `agent.rollback()`. Snapshots are logged, never claimed when
            absent (non-git cwd → skipped, `RangerError` only on explicit
            `snapshot()`/`rollback()` calls). Default off so the per-call
            subprocess accounting stays exact.

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
        skills: list | None = None,
        mode: str | None = None,
        effort: str = "medium",
        stats: bool = False,
        backend: str = "opencode",
        retries: int = 0,
        env: dict | None = None,
        allow: "list[str] | None" = None,
        deny: "list[str] | None" = None,
        snapshots: bool = False,
    ) -> None:
        if effort not in ("low", "medium", "high"):
            raise ValueError(f"effort must be low|medium|high, got {effort!r}")
        if backend not in _BACKEND_CLASSES:
            raise ValueError(
                f"backend must be one of {', '.join(sorted(_BACKEND_CLASSES))}, "
                f"got {backend!r}"
            )
        self.backend = backend
        # raw explicit choice; effective default is resolved per run so a
        # per-call backend switch never inherits the other backend's default
        self._model_explicit = model
        if model:
            self.model = model
        else:
            env_model = os.environ.get("RANGER_MODEL")
            if env_model:
                self.model = env_model
            elif backend == "opencode":
                self.model = DEFAULT_MODEL
                _warn_default_model()
            else:
                self.model = None
        self.cwd = str(Path(cwd).resolve()) if cwd else None
        self.timeout = timeout
        self.auto = auto
        self.session = session
        self.agent = agent
        self.mode = mode
        self.title = title
        self.thinking = thinking
        self.pretty = pretty
        self.memory = memory
        self.memory_budget = memory_budget
        self.skills = skills
        self.effort = effort
        self.stats = stats
        self.retries = retries
        self.env = env
        self.last: dict = {}
        #: OpenAI-format conversation state: {"role", "content"} dicts.
        self.context: list[dict] = []
        #: opt-in: snapshot via git before mutating commands (do/edit/write)
        self.snapshots = snapshots
        #: safety rails (issue #3): path globs the agent may / may never
        #: touch — pure-Python predicates, never prompt politeness
        self.allow = _normalize_patterns("allow", allow)
        self.deny = _normalize_patterns("deny", deny)
        self.dry_run = False   # per-call switch only (see _RUN_KEYS)
        #: explicit Python-side snapshot registry: {"tag", "sha", "time"}
        self.snapshot_log: list[dict] = []
        self._snap_seq = 0
        #: cumulative cost/telemetry ledger (issue #6) — always recorded;
        #: tokens_* stay None until a backend actually reports them
        self._costs: dict = {
            "calls": 0, "chars_in": 0, "chars_out": 0,
            "tokens_in": None, "tokens_out": None, "wall_s": 0.0,
        }

    def __repr__(self) -> str:
        """Return a compact description of the core run settings."""
        return (
            f"Ranger(model={self.model!r}, backend={self.backend!r}, "
            f"memory={self.memory!r}, cwd={self.cwd!r})"
        )
