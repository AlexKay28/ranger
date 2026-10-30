"""Bounded agent loops: gates and verdicts, until/attempt/resolve/fix — mechanical verdicts, honest budgets, never a sympathy pass."""
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
                    RangerHarnessError, GATE_OUT_CLIP,
                    DIAGNOSIS_CLIP)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)


class LoopsMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    def _gate_ev(self, command: str, timeout: float | None = None) -> tuple[bool, str]:
        """gate() with evidence: returns (ok, clipped output tail).

        The tail is stdout+stderr, clipped, so until() can report WHY
        the gate stayed red — a boolean alone is not a diagnosis.
        """
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=self.cwd,
                env=self._child_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,  # own pg: cleanup has a real target
            )
        except FileNotFoundError:
            raise RangerError(
                f"gate() could not spawn a shell for: {command}"
            ) from None
        except OSError as exc:
            raise RangerError(f"gate() could not run {command!r}: {exc}") from None
        try:
            out, err = proc.communicate(
                timeout=timeout if timeout is not None else self.timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return False, f"gate timed out after {timeout if timeout is not None else self.timeout}s"
        except KeyboardInterrupt:
            _kill_tree(proc)
            raise
        return proc.returncode == 0, _clip((out or "") + (err or ""), GATE_OUT_CLIP)

    def _gate_sequence(self, gate_cmd, timeout):
        """Run a gate SEQUENCE: short-circuit on the first red part.

        The semantics of `part1 && part2 && ...` with a per-part
        breakdown, so a red verdict names the exact sub-check that
        failed (the false-red lesson: never diagnose a compound gate
        from one blended blob).
        """
        if not gate_cmd:
            raise RangerError("gate_cmd sequence must not be empty")
        parts = []
        for cmd in gate_cmd:
            self._gate_last = None
            ok = self.gate(cmd, timeout=timeout)
            ev = self._gate_last
            parts.append({"cmd": cmd, "ok": ok,
                          "output": ev[1] if ev else ""})
            _LOG.info("gate sequence %d/%d · %s · %s", len(parts),
                      len(gate_cmd), cmd, "ok" if ok else "RED")
            if not ok:
                break
        failed = next((p for p in parts if not p["ok"]), None)
        all_ok = failed is None
        out = failed["output"] if failed else parts[-1]["output"]
        return all_ok, out, parts

    def _gate_evidence(self, gate_cmd, timeout: float | None = None):
        """Evaluate gate_cmd — a single command string OR a sequence.

        Returns (ok, output_tail, parts) — parts is None for a plain
        string gate, and a list of {"cmd", "ok", "output"} for a list.
        """
        if isinstance(gate_cmd, str):
            self._gate_last = None
            ok = self.gate(gate_cmd, timeout=timeout)
            ev = self._gate_last
            return ok, (ev[1] if ev else ""), None
        return self._gate_sequence(gate_cmd, timeout)

    def _verdict(self, goal, gate_cmd, condition, **ov):
        """One mechanical verdict, shared by until()/attempt()/resolve().

        Returns (ok, last_gate_dict). For a gate_cmd sequence, last_gate
        gains a "parts" breakdown naming the sub-check that failed — for
        a plain string gate the dict stays exactly {"kind", "ok",
        "output"} (backward compatible).
        """
        if gate_cmd is not None:
            ok, out, parts = self._gate_evidence(gate_cmd,
                                                 timeout=ov.get("timeout"))
            last_gate = {"kind": "gate_cmd", "ok": ok, "output": out}
            if parts is not None:
                last_gate["parts"] = parts
            return ok, last_gate
        if condition is not None:
            ok = self.check(condition, **ov)
            return ok, {"kind": "condition", "ok": ok, "output": ""}
        ok = self.check(f"the goal is fully achieved: {goal}", **ov)
        return ok, {"kind": "check", "ok": ok, "output": ""}

    def _pre_loop_snapshot(self, who: str):
        """Best-effort pre-loop snapshot for rollback_on_fail (None=absent)."""
        try:
            return self.snapshot(
                f"pre-{who}-{time.strftime('%Y%m%d%H%M%S')}")["tag"]
        except RangerError as exc:
            # best-effort and logged — never claimed when absent
            _LOG.info("%s rollback_on_fail: no snapshot (%s)", who, exc)
            return None

    def _rollback_on_red(self, result: dict, snap_tag) -> None:
        """Attach honest rollback evidence to a red-budget result.

        Mutates `result` in place: rolled_back True/False plus the
        snapshot tag and either the restored paths or the error —
        absent snap_tag leaves both keys out (nothing claimed).
        """
        try:
            rb = self.rollback(snap_tag)
            result["rolled_back"] = True
            result["rollback"] = {"tag": snap_tag,
                                   "restored": rb["restored"]}
        except RangerError as exc:
            result["rolled_back"] = False
            result["rollback"] = {"tag": snap_tag, "error": str(exc)}

    def _until_round(self, goal, gate_cmd, condition, steps, ov):
        """One until() round: ask a step, do it, gate it.

        Returns (step, report, ok, last_gate) — the caller owns budget
        and honesty rules; this helper never decides them.
        """
        attempted = "\n".join(f"- {s}" for s in steps) or "- none"
        step = self.ask(
            f"Goal: {goal}\n"
            f"Steps already attempted:\n{attempted}"
            + "\n\nName ONE concrete, small next step toward the goal. "
            "Reply with the step only, one line.",
            **ov,
        ).strip()
        report = self.do(step, **ov)
        return step, report, *self._verdict(goal, gate_cmd, condition, **ov)

    def until(
        self,
        goal: str,
        max_iter: int = 5,
        gate_cmd: str | list | None = None,
        condition: str | None = None,
        rollback_on_fail: bool = False,
        **ov,
    ) -> dict:
        """The loop primitive: plan → do → verify, repeated until green.

        Each iteration asks for ONE concrete next step toward the goal,
        executes it with do(), then decides achieved/not via a mechanical
        gate — either `gate_cmd` (shell command, exit code decides; or a
        list of commands, run in order, short-circuiting on the first
        red — last_gate then carries a per-part breakdown) or `condition`
        (agent-verified YES/NO). With neither, the gate falls
        back to `check("the goal is fully achieved: {goal}")`.

        Honesty rule 1: the gate is evaluated BEFORE any agent work. A
        gate that is green before iteration 1 is vacuous — the return is
        `{"achieved": True, "iterations": 0, "steps": [],
        "report": "", "already_green": True}` so "it was green all
        along" can never masquerade as "the agent made it green". The
        pre-check costs one gate evaluation (a shell run for gate_cmd,
        one model run for condition) and is refunded whenever it saves a
        wasted iteration.

        Every return also carries `last_gate`: `{"kind", "ok", "output"}`
        — the mechanical verdict's own evidence (gate_cmd output tail,
        or "" for agent-verified conditions), so a red outcome is a
        diagnosis, not a dead end.

        Honesty rule 2 (unchanged): max_iter exhausted -> achieved=False,
        never a sympathy iteration because the agent says it's "almost
        done".

        Recoverability (issue #7): `rollback_on_fail=True` takes a git
        snapshot before round 1 and, when the budget ends red, restores
        the working tree to it — the result then carries
        `rolled_back: True` plus `rollback: {"tag", "restored"}`. Best
        effort and honest: with no git repo (or a failed snapshot) the
        outcome records `rolled_back: False` and never claims a restore.

            agent.until("tests folder has coverage for parse()",
                        gate_cmd="python -m pytest -q",
                        rollback_on_fail=True)
        """
        if not isinstance(max_iter, int) or max_iter < 0:
            raise ValueError(f"max_iter must be a non-negative int, got {max_iter!r}")
        steps: list[str] = []
        report = ""
        last_gate: dict = {}    # mechanical evidence of the final verdict
        # -- gate sanity pre-check: vacuous-green detection ------------ #
        pre_ok, pre_gate = self._verdict(goal, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("until pre-check · gate(%s) already green — no work needed",
                      pre_gate["kind"])
            return {"achieved": True, "iterations": 0, "steps": [],
                    "report": "", "already_green": True,
                    "last_gate": pre_gate}
        snap_tag: str | None = None
        if rollback_on_fail:
            snap_tag = self._pre_loop_snapshot("until")
        try:
            for i in range(1, max_iter + 1):
                step, report, ok, last_gate = self._until_round(
                    goal, gate_cmd, condition, steps, ov)
                steps.append(step)
                _LOG.info("until iteration %d/%d · gate(%s) → %s",
                          i, max_iter, last_gate["kind"],
                          "achieved" if ok else "not achieved")
                if ok:
                    return {"achieved": True, "iterations": i, "steps": steps,
                            "report": report, "last_gate": last_gate}
        except KeyboardInterrupt:
            # cancelled, not failed: nothing is claimed achieved, but the
            # progress already paid for survives in the exception message
            raise KeyboardInterrupt(_interrupt_payload(
                "until", {"achieved": False, "iterations": len(steps),
                          "steps": steps, "report": report,
                          "last_gate": last_gate})) from None
        result = {"achieved": False, "iterations": len(steps),
                  "steps": steps, "report": report, "last_gate": last_gate}
        if rollback_on_fail and snap_tag is not None:
            self._rollback_on_red(result, snap_tag)
        return result

    def attempt(
        self,
        goal: str,
        gate_cmd: str | list | None = None,
        condition: str | None = None,
        **ov,
    ) -> dict:
        """The single-shot honest sibling of until(): ONE do(), one verdict.

        Runs `do(goal)` exactly once, then decides passed/not via the
        same mechanical gate as until() — `gate_cmd` (shell command, or
        a list of commands run in order with a per-part breakdown in
        last_gate, exit code decides), else `condition` (agent-verified
        YES/NO), else `check("the goal is fully achieved: {goal}")`.

        Like until(), the gate is evaluated BEFORE any agent work: an
        already-green gate returns
        `{"passed": True, "already_green": True, "goal": goal,
        "report": "", "last_gate": {...}}` and runs NO agent work —
        "it was green all along" can never masquerade as "the agent
        made it green".

        The normal return carries `last_gate: {"kind", "ok", "output"}`
        — the mechanical verdict's own evidence, so a red outcome is a
        diagnosis, not a dead end.

            agent.attempt("add __repr__ to Parser",
                          gate_cmd="python -m pytest -q tests/test_parser.py")
        """
        # -- gate sanity pre-check: vacuous-green detection -------------- #
        pre_ok, pre_gate = self._verdict(goal, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("attempt pre-check · gate(%s) already green — no work needed",
                      pre_gate["kind"])
            return {"passed": True, "already_green": True, "goal": goal,
                    "report": "", "last_gate": pre_gate}
        report = self.do(goal, **ov)
        ok, last_gate = self._verdict(goal, gate_cmd, condition, **ov)
        _LOG.info("attempt · gate(%s) → %s", last_gate["kind"],
                  "passed" if ok else "not passed")
        return {"passed": ok, "already_green": False, "goal": goal,
                "report": report, "last_gate": last_gate}

    def _resolve_round(self, goal, plan_text, gate_cmd, condition, ov):
        """One resolve() round: execute the next plan step, gate it.

        Returns (report, ok, last_gate) — budget and honesty rules stay
        with the caller.
        """
        report = self.do(
            f"Goal: {goal}\n\n"
            f"Approved plan to follow:\n{plan_text}\n\n"
            "Execute the next unfinished step of the plan (or redo "
            "a step that stayed red) and report what you changed.",
            **ov,
        )
        ok, last_gate = self._verdict(goal, gate_cmd, condition, **ov)
        return report, ok, last_gate

    def resolve(
        self,
        goal: str,
        max_iter: int = 3,
        gate_cmd: str | list | None = None,
        condition: str | None = None,
        rollback_on_fail: bool = False,
        **ov,
    ) -> dict:
        """The resolver distilled: plan once, then bounded honest attempts.

        The command the resolved-sprint scripts were hand-rolling every
        time. Protocol — all honesty rules of until()/attempt() intact:

        1. pre-flight: the gate runs BEFORE any work; an already-green
           goal returns status "ALREADY_GREEN" with zero model calls
        2. plan() once: think without touching, before any file changes
        3. bounded do()→verdict loop (max_iter times): the plan travels
           with every iteration, every verdict is mechanical, never a
           sympathy pass — the loop ends at the budget, not at the
           agent's word

        status is exactly one of "ALREADY_GREEN" | "PASS" | "FAILED".
        The result carries the plan, the iteration count, the last do()
        report and last_gate evidence ({"kind", "ok", "output"}, plus a
        "parts" breakdown when gate_cmd is a list — a red names the
        exact sub-check that failed). gates must assert contracts, not
        prose.

            agent.resolve("add coverage for parse()",
                          gate_cmd=["python -m pytest -q",
                                    "python -m pytest -q -k parse"])
        """
        if not isinstance(max_iter, int) or max_iter < 0:
            raise ValueError(
                f"max_iter must be a non-negative int, got {max_iter!r}")
        pre_ok, pre_gate = self._verdict(goal, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("resolve pre-check · gate(%s) already green — no work needed",
                      pre_gate["kind"])
            return {"status": "ALREADY_GREEN", "goal": goal, "plan": "",
                    "iterations": 0, "report": "", "last_gate": pre_gate}
        snap_tag: str | None = None
        if rollback_on_fail:
            snap_tag = self._pre_loop_snapshot("resolve")
        plan_text = self.plan(goal, **ov)
        report = ""
        last_gate = pre_gate
        iters = 0
        try:
            for i in range(1, max_iter + 1):
                iters = i
                report, ok, last_gate = self._resolve_round(
                    goal, plan_text, gate_cmd, condition, ov)
                _LOG.info("resolve iteration %d/%d · gate(%s) → %s", i,
                          max_iter, last_gate["kind"],
                          "PASS" if ok else "not yet")
                if ok:
                    return {"status": "PASS", "goal": goal,
                            "plan": plan_text, "iterations": i,
                            "report": report, "last_gate": last_gate}
        except KeyboardInterrupt:
            # cancelled, not failed: progress already paid for survives
            raise KeyboardInterrupt(_interrupt_payload(
                "resolve",
                {"status": "FAILED", "goal": goal, "plan": plan_text,
                 "iterations": iters, "report": report,
                 "last_gate": last_gate})) from None
        result = {"status": "FAILED", "goal": goal, "plan": plan_text,
                  "iterations": iters, "report": report,
                  "last_gate": last_gate}
        if rollback_on_fail and snap_tag is not None:
            self._rollback_on_red(result, snap_tag)
        return result

    def fix(self, problem: str, gate_cmd: "str | list | None" = None,
            condition: str | None = None, max_iter: int = 3,
            **ov) -> dict:
        """Diagnose once, then bounded repair rounds — evidence-carrying.

        The tier's bounded repair: (1) mechanical pre-verdict (gate_cmd /
        condition / check fallback — green means ALREADY_GREEN, zero
        work: never invent work); (2) ONE read-only `diagnose()` pass;
        (3) at most `max_iter` `do()` repair rounds, each ending in a
        mechanical verdict — no sympathy pass when the budget ends.

        status is exactly "ALREADY_GREEN" | "FIXED" | "FAILED"; the
        result carries the diagnosis and last_gate evidence.

            agent.fix("tests/test_parser.py::test_tokens fails",
                      gate_cmd="python -m pytest -q -k tokens")
        """
        if (not isinstance(max_iter, int) or isinstance(max_iter, bool)
                or max_iter < 1):
            raise ValueError(
                f"max_iter must be a positive int, got {max_iter!r}")
        pre_ok, pre_gate = self._verdict(problem, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("fix pre-check · already green — no work needed")
            return {"status": "ALREADY_GREEN", "problem": problem,
                    "diagnosis": "", "iterations": 0, "last_gate": pre_gate}
        diagnosis = self.diagnose(problem, **ov)
        clipped = _clip(diagnosis, DIAGNOSIS_CLIP)
        last_gate: dict = pre_gate
        rounds = 0
        for i in range(1, max_iter + 1):
            rounds = i
            work = (
                "Repair this problem until the mechanical verdict passes.\n\n"
                f"Problem: {problem}\n\n"
                "Diagnosis from a read-only pass:\n"
                f"{clipped}\n\n"
                "Make the smallest correct fix, then rerun only the "
                "relevant checks before reporting."
            )
            self.do(work, **ov)
            ok, last_gate = self._verdict(problem, gate_cmd, condition, **ov)
            if ok:
                return {"status": "FIXED", "problem": problem,
                        "diagnosis": diagnosis, "iterations": i,
                        "last_gate": last_gate}
        return {"status": "FAILED", "problem": problem,
                "diagnosis": diagnosis, "iterations": rounds,
                "last_gate": last_gate}
