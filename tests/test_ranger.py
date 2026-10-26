"""ranger unit tests — pinned behavior of the shipped API.

All subprocess calls are mocked: no live opencode runs, safe to run anywhere.

Contract (cycle 2 of the growth loop): >=12 tests, exit 0, no changes to
ranger/__init__.py, no network, no real agent calls.
"""

import os
import re
import signal
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


def fake_popen(returncode=0, pid=4321, communicate=None):
    """Build a mock Popen for gate() (its own subprocess seam)."""
    p = mock.Mock()
    p.pid = pid
    p.returncode = returncode
    p.communicate = (mock.Mock(side_effect=communicate) if communicate
                      else mock.Mock(return_value=("", "")))
    return p


# --------------------------------------------------------------------- #
# interruption hygiene: a leaked spinner thread ticks forever in
# notebooks — every exit path must retire it

class _TTYStderr:
    """stderr stand-in that looks like a TTY so the live UI activates."""

    def write(self, s):
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return True


def test_interrupt_stops_the_spinner():
    with mock.patch("ranger.subprocess.run",
                    side_effect=KeyboardInterrupt), \
         mock.patch("sys.stderr", _TTYStderr()), \
         mock.patch("ranger._Spinner") as spinner_cls:
        agent = Ranger()
        with pytest.raises(KeyboardInterrupt):
            agent.ask("x")
    spinner_cls.return_value.stop.assert_called()  # retired, never leaks


def test_error_path_stops_the_spinner():
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run("", stderr="boom",
                                          returncode=3)), \
         mock.patch("sys.stderr", _TTYStderr()), \
         mock.patch("ranger._Spinner") as spinner_cls:
        agent = Ranger()
        with pytest.raises(RangerError):
            agent.ask("x")
    spinner_cls.return_value.stop.assert_called()


def test_success_path_stops_the_spinner():
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run("done")), \
         mock.patch("sys.stderr", _TTYStderr()), \
         mock.patch("ranger._Spinner") as spinner_cls:
        assert Ranger().ask("x") == "done"
    spinner_cls.return_value.stop.assert_called()


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
        if "Edit exactly this existing file" in cmd[-1]:
            target.write_text("after")
            stamp = target.stat().st_mtime_ns
            os.utime(target, ns=(stamp, stamp + 1))
        return fake_run("ok")

    with mock.patch("ranger.subprocess.run", side_effect=capture):
        agent.summarize(target)
        assert agent.read("notes.md", "What is the heading?", timeout=42) == "ok"
        agent.do("rename the files")
        target.write_text("before")
        agent.edit(target, "replace the text")
        agent.search("where is config parsed")
        assert agent.trace("parse_config", timeout=42) == "ok"
        assert agent.test(timeout=42) == "ok"
        assert agent.lint(timeout=42) == "ok"
        assert agent.diagnose("ValueError: bad token", timeout=42) == "ok"
        assert agent.critique("src/parser.py", timeout=42) == "ok"

    assert str(target.resolve()) in prompts[0]
    assert str(target.resolve()) in prompts[1]
    assert "What is the heading?" in prompts[1]
    assert "do NOT modify" in prompts[1]
    assert "rename the files" in prompts[2]
    assert str(target.resolve()) in prompts[3]
    assert "replace the text" in prompts[3]
    assert "only that file" in prompts[3]
    assert "where is config parsed" in prompts[4]
    assert "No code changes" in prompts[4]
    assert "parse_config" in prompts[5]
    assert "definition, callers" in prompts[5]
    assert "data-flow" in prompts[5]
    assert "file:line" in prompts[5]
    assert "do NOT modify" in prompts[5]
    assert "test suite" in prompts[6]
    assert "do NOT modify" in prompts[6]
    assert "root cause" in prompts[6]
    assert "lint and format checks" in prompts[7]
    assert "do NOT modify" in prompts[7]
    assert "minimal remediation" in prompts[7]
    assert "ValueError: bad token" in prompts[8]
    assert "do NOT modify" in prompts[8]
    assert "root cause" in prompts[8]
    assert "minimal fix direction" in prompts[8]
    assert "src/parser.py" in prompts[9]
    assert "do NOT modify" in prompts[9]
    assert "security" in prompts[9]
    assert "missing tests" in prompts[9]


