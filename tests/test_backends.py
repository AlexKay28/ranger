"""Backend adapter contracts: pi and openhands (issue #2).

Fully mocked — no live CLI calls. These tests pin the researched CLI
surfaces (2026-10-25, official docs) so adapter drift from either
harness is caught here, not in a user's terminal.
"""

import subprocess
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError, RangerHarnessError

RANGER_MOD = "ranger.subprocess"


# --------------------------------------------------------------------- #
# registration

def test_all_four_backends_registered():
    names = ranger.backends()
    for name in ("opencode", "codex", "pi", "openhands"):
        assert name in names
    assert names == sorted(names)


def test_backend_must_be_known():
    with pytest.raises(ValueError, match="backend"):
        Ranger(backend="nope")


# --------------------------------------------------------------------- #
# pi backend

def _pi_opts(**kw):
    base = dict(model="anthropic/claude-sonnet-4-5", cwd=None, timeout=600.0,
                auto=True, session=None, agent=None, mode=None, title=None,
                thinking=False, pretty=True, memory=True, skills=None,
                effort="medium", stats=False, backend="pi",
                memory_budget=1000, retries=0, env=None)
    base.update(kw)
    return base


class TestPiBuildCmd:
    def test_basic_print_run(self):
        agent = Ranger(backend="pi", model="anthropic/claude-sonnet-4-5")
        adapter = ranger._BACKEND_CLASSES["pi"]()
        cmd, prompt = adapter.build_cmd(_pi_opts(), "do the thing", [])
        assert cmd == ["pi", "--print", "--model", "anthropic/claude-sonnet-4-5",
                       "--", "do the thing"]
        assert prompt == "do the thing"

    def test_no_model_flag_when_unset(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        cmd, _ = adapter.build_cmd(_pi_opts(model=None), "hi", [])
        assert "--model" not in cmd

    def test_never_emits_auto_flag_pi_has_no_permission_system(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        for auto in (True, False):
            cmd, _ = adapter.build_cmd(_pi_opts(auto=auto), "hi", [])
            assert "--approve" not in [c for c in cmd]
            assert not any("auto" in c for c in cmd)

    def test_session_title_thinking_skills(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        cmd, _ = adapter.build_cmd(
            _pi_opts(session="s1", title="t1", thinking=True,
                     skills=["a.md", "skillpack"]),
            "hi", ["a.md", "skillpack"],
        )
        assert cmd[1] == "--print"
        assert "--session-id" in cmd and cmd[cmd.index("--session-id") + 1] == "s1"
        assert "--name" in cmd and cmd[cmd.index("--name") + 1] == "t1"
        assert "--thinking" in cmd and cmd[cmd.index("--thinking") + 1] == "high"
        assert "--skill" in cmd
        assert cmd.count("--skill") == 2          # files AND dirs, native
        assert cmd[-2] == "--"                    # prompt is data
        assert cmd[-1] == "hi"

    def test_effort_maps_to_thinking_levels(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        cmd_hi, _ = adapter.build_cmd(_pi_opts(effort="high"), "hi", [])
        cmd_lo, _ = adapter.build_cmd(_pi_opts(effort="low"), "hi", [])
        cmd_mid, _ = adapter.build_cmd(_pi_opts(effort="medium"), "hi", [])
        assert "--thinking" in cmd_hi and "high" in cmd_hi
        assert "--thinking" in cmd_lo and "low" in cmd_lo
        assert "--thinking" not in cmd_mid

    def test_agent_mode_raise_unavailable(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        with pytest.raises(RangerError, match="does not support"):
            adapter.build_cmd(_pi_opts(agent="build"), "hi", [])
        with pytest.raises(RangerError, match="does not support"):
            adapter.build_cmd(_pi_opts(mode="plan"), "hi", [])

    def test_parse_output_is_text_passthrough(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        assert adapter.parse_output("  answer\n", True) == ("answer", None)

    def test_list_models_parses_output(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        out = "anthropic/claude-sonnet-4-5\nopenai/gpt-5.5\n"
        proc = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout=out, stderr="")
        with mock.patch(f"{RANGER_MOD}.run", return_value=proc):
            ids = adapter.list_models(None)
        assert ids == ["anthropic/claude-sonnet-4-5", "openai/gpt-5.5"]
        with mock.patch(f"{RANGER_MOD}.run", return_value=proc):
            assert adapter.list_models("claude") == ["anthropic/claude-sonnet-4-5"]

    def test_list_models_missing_cli_is_harness_error(self):
        adapter = ranger._BACKEND_CLASSES["pi"]()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=FileNotFoundError):
            with pytest.raises(RangerHarnessError, match="pi CLI not found"):
                adapter.list_models(None)


# --------------------------------------------------------------------- #
# openhands backend

def _oh_opts(**kw):
    base = dict(model=None, cwd=None, timeout=600.0, auto=True, session=None,
                agent=None, mode=None, title=None, thinking=False, pretty=True,
                memory=True, skills=None, effort="medium", stats=False,
                backend="openhands", memory_budget=1000, retries=0, env=None)
    base.update(kw)
    return base


class TestOpenHandsBuildCmd:
    def test_basic_headless_run(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        cmd, prompt = adapter.build_cmd(_oh_opts(), "fix the build", [])
        assert cmd == ["openhands", "--headless", "--task", "fix the build"]
        assert prompt == "fix the build"

    def test_model_is_env_never_a_flag(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        o = _oh_opts(model="gpt-5.5")
        cmd, _ = adapter.build_cmd(o, "hi", [])
        assert "-m" not in cmd and "--model" not in cmd
        assert "--override-with-envs" in cmd
        assert o["env"] == {"LLM_MODEL": "gpt-5.5"}   # folded into overlay

    def test_no_override_when_no_model(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        cmd, _ = adapter.build_cmd(_oh_opts(), "hi", [])
        assert "--override-with-envs" not in cmd

    def test_session_uses_resume(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        cmd, _ = adapter.build_cmd(_oh_opts(session="conv-9"), "hi", [])
        assert "--resume" in cmd and cmd[cmd.index("--resume") + 1] == "conv-9"

    def test_unsupported_options_raise_loudly(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        for bad in (_oh_opts(title="t"), _oh_opts(thinking=True),
                    _oh_opts(agent="build"), _oh_opts(mode="plan")):
            with pytest.raises(RangerError, match="does not support"):
                adapter.build_cmd(bad, "hi", [])

    def test_skills_inline_into_prompt(self, tmp_path):
        skill = tmp_path / "SKILL.md"
        skill.write_text("Be terse.", encoding="utf-8")
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        cmd, prompt = adapter.build_cmd(_oh_opts(), "do work", [skill])
        assert cmd[0] == "openhands"
        assert "--headless" in cmd
        assert "Attached skill file" in prompt
        assert "Be terse." in prompt
        assert "do work" in prompt
        # inlined docs also reach the CLI as the task body
        assert cmd[cmd.index("--task") + 1] == prompt

    def test_parse_output_is_text_passthrough(self):
        adapter = ranger._BACKEND_CLASSES["openhands"]()
        assert adapter.parse_output("transcript\n", True) == ("transcript", None)

    def test_model_env_fold_reaches_child_process(self):
        """The _run seam reads the adapter-mutated dict (o, not opts)."""
        agent = Ranger(backend="openhands", model="gpt-5.5", cwd=".")
        proc = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="done", stderr="")
        with mock.patch(f"{RANGER_MOD}.run", return_value=proc) as run_mock:
            assert agent.ask("hello") == "done"
        argv = run_mock.call_args.args[0]
        assert "--override-with-envs" in argv
        child_env = run_mock.call_args.kwargs["env"]
        assert child_env["LLM_MODEL"] == "gpt-5.5"
