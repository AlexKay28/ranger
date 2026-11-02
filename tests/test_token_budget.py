"""token_budget: loops bounded by SPEND, not just iterations.

The `agent.costs` ledger decides: real tokens when the backend reports
them, else chars/4 (the quote() estimate — a preview, not a bill).
Honesty contract, pinned here: a budget stop NEVER fabricates success —
until() returns achieved=False (+budget_exhausted: True), resolve()
returns status "FAILED" (+budget_exhausted: True), and no budget at all
leaves the red result dict byte-identical to before (no new keys).
"""

from unittest import mock

import pytest

from ranger import Ranger


def _spending_loop(agent, chars_per_round=4000):
    """Side effects: gate always red, do() burns chars_per_round chars."""
    def _gate(cmd, **kw):
        return False

    def _do(goal, **ov):
        agent._costs["chars_in"] += chars_per_round
        return f"worked on {goal}"

    def _ask(prompt, **ov):
        agent._costs["chars_in"] += chars_per_round
        return "a step"

    return (_gate, _do, _ask)


class TestUntilTokenBudget:
    def test_budget_stops_loop_with_honest_flag(self):
        agent = Ranger()
        gate, do, ask = _spending_loop(agent)   # 4000 chars = 1000 tokens/round
        with mock.patch.object(Ranger, "gate", side_effect=gate), \
             mock.patch.object(Ranger, "do", side_effect=do), \
             mock.patch.object(Ranger, "ask", side_effect=ask):
            outcome = agent.until("impossible", max_iter=10,
                                  gate_cmd="python -m pytest -q",
                                  token_budget=1500)
        # one round = ask + do = 8000 chars = 2000 est tokens. Round 1
        # runs (0 spent); before round 2 spent 2000 >= 1500 -> refused.
        assert outcome["achieved"] is False
        assert outcome["budget_exhausted"] is True
        assert outcome["iterations"] == 1
        assert len(outcome["steps"]) == 1

    def test_no_budget_red_shape_is_unchanged(self):
        """token_budget=None must not add ANY key to the plain red result."""
        agent = Ranger()
        gate, do, ask = _spending_loop(agent)
        with mock.patch.object(Ranger, "check", side_effect=lambda c, **ov: False), \
             mock.patch.object(Ranger, "do", side_effect=do), \
             mock.patch.object(Ranger, "ask", side_effect=ask):
            outcome = agent.until("impossible", max_iter=2)
        assert outcome == {"achieved": False, "iterations": 2,
                            "steps": ["a step", "a step"],
                            "report": "worked on a step",
                            "last_gate": {"kind": "check", "ok": False,
                                          "output": ""}}
        assert "budget_exhausted" not in outcome

    def test_already_green_precheck_ignores_budget(self):
        agent = Ranger()
        with mock.patch.object(Ranger, "gate", side_effect=lambda cmd, **kw: True):
            outcome = agent.until("already done", gate_cmd="true",
                                  token_budget=1)
        assert outcome["achieved"] is True
        assert outcome["already_green"] is True
        assert outcome["iterations"] == 0
        assert "budget_exhausted" not in outcome


class TestResolveTokenBudget:
    def test_budget_stops_resolve_with_failed_flag(self):
        agent = Ranger()
        gate, do, ask = _spending_loop(agent)
        with mock.patch.object(Ranger, "gate", side_effect=gate), \
             mock.patch.object(Ranger, "do", side_effect=do), \
             mock.patch.object(Ranger, "plan", side_effect=lambda g, **ov: "p"), \
             mock.patch.object(Ranger, "ask", side_effect=ask):
            outcome = agent.resolve("impossible", max_iter=10,
                                    gate_cmd="python -m pytest -q",
                                    token_budget=1500)
        assert outcome["status"] == "FAILED"
        assert outcome["budget_exhausted"] is True
        assert outcome["iterations"] == 2

    def test_spent_tokens_beat_chars_when_backend_reports(self):
        """Real reported tokens decide, not the chars/4 estimate."""
        agent = Ranger()
        agent._costs["tokens_in"] = 0     # backend reports: metric = tokens

        def _do(goal, **ov):
            agent._costs["tokens_in"] += 100
            return "did"

        with mock.patch.object(Ranger, "gate", side_effect=lambda c, **kw: False), \
             mock.patch.object(Ranger, "do", side_effect=_do), \
             mock.patch.object(Ranger, "plan", side_effect=lambda g, **ov: "p"):
            outcome = agent.resolve("impossible", max_iter=10,
                                    gate_cmd="pytest", token_budget=150)
        assert outcome["status"] == "FAILED"
        assert outcome["budget_exhausted"] is True
        assert outcome["iterations"] == 2   # 100<150, 100+100 >= 150 -> stop


class TestTokenBudgetValidation:
    @pytest.mark.parametrize("bad", [0, -1, True, "5", 3.5])
    def test_refuses_bad_budgets_before_any_work(self, bad):
        agent = Ranger()
        with mock.patch.object(Ranger, "gate") as gate, \
             mock.patch.object(Ranger, "check") as check:
            with pytest.raises(ValueError, match="token_budget"):
                agent.until("goal", token_budget=bad)
        gate.assert_not_called()     # not even the pre-check spawned
        check.assert_not_called()

    def test_resolve_refuses_bad_budgets_too(self):
        agent = Ranger()
        with mock.patch.object(Ranger, "gate") as gate:
            with pytest.raises(ValueError, match="token_budget"):
                agent.resolve("goal", token_budget=0)
        gate.assert_not_called()