def test_test_returns_harness_diagnosis_and_forwards_overrides():
    agent = Ranger(stats=True)
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run(
                        '{"sessionID":"ses_test","part":{"type":"text",'
                        '"text":"parser test fails: bad token"}}')) as m:
        assert agent.test(model="fast/model", timeout=42) == "parser test fails: bad token"
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "test"


def test_lint_is_pure_and_forwards_overrides():
    agent = Ranger(stats=True, session="ses_hist")
    agent.context = [{"role": "user", "content": "previous answer"}]
    payload = ('{"sessionID":"ses_lint","part":{"type":"text",'
               '"text":"ruff reports an unused import."}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        assert agent.lint(model="fast/model", timeout=42) == "ruff reports an unused import."
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert "lint and format checks" in prompt
    assert "do NOT modify" in prompt
    assert "Previous interaction" not in prompt
    assert "ses_hist" not in cmd
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "lint"


def test_trace_is_pure_and_forwards_overrides():
    agent = Ranger(stats=True, session="ses_hist")
    agent.context = [{"role": "user", "content": "previous answer"}]
    payload = ('{"sessionID":"ses_trace","part":{"type":"text",'
               '"text":"src/parser.py:12 defines parse_config."}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        assert agent.trace("parse_config", model="fast/model", timeout=42) == (
            "src/parser.py:12 defines parse_config."
        )
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert "parse_config" in prompt
    assert "definition, callers" in prompt
    assert "data-flow" in prompt
    assert "file:line" in prompt
    assert "do NOT modify" in prompt
    assert "Previous interaction" not in prompt
    assert "ses_hist" not in cmd
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "trace"


def test_diagnose_is_pure_and_forwards_overrides():
    agent = Ranger(stats=True, session="ses_hist")
    agent.context = [{"role": "user", "content": "previous answer"}]
    payload = ('{"sessionID":"ses_diagnose","part":{"type":"text",'
               '"text":"The parser rejects an empty token."}}')
    error = "Traceback (most recent call last):\nValueError: bad token"
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        assert agent.diagnose(error, model="fast/model", timeout=42) == (
            "The parser rejects an empty token."
        )
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert error in prompt
    assert "do NOT modify" in prompt
    assert "evidence-backed" in prompt
    assert "root cause" in prompt
    assert "Previous interaction" not in prompt
    assert "ses_hist" not in cmd
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "diagnose"


def test_critique_is_pure_and_forwards_overrides():
    agent = Ranger(stats=True, session="ses_hist")
    agent.context = [{"role": "user", "content": "previous answer"}]
    payload = ('{"sessionID":"ses_critique","part":{"type":"text",'
               '"text":"Missing a boundary test."}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        assert agent.critique("src/parser.py", model="fast/model", timeout=42) == (
            "Missing a boundary test."
        )
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert "src/parser.py" in prompt
    assert "bugs, risks, security issues, and missing tests" in prompt
    assert "do NOT modify" in prompt
    assert "Previous interaction" not in prompt
    assert "ses_hist" not in cmd
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "critique"


def test_read_answers_one_file_question_and_forwards_overrides(tmp_path):
    agent = Ranger(cwd=tmp_path, stats=True, session="ses_hist")
    agent.context = [{"role": "user", "content": "previous answer"}]
    payload = ('{"sessionID":"ses_read","part":{"type":"text",'
               '"text":"It accepts strings."}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        assert agent.read("parser.py", "What inputs does it accept?",
                          model="fast/model", timeout=42) == "It accepts strings."
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert str(tmp_path / "parser.py") in prompt
    assert "What inputs does it accept?" in prompt
    assert "do NOT modify" in prompt
    assert "Previous interaction" not in prompt
    assert "ses_hist" not in cmd
    assert cmd[cmd.index("--model") + 1] == "fast/model"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last["label"] == "read"


def test_edit_requires_a_changed_target_and_forwards_overrides(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("before")
    agent = Ranger(cwd=tmp_path)

    def edit_target(cmd, **kw):
        assert "Edit exactly this existing file" in cmd[-1]
        target.write_text("after")
        stamp = target.stat().st_mtime_ns
        os.utime(target, ns=(stamp, stamp + 1))
        return fake_run("changed it")

    with mock.patch("ranger.subprocess.run", side_effect=edit_target) as m:
        assert agent.edit("notes.md", "replace the text", timeout=42) == "changed it"
    assert m.call_args.kwargs["timeout"] == 42
    assert agent.last == {}
    with mock.patch("ranger.subprocess.run", return_value=fake_run("claimed")):
        with pytest.raises(RangerError, match="did not modify"):
            agent.edit(target, "do nothing")
    with pytest.raises(RangerError, match="does not exist"):
        agent.edit("missing.md", "make one")


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
        digest = agent.context_summarize()
    assert digest == "digest"
    # history truly untouched: only the ask exchange is recorded — the
    # transcript-bearing digest request is never nested back in
    assert len(agent.context) == 2
    assert all(m["role"] in ("user", "assistant") for m in agent.context)
    # and repeated summarization cannot recursively duplicate history
    with mock.patch("ranger.subprocess.run", return_value=fake_run("digest2")):
        agent.context_summarize()
    assert len(agent.context) == 2


def test_gate_never_records_context():
    agent = Ranger()
    with mock.patch("ranger.subprocess.Popen",
                    return_value=fake_popen(returncode=0)):
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
    with mock.patch("ranger.subprocess.Popen",
                    return_value=fake_popen(returncode=0)) as m:
        assert agent.gate("true") is True
        assert m.call_args.args[0] == "true"
        assert m.call_args.kwargs["shell"] is True
    with mock.patch("ranger.subprocess.Popen",
                    return_value=fake_popen(returncode=1)):
        assert agent.gate("false") is False


# --------------------------------------------------------------------- #
# mode / effort / stats / until

def test_mode_selects_opencode_agent():
    agent = Ranger(mode="build")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--agent") + 1] == "build"
    # legacy agent= alias still works; mode wins on conflict
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi", agent="plan")
    assert m.call_args.args[0][m.call_args.args[0].index("--agent") + 1] == "plan"


def test_effort_validation_and_directives():
    with pytest.raises(ValueError):
        Ranger(effort="turbo")
    agent = Ranger(effort="high")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert "--thinking" in cmd  # high effort forces thinking
    assert "verify" in cmd[-1].lower()
    agent2 = Ranger(effort="low")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent2.ask("hi")
    assert "--thinking" not in m.call_args.args[0]
    assert "be brief" in m.call_args.args[0][-1]
    # explicit per-call override
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent2.ask("hi", effort="medium")
    assert "be brief" not in m.call_args.args[0][-1]


def test_stats_json_mode_and_telemetry():
    agent = Ranger(stats=True)
    payload = (
        '{"type":"text","sessionID":"ses_abc","part":{"type":"text","text":"first ","time":{"start":1000,"end":2500}}}\n'
        '{"type":"text","sessionID":"ses_abc","part":{"type":"text","text":"second","time":{"start":2500,"end":4000}}}\n'
        'not json noise\n'
    )
    with mock.patch("ranger.subprocess.run", return_value=fake_run(payload)) as m:
        out = agent.ask("hi")
    assert out == "first \nsecond"
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--format") + 1] == "json"
    assert agent.last["session"] == "ses_abc"
    assert agent.last["model_s"] == 3.0
    assert agent.last["parts"] == 2
    assert agent.last["wall_s"] >= 0
    assert agent.last["label"] == "ask"


def test_stats_off_by_default():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("plain text")):
        assert agent.ask("hi") == "plain text"
    assert agent.last == {}


def test_until_loop_untils_gate_passes():
    agent = Ranger()
    # first False = the vacuous-gate pre-check (red = real work needed),
    # then two red gates, then green on the third work iteration
    results = iter([False, False, False, True])
    with mock.patch.object(Ranger, "gate", side_effect=lambda cmd, **kw: next(results)), \
         mock.patch.object(Ranger, "ask", side_effect=lambda p, **kw: "a step"), \
         mock.patch.object(Ranger, "do", side_effect=lambda p, **kw: f"did {p}"):
        outcome = agent.until("make tests green", max_iter=5,
                              gate_cmd="python -m pytest -q")
    assert outcome["achieved"] is True
    assert outcome["iterations"] == 3
    assert outcome["steps"] == ["a step"] * 3


def test_until_exhausts_honestly():
    agent = Ranger()
    with mock.patch.object(Ranger, "check", side_effect=lambda cond, **ov: False), \
         mock.patch.object(Ranger, "ask", side_effect=lambda p, **kw: "step"), \
         mock.patch.object(Ranger, "do", side_effect=lambda p, **kw: "nope"):
        outcome = agent.until("impossible goal", max_iter=2)
    assert outcome == {"achieved": False, "iterations": 2,
                       "steps": ["step", "step"], "report": "nope",
                       "last_gate": {"kind": "check", "ok": False,
                                     "output": ""}}



def test_gate_timeout_is_false_and_kills_the_group():
    agent = Ranger()
    p = fake_popen(pid=777, communicate=[
        subprocess.TimeoutExpired(cmd="x", timeout=5), ("", "")])
    with mock.patch("ranger.subprocess.Popen", return_value=p), \
         mock.patch("ranger.os.killpg") as kg:
        assert agent.gate("sleep 100", timeout=1) is False
    kg.assert_called_once_with(777, signal.SIGKILL)  # whole pg, not the shell


def test_gate_interrupt_kills_group_and_reraises():
    agent = Ranger()
    p = fake_popen(pid=778, communicate=KeyboardInterrupt)
    with mock.patch("ranger.subprocess.Popen", return_value=p), \
         mock.patch("ranger.os.killpg") as kg:
        with pytest.raises(KeyboardInterrupt):
            agent.gate("sleep 100")
    kg.assert_called_once_with(778, signal.SIGKILL)


def test_until_interrupt_preserves_partial_steps():
    agent = Ranger()
    with mock.patch.object(Ranger, "ask",
                           side_effect=["step 1", KeyboardInterrupt]), \
         mock.patch.object(Ranger, "do",
                           side_effect=lambda p, **kw: f"did {p}"), \
         mock.patch.object(Ranger, "check", return_value=False):
        with pytest.raises(KeyboardInterrupt) as ei:
            agent.until("goal", max_iter=3)   # check-gate keeps the loop alive
    msg = str(ei.value)
    # cancelled honestly — but the paid-for progress survives in the note
    assert "step 1" in msg and "achieved" in msg


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



# --------------------------------------------------------------------- #
# harness backends (adapters)

CODEX_JSONL = (
    '{"type":"thread.started","thread_id":"th_123"}\n'
    "not json at all\n"
    '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"ok"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":1,'
    '"cached_input_tokens":0,"output_tokens":5}}\n'
)


def test_codex_command_construction():
    agent = Ranger(backend="codex", model="gpt-5.1-codex", cwd="/tmp/demo")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        assert agent.ask("hi") == "ok"
    cmd = m.call_args.args[0]
    assert cmd[0] == "codex" and cmd[1] == "exec"
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5.1-codex"
    assert cmd[cmd.index("-C") + 1] == "/tmp/demo"      # native cd flag
    assert "--approve-for-me" in cmd                   # auto=True autonomy
    assert cmd[-1] == "hi"                               # prompt last
    # codex always answers in JSON; ranger never guesses raw stdout
    assert "--json" in cmd


def test_codex_no_model_means_config_default(monkeypatch):
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    agent = Ranger(backend="codex")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert "-m" not in cmd  # codex picks its config.toml default
    # auto=False pins a read-only sandbox (exec cannot be interactive)
    agent_ro = Ranger(backend="codex", auto=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent_ro.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("-s") + 1] == "read-only"


def test_codex_session_resume_shape():
    agent = Ranger(backend="codex", session="th_123")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[2] == "resume" and cmd[4] == "th_123"  # exec resume <id>


def test_codex_rejects_opencode_only_options():
    for kw in ({"mode": "build"}, {"agent": "build"}, {"title": "t"}):
        with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)):
            with pytest.raises(RangerError, match="codex.*does not support"):
                Ranger(backend="codex").ask("hi", **kw)


