"""Safety rails: allow/deny path predicates and pre/post guards around mutating commands (law 4: pure-Python predicates, never prompt politeness)."""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ._util import (DEFAULT_MODEL, _LOG, _NO_COLOR, _RESET, _COLORS, _c,
                    _clip, _interrupt_payload, _kill_tree,
                    _RUN_KEYS, _normalize_patterns,
                    _path_matches, RangerError, RangerTimeout,
                    RangerHarnessError, RAISED_PATHS_LISTED,
                    PORCELAIN_MIN, PORCELAIN_PATH_AT)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)


class SafetyMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    def _resolve_safety(self, ov: dict) -> tuple:
        """Effective (allow, deny, dry_run) for this call — per-call wins."""
        allow = _normalize_patterns("allow", ov.get("allow", self.allow))
        deny = _normalize_patterns("deny", ov.get("deny", self.deny))
        dry = ov.get("dry_run", self.dry_run)
        if not isinstance(dry, bool):
            raise TypeError(f"dry_run must be a bool, got {dry!r}")
        return allow, deny, dry

    def _assert_path_allowed(self, path, allow, deny, root=None) -> None:
        """Pure-Python path predicate — deny wins, then allow restricts."""
        if deny and _path_matches(path, deny, root):
            raise RangerError(
                f"path is denied by the safety rails: {Path(path)} "
                f"(deny: {', '.join(deny)})")
        if allow and not _path_matches(path, allow, root):
            raise RangerError(
                f"path is outside the allow safety rails: {Path(path)} "
                f"(allow: {', '.join(allow)})")

    def _guard_do(self, ov: dict) -> tuple:
        """Pre-spawn guard for TARGET-LESS mutating commands (do twins).

        The paths a do() will touch cannot be known before the spawn,
        so with rails active the tree MUST be mechanically verifiable
        (a git repo, for the post-run changed-path check) — otherwise
        the call is refused up front, never allowed-and-hoped. Returns
        (allow, deny, dry_run, root) for the post-run check.
        """
        allow, deny, dry = self._resolve_safety(ov)
        root = None
        if not dry and (allow or deny):
            root = self._git("rev-parse", "--show-toplevel").strip() or None
        return allow, deny, dry, root

    def _check_do_after(self, allow, deny, dry_run, root) -> None:
        """Post-run boundary for do twins: git status vs the rails.

        Law 5 honesty: a violation RAISES and names the paths; the tree
        is left mutated (our word is not a rollback) — pair with
        `snapshots=True` / `rollback()` for recovery.
        """
        if dry_run or not (allow or deny):
            return
        porcelain = self._git("status", "--porcelain")
        violations = []
        for line in porcelain.splitlines():
            if len(line) < PORCELAIN_MIN:
                continue
            p = line[PORCELAIN_PATH_AT:].strip().strip('"').rstrip("/")
            if not p:
                continue
            if deny and _path_matches(p, deny, root):
                violations.append(p)
            elif allow and not _path_matches(p, allow, root):
                violations.append(p)
        if violations:
            raise RangerError(
                "do() touched paths outside the safety rails: "
                + ", ".join(violations[:RAISED_PATHS_LISTED])
                + " — the working tree is LEFT MUTATED; pair rails with "
                  "snapshots=True / rollback() to recover")
