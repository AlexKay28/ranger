"""Reasoning commands — plan() and attempt() contracts, mocked end to end.

plan() is a dialogue command: ONE headless run that produces a numbered
implementation plan without touching the filesystem. attempt() is the
single-shot honest sibling of until(): ONE do(), one mechanical verdict,
with the same vacuous-green pre-check. All subprocess calls are mocked on
the `ranger.subprocess.run` seam (and `ranger.subprocess.Popen` for gates),
exactly like tests/test_reliability.py — no live harness runs in this suite.
"""

import subprocess
from unittest import mock

from ranger import Ranger


def fake_run(stdout: str, stderr: str = "", returncode: int = 0):
    """Mock subprocess.run result for the ranger.subprocess.run seam."""
    return subprocess.CompletedProcess(
        args=["mock"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def fake_popen(returncode=0, pid=4321, communicate=None):
    """Mock Popen for gate() (its own subprocess seam)."""
    p = mock.Mock()
    p.pid = pid
    p.returncode = returncode
    p.communicate = (mock.Mock(side_effect=communicate) if communicate
                     else mock.Mock(return_value=("", "")))
    return p


class TestPlan:
    def test_plan_prompt_contract_is_passed_to_the_harness(self, tmp_path):
        """The built prompt must demand read-only analysis, numbered steps
        referencing concrete files/commands, and end with the single
        riskiest assumption."""
        agent = Ranger(cwd=tmp_path)
        prompts = []

        def capture(cmd, **kw):
            prompts.append(cmd[-1])
            return fake_run("1. step")

        with mock.patch("ranger.subprocess.run", side_effect=capture):
            agent.plan("add a config validator")

        p = prompts[0]
        assert "add a config validator" in p
        assert "do NOT modify, create, or delete any file" in p
        assert "numbered plan" in p
        assert "concrete files" in p
        assert "commands to run" in p
        assert "Riskiest assumption:" in p

    def test_plan_returns_the_harness_answer(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("1. inspect x\n2. fix x")
        ):
            assert agent.plan("fix the parser") == "1. inspect x\n2. fix x"

    def test_plan_is_one_single_headless_run(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("1. step")
        ) as run_mock:
            agent.plan("whatever")
        run_mock.assert_called_once()

    def test_plan_recorded_in_agent_context(self, tmp_path):
        """plan is a dialogue command: the exchange lands in agent.context
        (and is therefore not in the history-free _PURE_LABELS set)."""
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("1. step one")
        ):
            agent.plan("goal under test")
        roles = [m["role"] for m in agent.context]
        assert roles == ["user", "assistant"]
        assert "goal under test" in agent.context[0]["content"]
        assert agent.context[1]["content"] == "1. step one"

    def test_plan_memory_false_skips_recording(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("1. step")
        ):
            agent.plan("quiet goal", memory=False)
        assert agent.context == []


class TestAttemptGateCmd:
    """attempt() with gate_cmd: red pre-check → do() → gate decides."""

    def test_attempt_precheck_green_runs_no_agent_work(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = iter([fake_popen(0, communicate=[("all good", "")])])
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run") as run_mock:
            res = agent.attempt("the goal", gate_cmd="pytest")
        assert res == {"passed": True, "already_green": True,
                       "goal": "the goal", "report": "",
                       "last_gate": {"kind": "gate_cmd", "ok": True,
                                     "output": "all good"}}
        run_mock.assert_not_called()

    def test_attempt_red_precheck_then_passing_gate(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = iter([
            fake_popen(1, communicate=[("fail", "")]),      # red pre-check
            fake_popen(0, communicate=[("clean run", "")]),  # green after do()
        ])
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch(
            "ranger.subprocess.run", return_value=fake_run("made the change")
        ) as run_mock:
            res = agent.attempt("add __repr__", gate_cmd="pytest")
        run_mock.assert_called_once()      # exactly ONE agent run (the do)
        assert res["passed"] is True
        assert res["already_green"] is False
        assert res["goal"] == "add __repr__"
        assert res["report"] == "made the change"
        assert res["last_gate"] == {"kind": "gate_cmd", "ok": True,
                                    "output": "clean run"}

    def test_attempt_red_gate_returns_output_tail(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = iter([
            fake_popen(1, communicate=[("old failure", "")]),
            fake_popen(1, communicate=[("", "AssertionError: still missing")]),
        ])
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch(
            "ranger.subprocess.run", return_value=fake_run("i fixed it, i swear")
        ):
            res = agent.attempt("add __repr__", gate_cmd="pytest")
        assert res["passed"] is False
        lg = res["last_gate"]
        assert lg["kind"] == "gate_cmd" and lg["ok"] is False
        assert "still missing" in lg["output"]
        assert res["report"] == "i fixed it, i swear"  # prose, not a verdict


class TestAttemptCondition:
    """attempt() verdicts via condition (agent YES/NO through check())."""

    def test_attempt_condition_path_passes(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        answers = iter([fake_run("NO"), fake_run("made it"), fake_run("YES")])
        with mock.patch(
            "ranger.subprocess.run", side_effect=lambda *a, **k: next(answers)
        ) as run_mock:
            res = agent.attempt("add tests", condition="the tests exist")
        assert run_mock.call_count == 3       # pre-check + do() + verdict
        assert res["passed"] is True
        assert res["already_green"] is False
        assert res["last_gate"] == {"kind": "condition", "ok": True,
                                    "output": ""}

    def test_attempt_default_check_verdict_fails_honestly(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        answers = iter([fake_run("NO"), fake_run("tried my best"),
                        fake_run("NO")])
        with mock.patch(
            "ranger.subprocess.run", side_effect=lambda *a, **k: next(answers)
        ):
            res = agent.attempt("the goal")
        assert res == {"passed": False, "already_green": False,
                       "goal": "the goal", "report": "tried my best",
                       "last_gate": {"kind": "check", "ok": False,
                                     "output": ""}}


class TestVerifyClaims:
    """verify_claims(): CLAIM: extraction, then per-claim check()s."""

    EXTRACTION = (
        "Here are the claims:\n"          # noise the parser must ignore
        "CLAIM: retries use exponential backoff\n"
        "some commentary line\n"
        "claim: lowercase prefix is ignored\n"
        "CLAIM: the timeout default is 180 seconds\n"
    )

    def test_claims_extraction_ignores_noise_lines(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=[fake_run(self.EXTRACTION),
                         fake_run("YES"), fake_run("YES")],
        ) as run_mock:
            results = agent.verify_claims("the retry logic")
        assert run_mock.call_count == 3    # 1 extraction + 2 checks
        parsed = [r["claim"] for r in results]
        assert parsed == ["retries use exponential backoff",
                          "the timeout default is 180 seconds"]

    def test_claims_get_per_claim_check_verdicts(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=[fake_run("CLAIM: a\nCLAIM: b"),
                         fake_run("YES"), fake_run("NO")],
        ):
            results = agent.verify_claims("t")
        assert results[0] == {"claim": "a", "verdict": "PASS", "ok": True}
        assert results[1] == {"claim": "b", "verdict": "FAIL", "ok": False}

    def test_claims_check_rangererror_is_uncertain(self, tmp_path):
        """A check() with an unparseable answer → UNCERTAIN, ok=None."""
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=[fake_run("CLAIM: maybe"),
                         fake_run("I could not determine that")],
        ):
            results = agent.verify_claims("t")
        assert results == [{"claim": "maybe", "verdict": "UNCERTAIN",
                            "ok": None}]

    def test_claims_max_claims_is_honored(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        extraction = "\n".join(f"CLAIM: claim number {i}" for i in range(6))
        checks = [fake_run("YES")] * 2
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=[fake_run(extraction)] + checks,
        ) as run_mock:
            results = agent.verify_claims("t", max_claims=2)
        assert run_mock.call_count == 3    # 1 extraction + only 2 checks
        assert [r["claim"] for r in results] == ["claim number 0",
                                                "claim number 1"]

    def test_claims_empty_extraction_raises_rangererror(self, tmp_path):
        import pytest
        from ranger import RangerError
        agent = Ranger(cwd=tmp_path)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("no claims here")
        ):
            with pytest.raises(RangerError, match="CLAIM"):
                agent.verify_claims("t")


def popen_seq(*specs):
    """Iterator of mocked Popens from (returncode, output) tuples."""
    return iter([fake_popen(rc, communicate=[(out, "")])
                 for rc, out in specs])


class TestResolve:
    """resolve(): pre-flight → plan() → bounded plan-guided attempts."""

    def test_resolve_precheck_green_runs_no_model(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((0, "already good"))
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run") as run_mock:
            res = agent.resolve("the goal", gate_cmd="pytest")
        assert res["status"] == "ALREADY_GREEN"
        assert res["iterations"] == 0 and res["plan"] == ""
        run_mock.assert_not_called()          # zero model runs

    def test_resolve_pass_in_one_round(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((1, "red pre-check"), (0, "green now"))
        answers = iter([fake_run("1. make it so"), fake_run("did step 1")])
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run",
                      side_effect=lambda *a, **k: next(answers)):
            res = agent.resolve("the goal", gate_cmd="pytest")
        assert res["status"] == "PASS"
        assert res["iterations"] == 1
        assert res["plan"].startswith("1.")     # plan() text travels
        assert res["report"] == "did step 1"

    def test_resolve_failed_honestly_at_budget(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((1, "red"), (1, "still red"), (1, "still red"))
        answers = iter([fake_run("1. try"),
                       fake_run("tried once"), fake_run("tried twice")])
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run",
                      side_effect=lambda *a, **k: next(answers)):
            res = agent.resolve("the goal", max_iter=2, gate_cmd="pytest")
        assert res["status"] == "FAILED"        # budget ends the loop
        assert res["iterations"] == 2
        assert res["last_gate"]["ok"] is False
        assert "tried" in res["report"]

    def test_resolve_rejects_bad_max_iter(self, tmp_path):
        import pytest
        agent = Ranger(cwd=tmp_path)
        with pytest.raises(ValueError):
            agent.resolve("g", max_iter=-1)
        with pytest.raises(ValueError):
            agent.resolve("g", max_iter="three")


class TestGateSequence:
    """gate_cmd as a list: short-circuit on first red + parts evidence."""

    def test_list_gate_all_green_has_parts_breakdown(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((0, "suite green"), (0, "chmod green"))
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run", return_value=fake_run("did")):
            res = agent.attempt("the goal",
                                gate_cmd=["pytest -q", "test -f x"])
        assert res["passed"] is True
        lg = res["last_gate"]
        assert lg["kind"] == "gate_cmd" and lg["ok"] is True
        assert len(lg["parts"]) == 2
        assert lg["parts"][0] == {"cmd": "pytest -q", "ok": True,
                                  "output": "suite green"}

    def test_list_gate_short_circuits_and_names_the_red_part(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((0, "suite green"),     # pre: part 1 ok
                           (1, "boom no xfile"),   # pre: part 2 red — stop
                           (0, "suite green"),     # post: part 1 ok
                           (1, "boom no xfile"))   # post: part 2 red — stop
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run", return_value=fake_run("tried")):
            res = agent.attempt("make x", gate_cmd=["pytest -q", "test -f x"])
        assert res["passed"] is False
        parts = res["last_gate"]["parts"]
        assert len(parts) == 2                    # part 3 never ran
        assert parts[1]["ok"] is False and "boom" in parts[1]["output"]
        assert "boom" in res["last_gate"]["output"]  # tail = the red part

    def test_string_gate_last_gate_stays_three_keys(self, tmp_path):
        """Backward compatibility: no parts key for a plain string gate."""
        agent = Ranger(cwd=tmp_path)
        popens = popen_seq((1, "red"), (0, "ok"))
        with mock.patch(
            "ranger.subprocess.Popen", side_effect=lambda *a, **k: next(popens)
        ), mock.patch("ranger.subprocess.run", return_value=fake_run("did")):
            res = agent.attempt("the goal", gate_cmd="pytest")
        assert set(res["last_gate"]) == {"kind", "ok", "output"}

    def test_empty_gate_sequence_raises(self, tmp_path):
        import pytest
        from ranger import RangerError
        agent = Ranger(cwd=tmp_path)
        with mock.patch("ranger.subprocess.run", return_value=fake_run("x")):
            with pytest.raises(RangerError):
                agent.attempt("the goal", gate_cmd=[])