def test_codex_effort_and_thinking_map_to_reasoning():
    agent = Ranger(backend="codex", effort="high")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent.ask("x")
    cmd = m.call_args.args[0]
    assert 'model_reasoning_effort="high"' in cmd  # effort -> reasoning config
    agent_lo = Ranger(backend="codex", effort="low")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent_lo.ask("x")
    assert 'model_reasoning_effort="low"' in m.call_args.args[0]


def test_codex_stats_reports_real_tokens():
    agent = Ranger(backend="codex", stats=True)
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)):
        agent.ask("hi")
    assert agent.last["session"] == "th_123"
    assert agent.last["parts"] == 1 and agent.last["chars"] == 2
    assert agent.last["input_tokens"] == 1
    assert agent.last["output_tokens"] == 5


def test_codex_skills_are_inlined_not_flagged(tmp_path):
    skill = tmp_path / "style.md"
    skill.write_text("Answer only in haiku.")
    agent = Ranger(backend="codex", skills=[tmp_path])
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert "--file" not in cmd                      # no native attachment flag
    assert "Answer only in haiku." in cmd[-1]       # ...so the text rides inside


def test_backend_validation_everywhere():
    with pytest.raises(ValueError):
        Ranger(backend="nope")
    with pytest.raises(TypeError):  # per-call too
        with mock.patch("ranger.subprocess.run", return_value=fake_run("x")):
            Ranger().ask("hi", backend="wat")
    with pytest.raises(ValueError):
        Ranger.models(backend="wat")


