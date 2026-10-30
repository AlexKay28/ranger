"""Git snapshot/rollback/commit rails: hidden-ref snapshots through a temporary index, honest restores, stage-and-commit only — no destructive verbs."""
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
                    RangerHarnessError)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)


class SnapshotMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    def _git(self, *args, env: dict | None = None, timeout: float = 60) -> str:
        """Run ONE git plumbing call in the agent cwd; return stripped stdout.

        The same `ranger.subprocess.run` seam as harness runs, so tests
        stay fully mocked. Raises RangerError on a non-zero exit — the
        snapshot machinery must never turn a git failure into a silent
        no-op (failure is an exception, law 5).
        """
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.cwd,
                env=env or self._child_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise RangerError(
                "git CLI not found on PATH — snapshots/rollback need git"
            ) from None
        except subprocess.TimeoutExpired:
            raise RangerError(
                f"git {' '.join(args)} timed out after {timeout}s"
            ) from None
        if proc.returncode != 0:
            raise RangerError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()}"
            )
        return proc.stdout

    def snapshot(self, tag: str | None = None) -> dict:
        """Commit the current state to a hidden git ref (recoverability).

        Captures tracked + untracked-but-not-ignored files through a
        TEMPORARY index (`GIT_INDEX_FILE` in `.git/`), so neither the
        real index + staged state nor the working tree are touched. The
        commit lands on `refs/ranger/snapshots/<tag>` (inspectable with
        plain git) and is recorded in the explicit Python-side registry
        `agent.snapshot_log` (law 4). `tag=None` auto-names `snap-1`,
        `snap-2`, ...; explicit tags must be unique within the agent.

        An honest refusal, not a phantom snapshot: RangerError when cwd
        is not a git repository or git is missing. Auto-snapshots before
        mutating commands (opt-in via `Ranger(snapshots=True)`) are
        best-effort: skipped and logged, never claimed when absent.

            snap = agent.snapshot("before-refactor")
            ...
            agent.rollback("before-refactor")
        """
        root = self._repo_root("snapshot()")
        self._snap_seq += 1
        if tag is None:
            tag = f"snap-{self._snap_seq}"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", tag or ""):
            raise ValueError(f"invalid snapshot tag: {tag!r}")
        if any(s["tag"] == tag for s in self.snapshot_log):
            raise ValueError(f"snapshot tag already used: {tag!r}")
        index = Path(root) / ".git" / f"ranger-index-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        env = {**(self._child_env() or {}), "GIT_INDEX_FILE": str(index)}
        try:
            # add -A on the TEMP index only — no real index/worktree touch
            self._git("add", "-A", "--", env=env)
            tree = self._git("write-tree", env=env).strip()
            sha = self._git(
                "commit-tree", tree, "-m", f"ranger snapshot {tag}",
                env=env,
            ).strip()
            self._git("update-ref", f"refs/ranger/snapshots/{tag}", sha,
                      env=env)
        finally:
            try:
                index.unlink(missing_ok=True)
            except OSError:
                pass  # cleanup is best-effort by design
        entry = {"tag": tag, "sha": sha, "tree": tree,
                 "time": round(time.time(), 3)}
        self.snapshot_log.append(entry)
        _LOG.info("snapshot · tag=%s sha=%s", tag, sha[:10])
        return {"tag": tag, "sha": sha, "tree": tree, "root": root}

    def _repo_root(self, who: str) -> str:
        """The git repo root of cwd, or an honest RangerError."""
        root = self._git("rev-parse", "--show-toplevel").strip()
        if not root:
            raise RangerError(
                f"{who} cwd is not a git repository: {self.cwd!r}"
            )
        return root

    def _rollback_target(self, tag):
        """Resolve a snapshot tag (None = the latest recorded) to its entry."""
        if tag is None:
            if not self.snapshot_log:
                raise RangerError(
                    "rollback(): no snapshot recorded — nothing to restore"
                )
            tag = self.snapshot_log[-1]["tag"]
        entry = next((s for s in self.snapshot_log if s["tag"] == tag), None)
        if entry is None:
            known = ", ".join(s["tag"] for s in self.snapshot_log) or "none"
            raise RangerError(
                f"rollback(): unknown snapshot tag {tag!r} (recorded: {known})"
            )
        return tag, entry

    def _paths_changed_since(self, sha, tree) -> tuple:
        """Honest path diff of the CURRENT tree vs a snapshot.

        Returns (changed, extras): modified/deleted tracked paths
        (git diff --name-only) and post-snapshot untracked creations
        present now but absent from the snapshot tree — each by exact
        path, never a shotgun.
        """
        changed = [l for l in self._git("diff", "--name-only", sha).splitlines()
                   if l.strip()]
        untracked = [l for l in self._git(
            "ls-files", "--others", "--exclude-standard").splitlines()
            if l.strip()]
        snap_files = set(
            l for l in self._git("ls-tree", "-r", "--name-only", tree).split() if l
        )
        extras = [p for p in untracked if p not in snap_files]
        return changed, extras

    def rollback(self, tag: str | None = None) -> dict:
        """Restore the working tree to a snapshot (tag, or the last one).

        Returns `{"tag", "sha", "restored": [...]}` — the paths that
        differed between the snapshot and the current tree (modified
        tracked files plus untracked stragglers created after the
        snapshot). Mechanics: `git read-tree --reset -u <tree>` rewinds
        index+worktree to the snapshot (this resets staged state too —
        the snapshot itself never preserved staged-vs-worktree
        distinctions), then any post-snapshot untracked leftovers are
        removed by exact path (`git clean -fd -- <paths>`, never a
        shotgun). HEAD, branches and your commit history are untouched.

        RangerError when nothing is recorded, the tag is unknown, or cwd
        stopped being a git repository — an honest refusal, never a
        claimed restore.
        """
        tag, entry = self._rollback_target(tag)
        self._repo_root("rollback()")
        sha, tree = entry["sha"], entry["tree"]
        changed, extras = self._paths_changed_since(sha, tree)
        # 1) index+worktree <- snapshot tree; `-u` deletes files whose only
        #    justification was a post-snapshot index entry
        self._git("read-tree", "--reset", "-u", tree)
        # 2) untracked leftovers go away by exact path — no shotgun clean
        if extras:
            self._git("clean", "-fd", "--", *extras)
        restored = sorted(set(changed) | set(extras))
        _LOG.info("rollback · tag=%s · restored %d path(s)", tag, len(restored))
        return {"tag": tag, "sha": sha, "restored": restored}

    def commit(self, message: str | None = None,
               allow: "list[str] | None" = None,
               deny: "list[str] | None" = None) -> str:
        """Stage and commit the agent's own work in cwd. Returns the sha.

        Only ever runs `git add -A --` + `git commit -m`: it never
        pushes, resets, cleans or rewrites history — destructive
        operations are simply not part of the method.

        Honest refusals (RangerError): cwd is not a git repository;
        nothing changed (`git status --porcelain` empty — a clean tree
        is never "committed"); a changeset path hits the safety rails
        (`deny` wins, `allow` restricts — the #3 defaults apply when
        no per-call lists are given, and a denied path is never
        staged). `message=None` uses a marked default so agent commits
        are identifiable in `git log`.
        """
        effective_allow = _normalize_patterns(
            "allow", allow if allow is not None else self.allow)
        effective_deny = _normalize_patterns(
            "deny", deny if deny is not None else self.deny)
        root = self._repo_root("commit()")
        porcelain = self._git("status", "--porcelain")
        if not porcelain.strip():
            raise RangerError(
                "commit(): nothing to commit — the working tree is clean")
        for line in porcelain.splitlines():
            if len(line) < 4:
                continue
            p = line[3:].strip().strip('"').rstrip("/")
            if p:
                self._assert_path_allowed(p, effective_allow,
                                           effective_deny, root)
        msg = message or f"ranger: agent work ({time.strftime('%Y-%m-%d %H:%M')})"
        self._git("add", "-A", "--")
        self._git("commit", "-m", msg)
        sha = self._git("rev-parse", "HEAD").strip()
        _LOG.info("commit · %s · %s", sha[:10], _clip(msg, 60))
        return sha

    def _auto_snapshot(self, label: str):
        """Best-effort pre-round snapshot when `snapshots=True`.

        Never raises — a skipped snapshot is logged, never claimed.
        """
        if not self.snapshots:
            return None
        try:
            return self.snapshot(f"{label}-{self._snap_seq + 1}")
        except RangerError as exc:
            _LOG.info("snapshot skipped (%s): %s", label, exc)
            return None
