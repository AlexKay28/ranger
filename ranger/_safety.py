"""Safety rails: allow/deny path predicates and pre/post guards around mutating commands (law 4: pure-Python predicates, never prompt politeness)."""
from __future__ import annotations

from pathlib import Path

from ._util import (_normalize_patterns, _path_matches, RangerError,
                    RAISED_PATHS_LISTED, _porcelain_paths_z)


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

    def _path_violations(self, allow, deny, root) -> "list[str]":
        """Changed paths that fall outside the rails, from git status.

        `status --porcelain -z` (issue #25): NUL-delimited records
        keep paths with spaces, quote-needing names and rename pairs
        whole, and `-c core.quotepath=false` keeps the bytes literal.
        A rename counts BOTH its sides — a change away from a denied
        path is as much a rail violation as a change into one. A path
        violates when it matches the deny list, or when an allow list
        exists and it does not match it.
        """
        porcelain = self._git("-c", "core.quotepath=false",
                              "status", "--porcelain", "-z")
        violations = []
        for p in _porcelain_paths_z(porcelain):
            if deny and _path_matches(p, deny, root) \
                    or allow and not _path_matches(p, allow, root):
                violations.append(p)
        return violations

    def _check_do_after(self, allow, deny, dry_run, root) -> None:
        """Post-run boundary for do twins: git status vs the rails.

        Law 5 honesty: a violation RAISES and names the paths; the tree
        is left mutated (our word is not a rollback) — pair with
        `snapshots=True` / `rollback()` for recovery.
        """
        if dry_run or not (allow or deny):
            return
        violations = self._path_violations(allow, deny, root)
        if violations:
            raise RangerError(
                "do() touched paths outside the safety rails: "
                + ", ".join(violations[:RAISED_PATHS_LISTED])
                + " — the working tree is LEFT MUTATED; pair rails with "
                  "snapshots=True / rollback() to recover")
