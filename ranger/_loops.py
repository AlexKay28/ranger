"""Bounded agent loops: gates and verdicts, until/attempt/resolve/fix — mechanical verdicts, honest budgets, never a sympathy pass."""
from __future__ import annotations

import itertools
import os
import subprocess
import time

from ._util import (_LOG, _clip, _interrupt_payload, _kill_tree,
                    RangerError, GATE_OUT_CLIP,
                    DIAGNOSIS_CLIP, APPROX_CHARS_PER_TOKEN)

# process-wide pre-loop tag counter: two rollback loops started inside
# the same second (or two agents in one process) can never collide (#23)
_PRELOOP_TAG_SEQ = itertools.count(1)


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
        """Best-effort pre-loop snapshot for rollback_on_fail (None=absent).

        Tags append pid + a process-wide monotonic counter after the
        timestamp (issue #23): same-second loop starts used to collide
        on the bare-second tag and crash through this guard. ValueError
        is caught alongside RangerError — the only honest outcomes are
        a tag or None, never an exception.
        """
        tag = (f"pre-{who}-{time.strftime('%Y%m%d%H%M%S')}"
               f"-{os.getpid()}-{next(_PRELOOP_TAG_SEQ)}")
        try:
            return self.snapshot(tag)["tag"]
        except (RangerError, ValueError) as exc:
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

    @staticmethod
    def _validate_max_iter(value, minimum: int = 0) -> None:
        """max_iter: a real int >= minimum — bools refused everywhere.

        One guard for every bounded loop (issue #26): until/resolve/
        refine_with document minimum=0 (a valid zero-round budget),
        fix demands minimum=1 — whichever loop, the SAME bad value
        raises the SAME ValueError shape.
        """
        if (not isinstance(value, int) or isinstance(value, bool)
                or value < minimum):
            raise ValueError(
                f"max_iter must be an int >= {minimum}, got {value!r}")

    @staticmethod
    def _validate_token_budget(token_budget) -> None:
        """token_budget: None (off) or a positive int — refuse the rest."""
        if token_budget is None:
            return
        if (not isinstance(token_budget, int) or isinstance(token_budget, bool)
                or token_budget < 1):
            raise ValueError(
                f"token_budget must be a positive int, got {token_budget!r}")

    def _budget_guard(self, token_budget):
        """Predicate: True while the loop may run another round.

        Charges the cumulative `agent.costs` ledger: when the backend
        reports real tokens they decide, else chars divided by
        APPROX_CHARS_PER_TOKEN (the quote() estimate — a preview, not a
        bill). The metric is FIXED at loop entry so tokens/chars can
        never mix mid-flight. Checked BEFORE each round: a round in
        flight is never cancelled — see the KeyboardInterrupt contract.
        """
        if token_budget is None:
            return None
        c0 = self.costs
        use_tokens = c0["tokens_in"] is not None
        tokens0 = c0["tokens_in"] or 0
        chars0 = c0["chars_in"]

        def may_continue():
            c = self.costs
            if use_tokens and c["tokens_in"] is not None:
                spent = (c["tokens_in"] or 0) - tokens0
            else:
                spent = (c["chars_in"] - chars0) / APPROX_CHARS_PER_TOKEN
            return spent < token_budget

        return may_continue

    def _bounded_rounds(self, label: str, max_iter: int,
                        round_fn, interrupt_state, may_continue=None):
        """Shared until/resolve skeleton: rounds, interrupt, exhaustion.

        `round_fn(i)` runs one round and returns a COMPLETED result dict
        to return immediately, or None to keep iterating (it also updates
        `interrupt_state()`-visible progress along the way).
        `interrupt_state()` yields the exact payload a cancelled loop
        must carry. `may_continue()` (optional, from `_budget_guard`) is
        checked before every round; returning (done: bool, result,
        iterations_executed, budget_exhausted: bool). Honest by
        construction: a max_iter/token budget never fabricates success —
        `done` is False and the caller composes the red result.
        """
        executed = 0
        try:
            for i in range(1, max_iter + 1):
                if may_continue is not None and not may_continue():
                    return False, None, executed, True
                executed = i
                done_result = round_fn(i)
                if done_result is not None:
                    return True, done_result, executed, False
        except KeyboardInterrupt:
            raise KeyboardInterrupt(
                _interrupt_payload(label, interrupt_state())) from None
        return False, None, executed, False

    def _until_loop(self, goal, gate_cmd, condition, steps, progress,
                    ov, max_iter, snap_tag, may_continue=None):
        """Closures + bounded rounds for until(); composes the red result.

        Pure until()-specific orchestration: the round body, the
        cancelled-loop payload, the exhausted-budget result and the
        optional rollback all in one place.
        """
        def _interrupt_state():
            return {"achieved": False, "iterations": len(steps),
                    "steps": steps, "report": progress["report"],
                    "last_gate": progress["last_gate"]}

        def _round(i):
            step, report, ok, last_gate = self._until_round(
                goal, gate_cmd, condition, steps, ov)
            steps.append(step)
            progress["report"], progress["last_gate"] = report, last_gate
            _LOG.info("until iteration %d/%d · gate(%s) → %s",
                      i, max_iter, last_gate["kind"],
                      "achieved" if ok else "not achieved")
            if ok:
                return {"achieved": True, "iterations": i, "steps": steps,
                        "report": report, "last_gate": last_gate}
            return None

        done, green, _, budget_exhausted = self._bounded_rounds(
            "until", max_iter, _round, _interrupt_state, may_continue)
        if done:
            return green
        result = {"achieved": False, "iterations": len(steps),
                  "steps": steps, "report": progress["report"],
                  "last_gate": progress["last_gate"]}
        if budget_exhausted:
            result["budget_exhausted"] = True
        if snap_tag is not None:
            self._rollback_on_red(result, snap_tag)
        return result

    def until(
        self,
        goal: str,
        max_iter: int = 5,
        gate_cmd: str | list | None = None,
        condition: str | None = None,
        rollback_on_fail: bool = False,
        token_budget: int | None = None,
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
        done". max_iter must be a real int >= 0 — bools are refused
        (`True` is not a 1-iteration budget); 0 is a valid zero-round
        budget that spends nothing beyond the pre-verdict.

        `token_budget=N` bounds the loop by SPEND as well: the
        cumulative `agent.costs` ledger is charged per round — real
        tokens when the backend reports them, else chars/4 (the same
        quote() estimate — a preview, not a bill). Checked BEFORE each
        round, so a round in flight is never cancelled; when the
        budget — not max_iter — stops the loop, the red result carries
        `budget_exhausted: True`. The metric (tokens vs chars) is fixed
        at loop entry; none of this fabricates success.

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
        self._validate_max_iter(max_iter)
        self._validate_token_budget(token_budget)
        # -- gate sanity pre-check: vacuous-green detection ------------ #
        pre_ok, pre_gate = self._verdict(goal, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("until pre-check · gate(%s) already green — no work needed",
                      pre_gate["kind"])
            return {"achieved": True, "iterations": 0, "steps": [],
                    "report": "", "already_green": True,
                    "last_gate": pre_gate}
        steps: list[str] = []
        progress = {"report": "", "last_gate": {}}
        snap_tag = self._pre_loop_snapshot("until") if rollback_on_fail else None
        may_continue = self._budget_guard(token_budget)
        return self._until_loop(goal, gate_cmd, condition, steps, progress,
                                ov, max_iter, snap_tag, may_continue)

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

    def _resolve_loop(self, goal, plan_text, gate_cmd, condition, ov,
                      max_iter, progress, pre_gate, snap_tag,
                      rollback_on_fail, may_continue):
        """Closures + bounded rounds for resolve(); composes FAILED.

        Pure resolve()-specific orchestration: the round body, the
        cancelled-loop payload, the exhausted-budget result and the
        optional rollback all in one place.
        """
        def _interrupt_state():
            return {"status": "FAILED", "goal": goal, "plan": plan_text,
                    "iterations": progress["iterations"],
                    "report": progress["report"],
                    "last_gate": progress["last_gate"]}

        def _round(i):
            progress["iterations"] = i
            report, ok, last_gate = self._resolve_round(
                goal, plan_text, gate_cmd, condition, ov)
            progress["report"], progress["last_gate"] = report, last_gate
            _LOG.info("resolve iteration %d/%d · gate(%s) → %s", i,
                      max_iter, last_gate["kind"],
                      "PASS" if ok else "not yet")
            if ok:
                return {"status": "PASS", "goal": goal,
                        "plan": plan_text, "iterations": i,
                        "report": report, "last_gate": last_gate}
            return None

        done, green, iters, budget_exhausted = self._bounded_rounds(
            "resolve", max_iter, _round, _interrupt_state, may_continue)
        if done:
            return green
        result = {"status": "FAILED", "goal": goal, "plan": plan_text,
                  "iterations": iters, "report": progress["report"],
                  "last_gate": progress["last_gate"]}
        if budget_exhausted:
            result["budget_exhausted"] = True
        if rollback_on_fail and snap_tag is not None:
            self._rollback_on_red(result, snap_tag)
        return result

    def resolve(
        self,
        goal: str,
        max_iter: int = 3,
        gate_cmd: str | list | None = None,
        condition: str | None = None,
        rollback_on_fail: bool = False,
        token_budget: int | None = None,
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

        `max_iter=0` is a valid zero-round budget: a red gate returns
        status "FAILED" up front, without the plan() call — nothing is
        spent beyond the pre-verdict. max_iter must be a real int >= 0
        (bools are refused — `True` is not a 1-iteration budget).

        status is exactly one of "ALREADY_GREEN" | "PASS" | "FAILED".
        The result carries the plan, the iteration count, the last do()
        report and last_gate evidence ({"kind", "ok", "output"}, plus a
        "parts" breakdown when gate_cmd is a list — a red names the
        exact sub-check that failed). gates must assert contracts, not
        prose.

        `token_budget=N` additionally bounds the loop by SPEND (the
        `agent.costs` ledger — real tokens when reported, else the
        chars/4 quote() estimate), checked before each round; a FAILED
        stopped by the budget rather than max_iter carries
        `budget_exhausted: True`. Never a sympathy pass either way.

            agent.resolve("add coverage for parse()",
                          gate_cmd=["python -m pytest -q",
                                    "python -m pytest -q -k parse"])
        """
        self._validate_max_iter(max_iter)
        self._validate_token_budget(token_budget)
        pre_ok, pre_gate = self._verdict(goal, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("resolve pre-check · gate(%s) already green — no work needed",
                      pre_gate["kind"])
            return {"status": "ALREADY_GREEN", "goal": goal, "plan": "",
                    "iterations": 0, "report": "", "last_gate": pre_gate}
        if max_iter == 0:
            # zero-round budget: FAILED up front — no plan() call, no
            # snapshot, nothing spent beyond the pre-verdict (#26)
            _LOG.info("resolve zero-round budget · FAILED before any plan() call")
            return {"status": "FAILED", "goal": goal, "plan": "",
                    "iterations": 0, "report": "", "last_gate": pre_gate}
        snap_tag: str | None = None
        if rollback_on_fail:
            snap_tag = self._pre_loop_snapshot("resolve")
        plan_text = self.plan(goal, **ov)
        progress = {"report": "", "last_gate": pre_gate,
                    "iterations": 0}
        may_continue = self._budget_guard(token_budget)
        return self._resolve_loop(goal, plan_text, gate_cmd, condition,
                                  ov, max_iter, progress, pre_gate,
                                  snap_tag, rollback_on_fail, may_continue)

    def _fix_loop(self, problem, diagnosis, gate_cmd, condition, ov,
                  max_iter, progress, snap_tag, rollback_on_fail,
                  may_continue):
        """Closures + bounded rounds for fix(); composes FAILED.

        Same contract as until()/resolve(): rounds are bounded by
        max_iter and token_budget; interruption preserves the partial
        payload; a red budget may restore the tree; FAILED is honest.
        """
        clipped = _clip(diagnosis, DIAGNOSIS_CLIP)

        def _interrupt_state():
            return {"status": "FAILED", "problem": problem,
                    "diagnosis": diagnosis,
                    "iterations": progress["iterations"],
                    "last_gate": progress["last_gate"]}

        def _round(i):
            progress["iterations"] = i
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
            progress["last_gate"] = last_gate
            _LOG.info("fix iteration %d/%d · gate(%s) → %s", i, max_iter,
                      last_gate["kind"], "FIXED" if ok else "not yet")
            if ok:
                return {"status": "FIXED", "problem": problem,
                        "diagnosis": diagnosis, "iterations": i,
                        "last_gate": last_gate}
            return None

        done, fixed, iters, budget_exhausted = self._bounded_rounds(
            "fix", max_iter, _round, _interrupt_state, may_continue)
        if done:
            return fixed
        result = {"status": "FAILED", "problem": problem,
                  "diagnosis": diagnosis, "iterations": iters,
                  "last_gate": progress["last_gate"]}
        if budget_exhausted:
            result["budget_exhausted"] = True
        if rollback_on_fail and snap_tag is not None:
            self._rollback_on_red(result, snap_tag)
        return result

    def fix(self, problem: str, gate_cmd: "str | list | None" = None,
            condition: str | None = None, max_iter: int = 3,
            rollback_on_fail: bool = False,
            token_budget: "int | None" = None,
            **ov) -> dict:
        """Diagnose once, then bounded repair rounds — evidence-carrying.

        The tier's bounded repair: (1) mechanical pre-verdict (gate_cmd /
        condition / check fallback — green means ALREADY_GREEN, zero
        work: never invent work); (2) ONE read-only `diagnose()` pass;
        (3) at most `max_iter` `do()` repair rounds, each ending in a
        mechanical verdict — no sympathy pass when the budget ends.
        max_iter must be a real int >= 1 (bools refused — `True` is not
        a 1-round budget; 0 refused: zero repair rounds have nothing to
        gate).

        status is exactly "ALREADY_GREEN" | "FIXED" | "FAILED"; the
        result carries the diagnosis and last_gate evidence.
        `token_budget=N` bounds the rounds by SPEND too (the
        `agent.costs` ledger, checked before every round, exactly like
        until()/resolve() — see there); a FAILED the budget stopped
        carries `budget_exhausted: True`. `rollback_on_fail=True`
        snapshots before round 1 and restores the tree when the budget
        ends red (`rolled_back: True` + `rollback: {"tag", "restored"}`),
        best-effort and honest like until(); cancellation raises
        KeyboardInterrupt with the partial payload — diagnosis and the
        last verdict survive instead of evaporating.

            agent.fix("tests/test_parser.py::test_tokens fails",
                      gate_cmd="python -m pytest -q -k tokens")
        """
        self._validate_max_iter(max_iter, minimum=1)
        self._validate_token_budget(token_budget)
        pre_ok, pre_gate = self._verdict(problem, gate_cmd, condition, **ov)
        if pre_ok:
            _LOG.info("fix pre-check · already green — no work needed")
            return {"status": "ALREADY_GREEN", "problem": problem,
                    "diagnosis": "", "iterations": 0, "last_gate": pre_gate}
        diagnosis = self.diagnose(problem, **ov)
        progress = {"iterations": 0, "last_gate": pre_gate}
        snap_tag = self._pre_loop_snapshot("fix") if rollback_on_fail else None
        may_continue = self._budget_guard(token_budget)
        return self._fix_loop(problem, diagnosis, gate_cmd, condition, ov,
                              max_iter, progress, snap_tag, rollback_on_fail,
                              may_continue)