def test_codex_models_listing_is_honest():
    with pytest.raises(RangerError, match="enumeration is not available"):
        Ranger.models(backend="codex")


def test_register_custom_backend_and_run_it():
    class _Mine(ranger._Backend):
        name = "mine"
        install_hint = "install mine"

        def build_cmd(self, o, full_prompt, skill_files):
            return ["mycli", "go", full_prompt], full_prompt

        def parse_output(self, stdout, want_stats):
            return stdout.strip(), None

    ranger.register_backend("mine", _Mine)
    agent = Ranger(backend="mine")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("done")) as m:
        assert agent.ask("hi") == "done"
    assert m.call_args.args[0] == ["mycli", "go", "hi"]
    assert agent.with_config(backend="mine").backend == "mine"


def test_same_commands_work_across_backends():
    """The public API must not depend on the harness underneath."""
    yes_plain = "YES the file exists"
    yes_jsonl = CODEX_JSONL.replace('"text":"ok"', f'"text":"{yes_plain}"')
    for backend, stdout in (("opencode", yes_plain), ("codex", yes_jsonl)):
        agent = Ranger(backend=backend, cwd="/tmp/demo")
        with mock.patch("ranger.subprocess.run", return_value=fake_run(stdout)):
            assert agent.check("the file exists") is True
        agent.context_clear()
    # and the YES/NO contract stays strict on both: unparseable raises
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)):
        with pytest.raises(RangerError):
            Ranger(backend="codex").check("file exists")


