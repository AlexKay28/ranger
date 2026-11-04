"""Git snapshot/rollback/commit rails: hidden-ref snapshots through a temporary index, honest restores, stage-and-commit only — no destructive verbs."""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from ._util import (_LOG, _clip, _normalize_patterns, RangerError,
                    LOG_SHA_CLIP, LOG_MSG_CLIP,
                    _porcelain_paths_z,
                    SNAP_HEX_CLIP, SNAP_TIME_DECIMALS)

# ranger's one and only hidden-ref namespace: every snapshot lands on
# refs/ranger/snapshots/<tag>, and nothing outside it is ever touched
_SNAP_REFS = "refs/ranger/snapshots"


class SnapshotMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    def _git(self, *args, env: dict | None = None, timeout: float = 60,
             cwd: str | None = None) -> str:
        """Run ONE git plumbing call; return stripped stdout.

        Runs in `cwd` when given (rollback's tree-wide listings need the
        repo ROOT, not a subdirectory cwd), else in the agent cwd. The
        same `ranger.subprocess.run` seam as harness runs, so tests
        stay fully mocked. Raises RangerError on a non-zero exit — the
        snapshot machinery must never turn a git failure into a silent
        no-op (failure is an exception, law 5).
        """
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=cwd or self.cwd,
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
        TEMPORARY index (`GIT_INDEX_FILE` under the real git dir —
        `git rev-parse --absolute-git-dir`, so linked worktrees whose
        `.git` is a file work too), so neither the
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
        # the REAL git dir, not root/.git: in a linked worktree .git is a
        # FILE, and the temp index would land outside the repository
        git_dir = self._git("rev-parse", "--absolute-git-dir").strip()
        if not git_dir:  # pragma: no cover — git never answers rc 0 + empty
            git_dir = str(Path(root) / ".git")
        index = Path(git_dir) / f"ranger-index-{os.getpid()}-{uuid.uuid4().hex[:SNAP_HEX_CLIP]}"
        # inherit, THEN overlay, THEN strip the env_deny rail — all in
        # ONE _child_env call, so the temp-index env gets exactly the
        # child-CLI env treatment (audit A: flattening os.environ here
        # used to lose PATH/HOME for the cwd=None default agent, and a
        # deny rail the git child can bypass would not be a rail).
        env = self._child_env(env={"GIT_INDEX_FILE": str(index)},
                              deny=self.env_deny)
        try:
            # add -A on the TEMP index only — no real index/worktree touch
            self._git("add", "-A", "--", env=env)
            tree = self._git("write-tree", env=env).strip()
            sha = self._git(
                "commit-tree", tree, "-m", f"ranger snapshot {tag}",
                env=env,
            ).strip()
            self._git("update-ref", f"{_SNAP_REFS}/{tag}", sha,
                      env=env)
        finally:
            try:
                index.unlink(missing_ok=True)
            except OSError:
                pass  # cleanup is best-effort by design
        entry = {"tag": tag, "sha": sha, "tree": tree,
                 "time": round(time.time(), SNAP_TIME_DECIMALS)}
        self.snapshot_log.append(entry)
        _LOG.info("snapshot · tag=%s sha=%s", tag, sha[:LOG_SHA_CLIP])
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

    def _paths_changed_since(self, sha, tree, root) -> tuple:
        """Honest path diff of the CURRENT tree vs a snapshot.

        Returns (changed, extras): modified/deleted tracked paths
        (git diff --name-only) and post-snapshot untracked creations
        present now but absent from the snapshot tree — each by exact
        path, never a shotgun. Issue #25: all three listings are
        NUL-delimited (`-z`, with `-c core.quotepath=false` so bytes
        stay literal) — paths with spaces and non-ASCII names survive,
        and a rename's two paths stay two fields (`--name-only -z`
        emits `new\\0old\\0`, never a merged line).

        All three listings run in `root` (the repo ROOT), never the
        agent cwd: git lists relative to its cwd, so running them in a
        subdirectory would scope the diff/untracked scan to that
        subtree while snapshot() captured the WHOLE tree — root-level
        leftovers would survive rollback while `restored` claimed
        completeness. From the root, every path comes back
        root-relative and `clean` receives the same forms.
        """
        changed = [p for p in self._git("-c", "core.quotepath=false",
                                        "diff", "--name-only", "-z",
                                        sha, cwd=root).split("\0") if p]
        untracked = [p for p in self._git(
            "-c", "core.quotepath=false",
            "ls-files", "--others", "--exclude-standard",
            "-z", cwd=root).split("\0") if p]
        snap_files = set(
            p for p in self._git("-c", "core.quotepath=false",
                                 "ls-tree", "-r", "--name-only",
                                 "-z", tree, cwd=root).split("\0") if p
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
        shotgun). The listings, the rewind and the clean all run from
        the repo ROOT, so a rollback from a subdirectory cwd restores
        the WHOLE tree, not just the agent's subtree. HEAD, branches
        and your commit history are untouched.

        RangerError when nothing is recorded, the tag is unknown, or cwd
        stopped being a git repository — an honest refusal, never a
        claimed restore.
        """
        tag, entry = self._rollback_target(tag)
        root = self._repo_root("rollback()")
        sha, tree = entry["sha"], entry["tree"]
        changed, extras = self._paths_changed_since(sha, tree, root)
        # 1) index+worktree <- snapshot tree; `-u` deletes files whose only
        #    justification was a post-snapshot index entry
        self._git("read-tree", "--reset", "-u", tree, cwd=root)
        # 2) untracked leftovers go away by exact path — no shotgun clean;
        #    from the ROOT, so root-level stragglers die like any other
        if extras:
            self._git("clean", "-fd", "--", *extras, cwd=root)
        restored = sorted(set(changed) | set(extras))
        _LOG.info("rollback · tag=%s · restored %d path(s)", tag, len(restored))
        return {"tag": tag, "sha": sha, "restored": restored}

    def snapshots_prune(self, keep: int = 5) -> dict:
        """Delete the OLDEST snapshot REFS beyond the newest `keep`.

        Maintenance for the hidden-ref registry — snapshots accumulate
        forever otherwise. Every ref under `refs/ranger/snapshots/` is
        listed by `git for-each-ref --sort=creatordate`: each ref's own
        commit records the wall time `snapshot()` created it, so the
        ordering is the honest recorded one and survives process
        restarts and gaps in the Python-side `snapshot_log` alike. The
        oldest refs beyond `keep` are deleted with `git update-ref -d`
        and their entries dropped from `agent.snapshot_log` (a pruned
        snapshot is no longer rollbackable). The working tree, index,
        HEAD and results are never touched, and refs outside the ranger
        namespace are not even considered.

        `keep` must be a positive int (`ValueError` otherwise) — `keep=0`
        would wipe out every safety buffer in one call, so the minimum
        is 1. Returns `{"pruned": [...], "kept": [...]}`: snapshot
        tags, oldest-first. `RangerError` when cwd is not a git
        repository or git fails — an honest refusal, never a claimed
        prune.

            agent.snapshots_prune(keep=3)
            # {"pruned": ["snap-1"], "kept": ["snap-2", "snap-3"]}
        """
        if (not isinstance(keep, int) or isinstance(keep, bool)
                or keep < 1):
            raise ValueError(f"keep must be a positive int, got {keep!r}")
        refs = self._snapshot_refs_chrono()
        pruned, kept = refs[:-keep], refs[-keep:]
        for ref in pruned:
            self._git("update-ref", "-d", ref)
        gone = {self._snap_tag_of(r) for r in pruned}
        self.snapshot_log = [s for s in self.snapshot_log
                             if s["tag"] not in gone]
        _LOG.info("snapshots_prune · pruned %d · kept %d",
                  len(gone), len(kept))
        return {"pruned": [self._snap_tag_of(r) for r in pruned],
                "kept": [self._snap_tag_of(r) for r in kept]}

    def _snapshot_refs_chrono(self) -> "list[str]":
        """Ranger snapshot refs, OLDEST first.

        `git for-each-ref --sort=creatordate` on the one namespace:
        each ref's own commit records when `snapshot()` created it.
        Refs elsewhere in the repository are never listed — the prefix
        match keep the prune target set ranger-owned, no matter what
        for-each-ref was asked to show.
        """
        listing = self._git("for-each-ref", "--format=%(refname)",
                            "--sort=creatordate", _SNAP_REFS)
        return [r.strip() for r in listing.splitlines()
                if r.strip().startswith(f"{_SNAP_REFS}/")]

    @staticmethod
    def _snap_tag_of(ref: str) -> str:
        """Snapshot tag of a hidden ref — the basename after the last /."""
        # snapshot tags are regex-validated to contain no '/', so the
        # basename IS the tag
        return ref.rpartition("/")[2]

    def commit(self, message: str | None = None,
               allow: "list[str] | None" = None,
               deny: "list[str] | None" = None) -> str:
        """Stage and commit working-tree changes, REPO-WIDE. Returns the sha.

        The scope is honest and tree-wide (audit finding C): `git add
        -A --` carries no pathspec, so everything the repo-wide
        porcelain reported is staged and committed — cwd only decides
        where git runs, and changes the agent left OUTSIDE cwd are
        committed too. There is no subtree-scoped staging mode; point
        the agent's cwd at the repo root when the whole-tree view is
        the intent.

        Only ever runs `git add -A --` + `git commit -m`: it never
        pushes, resets, cleans or rewrites history — destructive
        operations are simply not part of the method.

        Honest refusals (RangerError): cwd is not a git repository;
        nothing changed (`git status --porcelain -z` empty — a clean
        tree is never "committed"); a changeset path hits the safety
        rails (`deny` wins, `allow` restricts — the #3 defaults apply
        when no per-call lists are given, and a denied path is never
        staged; a rename counts BOTH its sides, #25). `message=None`
        uses a marked default so agent commits
        are identifiable in `git log`.
        """
        effective_allow = _normalize_patterns(
            "allow", allow if allow is not None else self.allow)
        effective_deny = _normalize_patterns(
            "deny", deny if deny is not None else self.deny)
        root = self._repo_root("commit()")
        # NUL-delimited porcelain (#25): spaces, renames and non-ASCII
        # quote-needing paths keep their exact bytes
        porcelain = self._git("-c", "core.quotepath=false",
                              "status", "--porcelain", "-z")
        if not porcelain.strip():
            raise RangerError(
                "commit(): nothing to commit — the working tree is clean")
        for p in _porcelain_paths_z(porcelain):
            self._assert_path_allowed(p, effective_allow,
                                      effective_deny, root)
        msg = message or f"ranger: agent work ({time.strftime('%Y-%m-%d %H:%M')})"
        self._git("add", "-A", "--")
        self._git("commit", "-m", msg)
        sha = self._git("rev-parse", "HEAD").strip()
        _LOG.info("commit · %s · %s", sha[:LOG_SHA_CLIP], _clip(msg, LOG_MSG_CLIP))
        return sha

    def _auto_snapshot(self, label: str):
        """Best-effort pre-round snapshot when `snapshots=True`.

        Never raises — a skipped snapshot is logged, never claimed.
        RangerError (no git repo, git failure) and ValueError (e.g. a
        duplicate auto tag colliding with a user tag) both degrade to
        the honest no-snapshot result.
        """
        if not self.snapshots:
            return None
        try:
            return self.snapshot(f"{label}-{self._snap_seq + 1}")
        except (RangerError, ValueError) as exc:
            _LOG.info("snapshot skipped (%s): %s", label, exc)
            return None
