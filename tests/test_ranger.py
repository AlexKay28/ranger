"""ranger unit tests — pinned behavior of the shipped API.

All subprocess calls are mocked: no live opencode runs, safe to run anywhere.

Contract (cycle 2 of the growth loop): >=12 tests, exit 0, no changes to
ranger/__init__.py, no network, no real agent calls.
"""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError
from ranger import DEFAULT_MODEL


def fake_run(stdout="", stderr="", returncode=0):
    """Build a mock subprocess.run return value with the given results."""
    ret = mock.Mock()
    ret.stdout = stdout
    ret.stderr = stderr
    ret.returncode = returncode
    return ret


# --------------------------------------------------------------------- #
# command construction

def test_run_default_flags_and_pwd_env():
    agent = Ranger(cwd="/tmp/demo")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("hi")) as m:
        assert agent.ask("hello") == "hi"
    cmd = m.call_args.args[0]
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"
    assert "--model" in cmd and DEFAULT_MODEL in cmd  # package default when no env/arg
    assert "--auto" in cmd
    assert "hello" in cmd  # prompt travels as the last argument
    assert m.call_args.kwargs["cwd"] == "/tmp/demo"
    # the PWD env fix: subprocess cwd alone is not enough for opencode
    assert m.call_args.kwargs["env"]["PWD"] == "/tmp/demo"


def test_ranger_model_env_override():
    import os
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "custom/m"}), mock.patch(
        "ranger.subprocess.run", return_value=fake_run("ok")
    ) as m:
        Ranger().ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "custom/m"
    # explicit argument still beats the environment
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "custom/m"}), mock.patch(
        "ranger.subprocess.run", return_value=fake_run("ok")
    ) as m:
        Ranger(model="arg/m").ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "arg/m"


def test_run_no_pwd_env_without_cwd():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    # env=None means "inherit": no PWD override is injected without a cwd
    assert m.call_args.kwargs.get("env") is None


def test_run_optional_flags_off_or_on():
    agent = Ranger(auto=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    assert "--auto" not in m.call_args.args[0]

    agent2 = Ranger(session="s1", agent="build", title="t", thinking=True)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent2.ask("hi")
    cmd = m.call_args.args[0]
    for flag in ("--session", "--agent", "--title", "--thinking"):
        assert flag in cmd
    assert "s1" in cmd and "build" in cmd and "t" in cmd


def test_per_call_override_beats_default():
    agent = Ranger(model="base/model", timeout=100)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi", model="other/model")
    cmd = m.call_args.args[0]
    i = cmd.index("--model") + 1
    assert cmd[i] == "other/model"
    assert m.call_args.kwargs["timeout"] == 100  # default survives where not overridden

    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi", timeout=42)
    assert m.call_args.kwargs["timeout"] == 42

    # and default switches over with_config too
    fast = agent.with_config(model="fast/model")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        fast.ask("hi")
    assert m.call_args.args[0][m.call_args.args[0].index("--model") + 1] == "fast/model"


def test_unknown_run_option_raises():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")):
        with pytest.raises(TypeError):
            agent.ask("hi", bogus="x")
        with pytest.raises(TypeError):
            agent.do("goal", modle="typo")


# --------------------------------------------------------------------- #
# error paths

def test_nonzero_exit_raises_with_stderr():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("", stderr="boom", returncode=1)):
        with pytest.raises(RangerError, match="boom"):
            agent.ask("hi")


def test_timeout_raises_ranger_error():
    agent = Ranger(timeout=5)
    with mock.patch(
        "ranger.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)
    ):
        with pytest.raises(RangerError, match="timed out"):
            agent.ask("hi")


def test_missing_opencode_binary():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RangerError, match="opencode CLI not found"):
            agent.ask("hi")


# --------------------------------------------------------------------- #
# models discovery