def test_check_accepts_verdict_line_after_chatter():
    """Some harnesses chat before the verdict; a YES/NO-only line still parses."""
    agent = Ranger()
    chatty = ("I'll verify the file directly.\nYES  \nEvidence: it exists.")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(chatty)):
        assert agent.check("file exists") is True
    chatty_no = ("Let me look.\nno.\nnothing found")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(chatty_no)):
        assert agent.check("file exists") is False
    # prose that merely mentions the words never parses
    with mock.patch("ranger.subprocess.run", return_value=fake_run(
            "The question of yes or no is subtle; I found no verdict.")):
        with pytest.raises(RangerError):
            agent.check("file exists")


# --------------------------------------------------------------------- #
# paradigm law: context memory colors dialogues, never facts

def test_recall_is_skipped_for_pure_commands():
    """Fact commands run history-independent; ask/do recall."""
    agent = Ranger()
    agent.context = [
        {"role": "user", "content": "we agreed the PORT is 8080"},
        {"role": "assistant", "content": "okay, 8080 it is"},
    ]
    for label, method in (("check", lambda: agent.check("port is 8080")),
                           ("critique", lambda: agent.critique("x.py")),
                           ("lint", lambda: agent.lint()),
                           ("read", lambda: agent.read("x.py", "What port is used?")),
                           ("search", lambda: agent.search("PORT usage")),
                           ("summarize", lambda: agent.summarize("x.py")),
                           ("trace", lambda: agent.trace("serve"))):
        with mock.patch("ranger.subprocess.run",
                        return_value=fake_run("YES")) as m:
            method()
        assert "Previous interaction" not in m.call_args.args[0][-1], (
            f"{label} must not see conversation history"
        )
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("what port did we agree on?")
    assert "Previous interaction" in m.call_args.args[0][-1]  # dialogue recalls


