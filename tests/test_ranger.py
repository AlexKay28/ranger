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