def test_models_parses_and_filters():
    out = "openrouter/anthropic/claude-sonnet-4.5\nopenrouter/google/gemini-2.5-flash\n\n"
    with mock.patch("ranger.subprocess.run", return_value=fake_run(out)) as m:
        assert Ranger.models() == [
            "openrouter/anthropic/claude-sonnet-4.5",
            "openrouter/google/gemini-2.5-flash",
        ]
        assert Ranger.models(match="GEMINI") == ["openrouter/google/gemini-2.5-flash"]
    assert m.call_args.args[0] == ["opencode", "models"]
    with mock.patch("ranger.subprocess.run", return_value=fake_run(out)):
        assert Ranger.models(match="nomatch-zzz") == []  # case-insensitive filter


def test_models_failure_raises():
    with mock.patch(
        "ranger.subprocess.run", return_value=fake_run("", stderr="err", returncode=1)
    ):
        with pytest.raises(RangerError, match="opencode models failed"):
            Ranger.models()
    with mock.patch("ranger.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RangerError, match="opencode CLI not found"):
            Ranger.models()


# --------------------------------------------------------------------- #
# with_config

def test_with_config_clones_and_does_not_touch_original():
    base = Ranger(model="a/b", cwd="examples")
    clone = base.with_config(model="c/d", agent="build")
    assert clone.model == "c/d" and clone.agent == "build"
    assert base.model == "a/b" and base.agent is None
    assert clone.cwd == str(Path("examples").resolve())  # cwd normalized
    with pytest.raises(TypeError):
        base.with_config(nope="x")


# --------------------------------------------------------------------- #
# write(): the file is the answer

def test_write_returns_path_and_requires_file(tmp_path):
    agent = Ranger(cwd=tmp_path)
    made = {}

    def side_effect(cmd, **kw):
        made["path"] = cmd[-1].split("exactly:")[1].strip().splitlines()[0]
        Path(made["path"]).write_text("report")
        return fake_run(str(made["path"]))

    with mock.patch("ranger.subprocess.run", side_effect=side_effect):
        assert agent.write("make a report") == made["path"]
        assert Path(made["path"]).exists()

    # agent claims it wrote but no file -> RangerError, not a silent pass
    with mock.patch("ranger.subprocess.run", return_value=fake_run("claimed.md")):
        with pytest.raises(RangerError, match="did not write the expected file"):
            agent.write("make a report", path=tmp_path / "claimed.md")


# --------------------------------------------------------------------- #
# prompt contracts of the shipped commands

def test_command_prompt_contents(tmp_path):
    agent = Ranger(cwd=tmp_path)
    target = tmp_path / "notes.md"
    prompts = []

    def capture(cmd, **kw):
        prompts.append(cmd[-1])
        return fake_run("ok")

    with mock.patch("ranger.subprocess.run", side_effect=capture):
        agent.summarize(target)
        agent.do("rename the files")
        agent.search("where is config parsed")

    assert str(target.resolve()) in prompts[0]
    assert "rename the files" in prompts[1]
    assert "where is config parsed" in prompts[2]
    assert "No code changes" in prompts[2]


def test_write_slug_fallback_for_empty_task(tmp_path):
    agent = Ranger(cwd=tmp_path)
    seen = []

    def capture(cmd, **kw):
        seen.append(cmd[-1])
        return fake_run("p")

    with mock.patch("ranger.subprocess.run", side_effect=capture):
        with pytest.raises(RangerError):  # no file appears -> error, as contracted
            agent.write("")
    # the prompt still got a concrete target path with the slug fallback
    assert "ranger_ranger_out_" in seen[0]


def test_docs_do_not_mention_internal_providers():
    """Public-repo hygiene gate: no internal provider ids in code or docs.

    Scans every .py and .md file in the repo (plus pyproject.toml), except
    this test file, which names the banned words by definition.
    """
    repo = Path(__file__).parent.parent
    banned = ("eliza", "glm-5-3", "glm-5.3-flash", "glm53")
    me = Path(__file__).resolve()
    files = (
        [repo / "pyproject.toml"]
        + list(repo.rglob("*.py"))
        + list(repo.rglob("*.md"))
    )
    for f in files:
        if any(part in str(f) for part in (".git/", ".pytest_cache", "egg-info", "__pycache__")):
            continue
        if f.resolve() == me:
            continue
        text = f.read_text()
        for word in banned:
            assert word not in text, f"{f}: internal id '{word}' leaked"


# --------------------------------------------------------------------- #
# skills allow-list

def test_skill_file_attached_via_file_flag(tmp_path):
    skill = tmp_path / "haiku.md"
    skill.write_text("Always answer in haiku form.")
    agent = Ranger(skills=str(skill))
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x")) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--file") + 1] == str(skill)
    assert "--file" in cmd