# --------------------------------------------------------------------- #
# critic round fixes (gpt-6.1-sol adversarial review)

def test_prompts_travel_after_option_terminator():
    """Task text is data, never flags: `--` guards the prompt on every backend."""
    for backend in ("opencode", "codex"):
        stdout = CODEX_JSONL if backend == "codex" else "ok"
        agent = Ranger(backend=backend, cwd="/tmp/demo")
        with mock.patch("ranger.subprocess.run", return_value=fake_run(stdout)) as m:
            agent.ask("--help")
        cmd = m.call_args.args[0]
        assert cmd[-1] == "--help"
        assert cmd[-2] == "--", f"{backend}: no option terminator before prompt"


def test_pure_commands_drop_harness_session(monkeypatch):
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    agent = Ranger(cwd="/tmp/demo", session="ses_hist")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("flow")) as m:
        agent.ask("hi")  # dialogue keeps the session
    assert "ses_hist" in m.call_args.args[0]
    with mock.patch("ranger.subprocess.run", return_value=fake_run("YES")) as m:
        agent.check("x exists")  # fact commands drop it
    assert "ses_hist" not in m.call_args.args[0]


def test_codex_resume_applies_model_and_readonly(monkeypatch):
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    agent = Ranger(backend="codex", session="th_1", model="gpt-5.1-codex",
                   auto=False, cwd="/tmp/demo")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[2] == "resume" and "th_1" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5.1-codex"     # model still applies
    assert 'sandbox_mode="read-only"' in " ".join(cmd)    # policy still enforced
    assert "-C" not in cmd                                # resume takes no -C


def test_backend_switch_does_not_inherit_wrong_default(monkeypatch):
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    # opencode-default agent, per-call switch to codex: no -m foisted
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        Ranger().ask("hi", backend="codex")
    assert "-m" not in m.call_args.args[0]
    assert DEFAULT_MODEL not in m.call_args.args[0]
    # codex-default agent, per-call switch to opencode: package default fills in
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(backend="codex").ask("hi", backend="opencode")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == DEFAULT_MODEL
    # explicit ctor model still wins after a backend switch
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSONL)) as m:
        Ranger(model="custom/m").ask("hi", backend="codex")
    assert m.call_args.args[0][m.call_args.args[0].index("-m") + 1] == "custom/m"


def test_with_config_copies_mutable_state():
    base = Ranger()
    clones = [base.with_config(model=f"m{i}") for i in range(2)]
    for c in clones:
        c.context.append({"role": "user", "content": "hi"})
    assert base.context == []                        # original untouched
    assert clones[0].context is not clones[1].context  # no shared list
    # with_config(model=...) is the copy's EXPLICIT choice — per-run
    # resolution must not resurrect the base agent's model
    copy = base.with_config(model="fast/model")
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        copy.ask("hi")
    cmd = m.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "fast/model"


def test_check_rejects_contradictory_and_unconfident():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run",
                   return_value=fake_run("I checked:\nYES\nNO")):
        with pytest.raises(RangerError, match="contradictory"):
            agent.check("x")
    with mock.patch("ranger.subprocess.run",
                   return_value=fake_run("NO verification was performed; I cannot answer.")):
        with pytest.raises(RangerError):
            agent.check("x")


def test_write_slug_is_sanitized_and_collision_proof(tmp_path):
    agent = Ranger(cwd=tmp_path)

    def fake_exec(cmd, **kw):
        # extract the CURRENT target ("at exactly: <path>") from the frozen
        # prompt; recall (write is a dialogue command) may embed earlier
        # targets too, so always take the LAST match
        found = re.findall(r"at exactly: (\S+)", cmd[-1])
        if found:
            Path(found[-1]).write_text("x")   # agent honors the contract
        return fake_run("claimed")

    with mock.patch("ranger.subprocess.run", side_effect=fake_exec):
        agent.write("describe src/parser.py")
        agent.write("describe src/parser.py")
        agent.write("two  tasks!!! with /slashes/")
    outs = [p.name for p in tmp_path.glob("ranger_describe_src_parser_py*")]
    assert len(outs) >= 2, "repeated tasks must never collide on one path"
    for name in (p.name for p in tmp_path.glob("ranger_*")):
        assert "/" not in name and ".." not in name  # safe direct children


