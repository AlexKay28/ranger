"""skills_budget: an opt-in per-file cap on inlined skill excerpts.

Default None keeps whole files — the frozen prompt composition is
byte-identical to before (pinned here). With `skills_budget=N` (chars),
each skill file a backend must INLINE (codex/claude/openhands — no
native file-attachment flag) travels as a verbatim head excerpt plus
an honest marker naming where the excerpt ends; validation refuses
0/negative/bool/non-int at the shared option boundary, before any
spawn. Native file-attachment backends (opencode, pi) send full files
through their own channel — the cap neither applies nor lies about it.
"""

from unittest import mock

import pytest

import ranger
from ranger import Ranger


def _codex_opts(**kw):
    base = dict(model="gpt-5.1-codex", cwd=None, timeout=600.0, auto=True,
                session=None, agent=None, mode=None, title=None,
                thinking=False, pretty=True, memory=True, skills=None,
                effort="medium", stats=False, backend="codex",
                memory_budget=20000, retries=0, env=None)
    base.update(kw)
    return base


def _skill_file(tmp_path, text):
    path = tmp_path / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


class TestExcerptComposition:
    def test_default_none_inlines_whole_file_verbatim(self, tmp_path):
        skill = _skill_file(tmp_path, "Rule one.\n\nRule two.\n")
        adapter = ranger._BACKEND_CLASSES["codex"]()
        _, prompt = adapter.build_cmd(_codex_opts(), "do work", [skill])
        assert "Rule one.\n\nRule two.\n" in prompt       # untouched
        assert "clipped" not in prompt

    def test_budget_clips_head_with_honest_marker(self, tmp_path):
        body = "".join(f"Rule {i}.\n" for i in range(1, 60))   # ~480 chars
        skill = _skill_file(tmp_path, body)
        adapter = ranger._BACKEND_CLASSES["codex"]()
        _, prompt = adapter.build_cmd(_codex_opts(skills_budget=50),
                                      "do work", [skill])
        assert body[:50] in prompt                            # verbatim head
        assert body[50:] not in prompt                        # nothing past it
        assert ("[skill excerpt clipped at 50 chars by skills_budget "
                f"— read the full file: {skill}]") in prompt
        assert "do work" in prompt                            # task survives

    def test_budget_larger_than_file_is_a_no_op(self, tmp_path):
        skill = _skill_file(tmp_path, "Be terse.")
        adapter = ranger._BACKEND_CLASSES["codex"]()
        _, whole = adapter.build_cmd(_codex_opts(skills_budget=10 ** 6),
                                     "do work", [skill])
        _, base = adapter.build_cmd(_codex_opts(), "do work", [skill])
        assert whole == base                                   # byte-identical


class TestBudgetFlowsThroughTheRunSeam:
    def test_per_call_budget_clips_the_spawned_prompt(self, tmp_path):
        skill = _skill_file(tmp_path, "x" * 400)
        agent = Ranger(backend="codex", cwd=tmp_path,
                       skills=[skill], memory=False)
        with mock.patch("ranger._engine._Popen",
                       return_value=_fake()) as m:
            agent.ask("hi", skills_budget=100)
        sent = m.call_args.kwargs.get("args") or m.call_args.args[0]
        prompt = " ".join(sent) if isinstance(sent, list) else str(sent)
        assert "clipped at 100 chars" in prompt


class TestBudgetValidation:
    @pytest.mark.parametrize("bad", [0, -5, True, "100", 2.5])
    def test_refuses_bad_budgets_before_any_spawn(self, bad):
        agent = Ranger(backend="codex")
        with mock.patch("ranger._engine._Popen") as run:
            with pytest.raises(ValueError, match="skills_budget"):
                agent.ask("hi", skills_budget=bad)
        run.assert_not_called()          # not even the spawn happened

    def test_with_config_budget_policy_does_not_need_a_ctor_param(self, tmp_path):
        """Session-level policy via with_config — the class default is None."""
        skill = _skill_file(tmp_path, "z" * 500)
        base = Ranger(backend="codex", cwd=tmp_path, skills=[skill],
                     memory=False)
        assert base.skills_budget is None            # class-level default
        agent = base.with_config(skills_budget=64)
        with mock.patch("ranger._engine._Popen",
                       return_value=_fake()) as m:
            agent.ask("hi")
        sent = m.call_args.kwargs.get("args") or m.call_args.args[0]
        prompt = " ".join(sent) if isinstance(sent, list) else str(sent)
        assert "clipped at 64 chars" in prompt
        assert base.skills_budget is None            # copy, not mutation

    def test_quote_shares_the_boundary(self):
        """quote() never spawns, but validates identically (law 5)."""
        agent = Ranger()
        with pytest.raises(ValueError, match="skills_budget"):
            agent.quote("hi", skills_budget=-1)


def _fake():
    ret = mock.Mock()
    ret.stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}'
    ret.stderr = ""
    ret.returncode = 0
    # the Popen transport reads the output pair from communicate()
    ret.communicate.return_value = (
        '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        "",
    )
    return ret