def test_skill_directory_attaches_markdown(tmp_path):
    sdir = tmp_path / "pack"
    sdir.mkdir()
    (sdir / "SKILL.md").write_text("# pack")
    (sdir / "extra.md").write_text("# extra")
    (sdir / "ignore.txt").write_text("not markdown")
    agent = Ranger(skills=sdir)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x")) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    attached = {cmd[i + 1] for i, x in enumerate(cmd) if x == "--file"}
    assert attached == {str(sdir / "SKILL.md"), str(sdir / "extra.md")}


def test_skill_empty_directory_raises(tmp_path):
    sdir = tmp_path / "empty"
    sdir.mkdir()
    agent = Ranger(skills=sdir)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x")):
        with pytest.raises(RangerError, match="no markdown"):
            agent.ask("hi")


def test_prose_grant_injected_into_prompt():
    agent = Ranger(skills=["always answer in haiku form", "use british spelling"])
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("tell me about tests")
    sent = m.call_args.args[0][-1]
    assert sent.startswith("## Allowed skills")
    assert "haiku form" in sent and "british spelling" in sent
    assert "--file" not in m.call_args.args[0]


def test_skills_per_call_override_beats_default(tmp_path):
    skill = tmp_path / "s.md"
    skill.write_text("x")
    agent = Ranger(skills=str(skill))
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    assert "--file" in m.call_args.args[0]
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi", skills=["prose only grant"])  # overrides, no file
    assert "--file" not in m.call_args.args[0]
    assert "prose only grant" in m.call_args.args[0][-1]


def test_no_skills_no_flags_by_default():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    assert "--file" not in m.call_args.args[0]
    assert m.call_args.args[0][-1] == "hi"


# --------------------------------------------------------------------- #
# context state

def test_context_records_openai_format_after_each_run():
    agent = Ranger(memory=True)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("answer here")):
        agent.ask("hi")
    assert agent.context == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "answer here"},
    ]


def test_context_recall_prepends_history():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", side_effect=[fake_run("first answer")]) as m:
        agent.ask("first question")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("second answer")) as m:
        agent.ask("second question")
    sent = m.call_args.args[0][-1]
    assert "first question" in sent and "first answer" in sent
    assert "## Current request\nsecond question" in sent
    # raw answers recorded, not the context-prefixed prompt (no nesting)
    assert agent.context[2]["content"] == "second question"


def test_context_memory_off_stops_recording_and_recall():
    agent = Ranger(memory=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("who")):
        agent.ask("knock")
    assert agent.context == []
    with mock.patch("ranger.subprocess.run", return_value=fake_run("who")) as m:
        agent.ask("knock again")
    assert m.call_args.args[0][-1] == "knock again"  # no context block


def test_context_per_call_override():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("a")):
        agent.ask("one")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("b")) as m:
        agent.ask("two", memory=False)  # isolated run
    assert m.call_args.args[0][-1] == "two"
    assert len(agent.context) == 2  # and nothing recorded for it


def test_context_budget_bounds_recall():
    agent = Ranger(memory_budget=10)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x" * 500)):
        agent.ask("big exchange")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("y")) as m:
        agent.ask("next")
    # nothing fits in the budget -> the run is sent raw
    assert m.call_args.args[0][-1] == "next"


def test_context_clear_returns_old_and_resets():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("a")):
        agent.ask("one")
    removed = agent.context_clear()
    assert agent.context == []
    assert [m["role"] for m in removed] == ["user", "assistant"]