def test_write_rejects_directory_as_output(tmp_path):
    agent = Ranger(cwd=tmp_path)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("claimed")):
        with pytest.raises(RangerError, match="did not write"):
            agent.write("report", path=".")  # a directory is not a document


def test_until_validates_max_iter():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")):
        for bad in (-1, "three", 2.5):
            with pytest.raises(ValueError):
                agent.until("goal", max_iter=bad, gate_cmd="true")
        # zero is a valid, immediately-honest no-iteration result; with a
        # green gate the vacuous case is reported as already_green, not
        # as a fake exhausted failure
        res = agent.until("goal", max_iter=0, gate_cmd="true")
        assert res == {"achieved": True, "iterations": 0, "steps": [],
                       "report": "", "already_green": True,
                       "last_gate": {"kind": "gate_cmd", "ok": True,
                                     "output": ""}}


def test_registered_backends_listing():
    assert "codex" in ranger.backends() and "opencode" in ranger.backends()
    assert "pi" in ranger.backends() and "openhands" in ranger.backends()
    assert ranger.backends() == sorted(ranger.backends())


def test_relative_skill_paths_resolve_against_agent_cwd(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "style.md").write_text("Use haikus.")
    agent = Ranger(cwd=str(target), skills=["style.md"])
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")
    cmd = m.call_args.args[0]
    i = cmd.index("--file")
    assert Path(cmd[i + 1]).is_absolute()          # harness gets absolute
    assert cmd[i + 1] == str(target / "style.md")  # resolved in AGENT cwd


def test_memory_budget_per_call_override():
    agent = Ranger()
    agent.context = [
        {"role": "user", "content": "u" * 9000},
        {"role": "assistant", "content": "a" * 9000},
    ]
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi")  # default 20k budget: both messages recalled
    joined = m.call_args.args[0][-1]
    assert "u" * 9000 in joined and "a" * 9000 in joined
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        agent.ask("hi", memory_budget=100)  # tiny budget: almost nothing fits
    joined = m.call_args.args[0][-1]
    assert "u" * 9000 not in joined and "a" * 9000 not in joined


# --------------------------------------------------------------------- #
# multi-agent interactions (v0.6) — frozen contracts, mocked calls

def _review_answer(verdict="APPROVE", findings="all verified",
                   changes="none"):
    return (f"VERDICT: {verdict}\nFINDINGS: {findings}\n"
            f"CHANGES: {changes}")


def test_review_parses_verdicts_mechanically():
    builder, critic = Ranger(cwd="/tmp/demo"), Ranger(cwd="/tmp/demo")
    builder.context.append({"role": "assistant", "content": "I added tests."})
    for verdict, passed in (("APPROVE", True), ("REJECT", False),
                            ("REQUEST_CHANGES", False)):
        with mock.patch("ranger.subprocess.run",
                        return_value=fake_run(_review_answer(verdict))):
            rev = critic.review("the tests exist", author=builder)
        assert rev == {"passed": passed, "verdict": verdict,
                       "findings": "all verified", "changes": "none"}
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run("looks good to me!")):
        with pytest.raises(RangerError, match="VERDICT"):
            critic.review("x", author=builder)


def test_review_is_memory_and_session_free():
    critic = Ranger(session="ses_bias")
    critic.context = [{"role": "user", "content": "we agreed it's fine"},
                      {"role": "assistant", "content": "sure, fine"}]
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run(_review_answer())) as m:
        critic.review("the thing")
    cmd = m.call_args.args[0]
    prompt = cmd[-1]
    assert "Previous interaction" not in prompt  # not colored by own chat
    assert "ses_bias" not in cmd                  # nor resumed from a session
    assert "we agreed it's fine" not in prompt


def test_review_injects_author_claims_as_unverified():
    builder = Ranger()
    builder.context.append({"role": "assistant", "content": "all tests pass"})
    critic = Ranger()
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run(_review_answer())) as m:
        critic.review("suite health", author=builder)
    prompt = m.call_args.args[0][-1]
    assert "all tests pass" in prompt
    assert "NOT verified" in prompt  # claims labeled, trust nothing
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run(_review_answer())):
        critic.review("x", author="plain string claims")  # bare string ok
        with pytest.raises(RangerError, match="no recorded claim"):
            Ranger().review("x", author=Ranger())  # silent author rejected


def test_challenge_attacks_defends_and_rules():
    attacker, defender = Ranger(), Ranger()
    defender.context.append({"role": "assistant",
                             "content": "the parser handles every case"})
    replies = iter([
        "ATTACK: no test for empty input exists",     # attack
        "Fixed — added tests\nDEFENDED",              # defense
        "RULING: WITHDRAWN",                           # ruling round 1
        "ATTACK: benchmark numbers are hearsay",       # round 2 attack
        "Here are the numbers\nDEFENDED",              # defense
        "RULING: SUSTAINED",                           # sustained -> survives no
    ])
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda *a, **k: fake_run(next(replies))):
        duel = attacker.challenge(defender, rounds=2)
    assert duel["survived"] is False
    assert [r["ruling"] for r in duel["rounds"]] == ["WITHDRAWN", "SUSTAINED"]
    assert len(duel["rounds"]) == 2  # immediate stop after SUSTAINED? no: last
    # budgets: all withdrawn -> survived True
    replies2 = iter(["ATTACK: a", "DEFENDED", "RULING: WITHDRAWN"] * 3)
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda *a, **k: fake_run(next(replies2))):
        ok = attacker.challenge(defender, rounds=2)
    assert ok["survived"] is True and len(ok["rounds"]) == 2
    # concession ends it immediately
    replies3 = iter(["ATTACK: a", "you got me.\nCONCEDED"])
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda *a, **k: fake_run(next(replies3))):
        lost = attacker.challenge(defender, rounds=2)
    assert lost["survived"] is False and len(lost["rounds"]) == 1
    with pytest.raises(ValueError):  # bad budget
        attacker.challenge(defender, rounds=-1)


def test_second_opinion_compares_normatively():
    a, b = Ranger(), Ranger()
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("The\nanswer  is 42"), fake_run("the answer is 42"),
    ]):
        same = a.second_opinion(b, "the question")
    assert same["differs"] is False  # whitespace/case differences don't count
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("42"), fake_run("43"),
    ]):
        diff = a.second_opinion(b, "the question")
    assert diff["differs"] is True


def test_refine_with_gates_on_mechanical_approve():
    builder, critic = Ranger(cwd="/tmp/demo"), Ranger(cwd="/tmp/demo")
    replies = iter([
        fake_run("worked"),                      # do #1
        fake_run(_review_answer("REQUEST_CHANGES",
                                findings="f", changes="add empty-input test")),
        fake_run("worked again"),                 # do #2
        fake_run(_review_answer("APPROVE")),      # approved
    ])
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda *a, **k: next(replies)):
        out = builder.refine_with(critic, "add input tests", max_iter=3)
    assert out["approved"] is True and out["iterations"] == 2
    assert out["reviews"][0]["changes"] == "add empty-input test"
    # budget exhaustion is honest: never approved without APPROVE
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("w"), fake_run(_review_answer("REQUEST_CHANGES", changes="c")),
        fake_run("w"), fake_run(_review_answer("REQUEST_CHANGES", changes="c")),
    ]):
        out2 = builder.refine_with(critic, "goal", max_iter=2)
    assert out2["approved"] is False and out2["iterations"] == 2
    with pytest.raises(TypeError):  # critic must be a Ranger
        builder.refine_with("not an agent", "goal")
    with pytest.raises(ValueError):
        builder.refine_with(critic, "goal", max_iter=-1)


def test_debate_exchanges_and_judges():
    a, b, judge = Ranger(), Ranger(), Ranger()
    replies = iter([fake_run("pos-A"), fake_run("pos-B"), fake_run("pos-A2"),
                    fake_run("pos-B2"), fake_run("digest here")])
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda *a2, **k: next(replies)):
        talk = ranger.debate(a, b, "the topic", rounds=2, judge=judge)
    assert [t["round"] for t in talk["transcript"]] == [1, 2]
    assert talk["digest"] == "digest here" and judge.context == []
    # each side sees the opponent's labeled position
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("standing firm"), fake_run("opposing"),
    ]) as m:
        ranger.debate(a, b, "topic", rounds=1)
    assert "standing firm" in m.call_args_list[-1].args[0][-1]
    with pytest.raises(ValueError):
        ranger.debate(a, b, "topic", rounds=1.5)
    with pytest.raises(TypeError):
        ranger.debate(a, "b", "topic")