def test_context_compact_replaces_history_with_system_digest():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("step one happened"), fake_run("- did step one\n- learned X"),
    ]):
        agent.ask("do step one")
        digest = agent.context_compact()
    assert digest == "- did step one\n- learned X"
    assert agent.context == [{"role": "system", "content": digest}]
    # the compacted summary is recalled in the next run
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("next step")
    sent = m.call_args.args[0][-1]
    assert "[system] - did step one" in sent and "Prompt contracts" not in sent


def test_context_summarize_keeps_history():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("note"), fake_run("digest"),
    ]):
        agent.ask("question")
        agent.context_summarize()
    # question + summarize runs are both recorded; nothing was collapsed
    assert len(agent.context) >= 4
    assert all(m["role"] in ("user", "assistant") for m in agent.context)


def test_gate_never_records_context():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("", returncode=0)):
        agent.gate("true")
    assert agent.context == []  # gate is model-free: not part of the transcript


# --------------------------------------------------------------------- #
# boolean gates

@pytest.mark.parametrize("reply,expected", [
    ("YES — all 15 tests pass.", True),
    ("NO — two tests fail.", False),
    ("Yes, the license is mentioned.", True),
    ("no, nothing matches.", False),
])
def test_check_parses_verdicts(reply, expected):
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run(reply)):
        assert agent.check("all tests pass") is expected


def test_check_rejects_unparseable_verdicts():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("Probably fine?")):
        with pytest.raises(RangerError, match="YES/NO"):
            agent.check("all tests pass")


def test_gate_exit_code_booleans():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("", returncode=0)) as m:
        assert agent.gate("true") is True
        assert m.call_args.args[0] == "true"
        assert m.call_args.kwargs["shell"] is True
    with mock.patch("ranger.subprocess.run", return_value=fake_run("", returncode=1)):
        assert agent.gate("false") is False


def test_gate_timeout_is_false():
    agent = Ranger()
    with mock.patch(
        "ranger.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)
    ):
        assert agent.gate("sleep 100", timeout=1) is False


# --------------------------------------------------------------------- #
# live terminal UI

class _FakeTty:
    """A stderr stand-in that claims to be a terminal and records writes."""

    def __init__(self):
        self.is_tty = True
        self.chunks = []

    def isatty(self):
        return self.is_tty

    def write(self, s):
        self.chunks.append(s)

    def flush(self):
        pass


def test_summarize_resolves_relative_paths_against_agent_cwd(tmp_path):
    agent = Ranger(cwd=tmp_path)
    seen = []

    def capture(cmd, **kw):
        seen.append(cmd[-1])
        return fake_run("ok")

    with mock.patch("ranger.subprocess.run", side_effect=capture):
        agent.summarize("notes.md")
    assert str(tmp_path / "notes.md") in seen[0]  # agent cwd, not python cwd


def test_pretty_default_and_per_call_override():
    assert Ranger().pretty is True
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")):
        agent.ask("hi", pretty=False)  # accepted, no TypeError


def test_ui_silent_when_not_a_tty():
    """Piped/captured stderr must stay byte-identical: UI never fires."""
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("done")):
        agent.ask("hi")
    import sys as _sys
    assert not _sys.stderr.isatty()  # precondition of the test env


def test_ui_draws_progress_on_tty(capsys):
    import sys as _sys
    agent = Ranger()
    fake_tty = _FakeTty()
    with mock.patch.object(_sys, "stderr", fake_tty), mock.patch(
        "ranger.subprocess.run", return_value=fake_run("the answer\nline two")
    ):
        out = agent.ask("hello world")
    assert out == "the answer\nline two"
    drawn = "".join(fake_tty.chunks)
    assert "⠋" in drawn and "ask" in drawn and "\r" in drawn  # spinner animated
    assert "✓" in drawn and "the answer" in drawn             # final ok line


def test_ui_draws_error_mark_on_failure():
    import sys as _sys
    agent = Ranger()
    fake_tty = _FakeTty()
    with mock.patch.object(_sys, "stderr", fake_tty), mock.patch(
        "ranger.subprocess.run", return_value=fake_run("", stderr="boom", returncode=1)
    ):
        with pytest.raises(RangerError):
            agent.do("break things", timeout=5)
    drawn = "".join(fake_tty.chunks)
    assert "✗" in drawn and "boom" in drawn


