"""Logic/correctness tests — the agent must return the RIGHT answer.

The other suites pin contracts ("doesn't crash", "argv shape"). This one
pins VALUES: verdict parsing, precedence chains, budget arithmetic, flow
outcomes. Truth-table style, fully mocked, deterministic.

Budget rule (a commitment, enforced below): the whole suite finishes in
well under one minute.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError, DEFAULT_MODEL

REPO = Path(__file__).resolve().parent.parent


def fake_run(stdout="", stderr="", returncode=0):
    ret = mock.Mock()
    ret.stdout, ret.stderr, ret.returncode = stdout, stderr, returncode
    return ret


def fake_popen(returncode=0, pid=4321, communicate=None):
    """Build a mock Popen for gate() (its own subprocess seam)."""
    p = mock.Mock()
    p.pid = pid
    p.returncode = returncode
    p.communicate = (mock.Mock(side_effect=communicate) if communicate
                      else mock.Mock(return_value=("", "")))
    return p


# ==================================================================== #
# 1. check(): the verdict grammar is a truth table, not a vibe

@pytest.mark.parametrize("answer,expected", [
    ("YES", True), ("yes.", True), ("Yes, verified on disk", True),
    ("NO", False), ("no,", False), ("No such file exists", False),
    ("chatter first\nYES\nmore text", True),        # standalone line fallback
    ("some prose\nNO.", False),
    ("I'll check.\nYES  \nEvidence: exists", True),
    ("The question of yes or no is unclear", RangerError),   # prose — raise
    ("", RangerError), ("maybe so", RangerError),
    ("NO verification was performed; cannot answer", RangerError),  # unsure
    ("YES but I am unable to confirm", RangerError),
    ("I checked:\nYES\nNO", RangerError),           # contradiction
    ("hmm\nNO\nYES\n", RangerError),
])
def test_check_truth_table(answer, expected):
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run(answer)):
        if expected is RangerError:
            with pytest.raises(RangerError):
                agent.check("cond")
        else:
            assert agent.check("cond") is expected


# ==================================================================== #
# 2. model resolution: every precedence path, exact expected outcome

def _model_of(cmd):
    for flag in ("--model", "-m"):
        if flag in cmd:
            return cmd[cmd.index(flag) + 1]
    return None


def test_model_precedence_matrix(monkeypatch):
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    # constructor explicit beats env and default
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "env/m"}), \
         mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(model="ctor/m").ask("x")
    assert _model_of(m.call_args.args[0]) == "ctor/m"
    # env fills when constructor silent
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "env/m"}), \
         mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger().ask("x")
    assert _model_of(m.call_args.args[0]) == "env/m"
    # per-call beats everything
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "env/m"}), \
         mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(model="ctor/m").ask("x", model="call/m")
    assert _model_of(m.call_args.args[0]) == "call/m"
    # package default last resort (opencode), none for codex
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger().ask("x")
    assert _model_of(m.call_args.args[0]) == DEFAULT_MODEL
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run('{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}')) as m:
        Ranger(backend="codex").ask("x")
    assert "-m" not in m.call_args.args[0]
    # backend switch in either direction gets the RIGHT default
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger().ask("x", backend="codex")          # openrouter id NOT passed
    assert "-m" not in m.call_args.args[0] and DEFAULT_MODEL not in m.call_args.args[0]
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(backend="codex").ask("x", backend="opencode")   # default fills in
    assert _model_of(m.call_args.args[0]) == DEFAULT_MODEL
    # with_config keeps its explicit choice (marker travels)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(model="a/m").with_config(model="b/m").ask("x")
    assert _model_of(m.call_args.args[0]) == "b/m"
    with mock.patch("ranger.subprocess.run", return_value=fake_run("ok")) as m:
        Ranger(model="a/m").with_config(backend="codex").ask("x")
    assert _model_of(m.call_args.args[0]) == "a/m"   # explicit survives switch


@pytest.fixture
def default_model_warning_reset(monkeypatch):
    """Reset the once-per-process guard so test order does not matter."""
    monkeypatch.setattr(ranger, "_DEFAULT_MODEL_WARNED", False)


def _default_warnings(caplog):
    return [r for r in caplog.records
            if r.name == "ranger" and r.levelno >= logging.WARNING
            and "DEFAULT_MODEL" in r.getMessage()]


def test_default_model_warning_truth_table(caplog, monkeypatch,
                                           default_model_warning_reset):
    """One-time DEFAULT_MODEL staleness warning, per resolution path."""
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    run = "ranger.subprocess.run"
    caplog.set_level(logging.WARNING, logger="ranger")

    # (1) default resolution -> exactly one warning, right content
    with mock.patch(run, return_value=fake_run("ok")):
        Ranger().ask("x")
    recs = _default_warnings(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert DEFAULT_MODEL in msg and "RANGER_MODEL" in msg and "model=" in msg

    # (4) a second default-resolution call -> no duplicate (once/process)
    caplog.clear()
    with mock.patch(run, return_value=fake_run("ok")):
        Ranger().ask("x")
    assert not _default_warnings(caplog)

    # (2) explicit model= (ctor) -> no warning
    caplog.clear()
    with mock.patch(run, return_value=fake_run("ok")):
        Ranger(model="explicit/m").ask("x")
    assert not _default_warnings(caplog)

    # (2b) explicit per-call model= -> no warning
    caplog.clear()
    with mock.patch(run, return_value=fake_run("ok")):
        Ranger().ask("x", model="call/m")
    assert not _default_warnings(caplog)

    # (3) RANGER_MODEL env set -> no warning
    caplog.clear()
    with mock.patch.dict(os.environ, {"RANGER_MODEL": "env/m"}), \
         mock.patch(run, return_value=fake_run("ok")):
        Ranger().ask("x")
    assert not _default_warnings(caplog)

    # (5) non-opencode backend without a model -> no warning
    caplog.clear()
    codex_out = '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}'
    with mock.patch(run, return_value=fake_run(codex_out)):
        Ranger(backend="codex").ask("x")
    assert not _default_warnings(caplog)


def test_default_model_warning_once_across_both_sites(caplog, monkeypatch,
                                                      default_model_warning_reset):
    """Constructor resolution and _run resolution share one warning."""
    monkeypatch.delenv("RANGER_MODEL", raising=False)
    caplog.set_level(logging.WARNING, logger="ranger")
    run = "ranger.subprocess.run"
    # constructor site consumes the one warning…
    Ranger()
    recs = _default_warnings(caplog)
    assert len(recs) == 1
    # …so the _run site for the same default stays silent
    caplog.clear()
    with mock.patch(run, return_value=fake_run("ok")):
        Ranger().ask("x")
    assert not _default_warnings(caplog)


# ==================================================================== #
# 3. context recall: the budget is arithmetic, newest messages first

def _recall_set(budget):
    agent = Ranger()
    # oldest -> newest: 10, 20, 4000 chars
    agent.context = [
        {"role": "user", "content": "A" * 10},
        {"role": "assistant", "content": "B" * 20},
        {"role": "user", "content": "C" * 4000},
    ]
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run("ok")) as m:
        agent.ask("q", memory_budget=budget)
    return m.call_args.args[0][-1]


def test_recall_budget_arithmetic():
    # message overhead: len + 16 each -> A=26, B=36, C=4016
    # budget 4050: newest C fits (4016), adding B would hit 4052 -> cut
    p = _recall_set(4050)
    assert "C" * 4000 in p and "B" * 20 not in p and "A" * 10 not in p
    # whole history fits (4078 <= 5000)
    p = _recall_set(5000)
    assert "A" * 10 in p and "B" * 20 in p and "C" * 4000 in p
    # newest itself does not fit -> nothing recalled
    p = _recall_set(100)
    assert "C" * 4000 not in p and "## Previous interaction" not in p


def test_purity_map_for_every_command():
    """Dialogue recalls history; facts never do; reviews run free."""
    agent = Ranger()
    agent.context = [{"role": "user", "content": "HIST"}]
    plan = [
        ("ask", lambda a: a.ask("x")),
        ("do", lambda a: a.do("x")),
        ("edit", lambda a: a.edit(edit_target, "change it")),
        ("write", lambda a: a.write("x", path="f.md")),
        ("check", lambda a: a.check("x")),
        ("search", lambda a: a.search("x")),
        ("summarize", lambda a: a.summarize("x.py")),
        ("test", lambda a: a.test()),
        ("lint", lambda a: a.lint()),
        ("diagnose", lambda a: a.diagnose("ValueError: bad token")),
        ("review", lambda a: a.review("x")),
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        edit_target = Path(d) / "edit.txt"
        edit_target.write_text("before")
        for label, method in plan:
            def run(cmd, **kw):
                if label == "edit":
                    edit_target.write_text("after")
                    stamp = edit_target.stat().st_mtime_ns
                    os.utime(edit_target, ns=(stamp, stamp + 1))
                return fake_run("VERTEX:\nVERTEX")
            with mock.patch("ranger.subprocess.run", side_effect=run) as m:
                try:
                    method(agent)
                except RangerError:
                    pass  # answers here are garbage — parse may fail, fine
                prompt = m.call_args.args[0][-1]
            recalls = "HIST" in prompt
            expectations = {"ask": True, "do": True, "edit": True, "write": True,
                                "check": False, "search": False,
                                "summarize": False, "test": False, "lint": False,
                                "diagnose": False,
                                "review": False}
            assert recalls == expectations[label], (
                f"{label}: recall={recalls}, expected {expectations[label]}")
        # write needs a real target; summarize needs the cwd to exist


def test_recording_keeps_raw_prompt_and_pairing():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run",
                    side_effect=[fake_run("ans")]) as m:
        agent.ask("original prompt")
    # recorded pair: raw request + the answer — not the recall-prefixed variant
    assert agent.context == [{"role": "user", "content": "original prompt"},
                             {"role": "assistant", "content": "ans"}]
    with mock.patch("ranger.subprocess.Popen", return_value=fake_popen(0)):
        agent.gate("true")
    assert len(agent.context) == 2   # gate never records


# ==================================================================== #
# 4. write(): path + slug correctness tables

def test_write_path_resolution_table(tmp_path):
    agent = Ranger(cwd=tmp_path)
    seen = []
    def fake(cmd, **kw):
        import re as _re
        m = _re.findall(r"at exactly: (\S+)", cmd[-1])
        Path(m[-1]).write_text("x")
        return fake_run("claimed")
    with mock.patch("ranger.subprocess.run", side_effect=fake):
        # relative path arg joins the AGENT cwd
        assert agent.write("doc", path="out.md") == str(tmp_path / "out.md")
        # absolute path preserved as-is
        abs_target = tmp_path / "abs.md"
        assert agent.write("doc", path=abs_target) == str(abs_target)


def test_slug_sanitization_table(tmp_path):
    """Exercise write() itself and check the generated target's name."""
    agent = Ranger(cwd=tmp_path)
    import re as _re
    table = [
        ("Describe SRC/Parser.py", "ranger_describe_src_parser_py"),
        ("UPPER Case", "ranger_upper_case"),
        ("...", "ranger_ranger_out"),       # nothing survives -> slug fallback
        ("a/b/../escape", "ranger_a_b_escape"),
    ]
    for task, expected_prefix in table:
        def fake(cmd, **kw):
            m = _re.findall(r"at exactly: (\S+)", cmd[-1])
            Path(m[-1]).write_text("x")
            return fake_run("done")
        with mock.patch("ranger.subprocess.run", side_effect=fake):
            out = agent.write(task)
        name = Path(out).name
        assert name.startswith(expected_prefix), (name, expected_prefix)
        # and the unique-suffix part is exactly a 6-hex uuid slice
        suffix = name[:-3].rsplit("_", 1)[-1]
        assert _re.fullmatch(r"[0-9a-f]{6}", suffix), name


# ==================================================================== #
# 5. until(): loop mechanics produce exactly the promised dict

def test_until_gate_precedence_and_counting():
    agent = Ranger()
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        return fake_run("do a step" if len(calls) == 1 else "done report")
    with mock.patch("ranger.subprocess.run", side_effect=fake), \
         mock.patch("ranger.subprocess.Popen",
                    side_effect=[fake_popen(1),   # vacuous pre-check: red
                                 fake_popen(0)]):  # iteration-1 gate: green
        res = agent.until("goal", max_iter=3, gate_cmd="test -f x")
    # gate_cmd path: one ask (step) + one do per iteration; gate is shell
    assert res["achieved"] is True      # mocked gate exit 0
    assert res["iterations"] == 1
    assert res["steps"] == ["do a step"]
    assert res["report"] == "done report"
    # honest failure when the gate never passes
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("s1"), fake_run("r"),   # iter1: ask + do
        fake_run("s2"), fake_run("r"),   # iter2
    ]), mock.patch("ranger.subprocess.Popen",
                   return_value=fake_popen(1)):   # gate never passes
        res = agent.until("goal", max_iter=2, gate_cmd="false")
    assert res == {"achieved": False, "iterations": 2,
                   "steps": ["s1", "s2"], "report": "r",
                   "last_gate": {"kind": "gate_cmd", "ok": False,
                                 "output": ""}}


# ==================================================================== #
# 6. stats parsers: numbers must be the RIGHT numbers

OPENCODE_JSON = (
    '{"sessionID":"ses_x","part":{"type":"text","text":"hello ",'
    '"time":{"start":100,"end":1600}}}\n'
    '{"sessionID":"ses_x","part":{"type":"text","text":"world",'
    '"time":{"start":2000,"end":2600}}}\n'
)
CODEX_JSON = (
    '{"type":"thread.started","thread_id":"t9"}\n'
    '{"type":"item.completed","item":{"type":"agent_message","text":"one"}}\n'
    '{"type":"item.completed","item":{"type":"agent_message","text":"two"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":7,'
    '"cached_input_tokens":3,"output_tokens":11}}\n'
)

def test_opencode_stats_math():
    agent = Ranger(stats=True)
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run(OPENCODE_JSON)):
        ans = agent.ask("q")
    assert ans == "hello \nworld"                  # parts joined verbatim
    assert agent.last["model_s"] == round((2600 - 100) / 1000, 2)  # 2.5
    assert agent.last["parts"] == 2 and agent.last["chars"] == 12
    assert agent.last["session"] == "ses_x"

def test_codex_stats_numbers():
    agent = Ranger(backend="codex", stats=True)
    with mock.patch("ranger.subprocess.run", return_value=fake_run(CODEX_JSON)):
        ans = agent.ask("q")
    assert ans == "one\ntwo"
    last = agent.last
    assert last["input_tokens"] == 7 and last["cached_input_tokens"] == 3
    assert last["output_tokens"] == 11 and last["session"] == "t9"


# ==================================================================== #
# 7. interaction flows: scripted behavior -> exact structural outcome

def test_refine_with_feeds_changes_and_stops_on_approve():
    builder, critic = Ranger(cwd="/tmp"), Ranger(cwd="/tmp")
    captured = []
    def fake(cmd, **kw):
        captured.append(cmd[-1])
        replies = ["worked",
                   "VERDICT: REQUEST_CHANGES\nFINDINGS: f\nCHANGES: add empty test",
                   "worked2",
                   "VERDICT: APPROVE\nFINDINGS: all good\nCHANGES: none"]
        return fake_run(replies[len(captured) - 1])
    with mock.patch("ranger.subprocess.run", side_effect=fake):
        out = builder.refine_with(critic, "the goal", max_iter=3)
    assert out["approved"] is True and out["iterations"] == 2
    # the second do() prompt must carry the requested changes verbatim
    assert "add empty test" in captured[2]
    assert "the goal" in captured[2]


def test_challenge_concedes_and_rules_exactly():
    attacker, defender = Ranger(), Ranger()
    defender.context.append({"role": "assistant", "content": "CLAIM"})
    q = []
    def fake(cmd, **kw):
        q.append(cmd[-1])
        r = ["ATTACK: hole", "fair.\nCONCEDED"]
        return fake_run(r[len(q) - 1])
    with mock.patch("ranger.subprocess.run", side_effect=fake):
        duel = attacker.challenge(defender, rounds=5)
    assert duel["survived"] is False and len(duel["rounds"]) == 1
    assert duel["rounds"][0]["ruling"] == "CONCEDED"
    # the defender was actually shown the attack text (marker-stripped)
    assert "hole" in q[1] and "ATTACK:" not in q[1].split("hole")[0]


def test_second_opinion_table():
    a, b = Ranger(), Ranger()
    for mine, theirs, differs in [
        ("\n\nThe  ANSWER\n", "the answer", False),
        ("The answer is 42", "The answer is 43", True),
        ("", "", False),
    ]:
        with mock.patch("ranger.subprocess.run", side_effect=[
            fake_run(mine), fake_run(theirs),
        ]):
            assert a.second_opinion(b, "q")["differs"] is differs


def test_debate_alternates_and_judge_sees_all(tmp_path):
    a, b, judge = Ranger(), Ranger(), Ranger()
    seen = []
    def fake(cmd, **kw):
        seen.append(cmd[-1])
        return fake_run(f"pos{len(seen)}")
    with mock.patch("ranger.subprocess.run", side_effect=fake):
        talk = ranger.debate(a, b, "topic", rounds=3, judge=judge)
    assert len(talk["transcript"]) == 3
    # round 2's first speaker sees round 1's second-speaker position
    assert "pos2" in seen[2]
    # judge (7th call) sees every position and records no chat
    judge_prompt = seen[6]
    for pos in ("pos1", "pos3", "pos5"):
        assert pos in judge_prompt
    assert judge.context == []


# ==================================================================== #
# 8. the budget commitment itself — enforced, not promised

def test_suite_stays_within_one_minute():
    """Every other test file must finish in under 60 seconds.

    All current test files are globbed in (minus this one — no
    recursion), so future test files are budget-checked automatically.
    """
    others = sorted(str(p) for p in REPO.glob("tests/test_*.py")
                    if p.name != "test_logic.py")
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *others],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    elapsed = time.monotonic() - t0
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert elapsed < 60, f"suite takes {elapsed:.1f}s — over the 1-minute budget"


# ==================================================================== #
# 9. critic round 2 regressions — strict decision grammars

REVIEW_OK = "VERDICT: APPROVE\nFINDINGS: everything verified\nCHANGES: none"


def test_reviews_reject_poisoned_and_broken_verdicts():
    bad = [
        "VERDICT: APPROVE_NOT\nFINDINGS: f\nCHANGES: none",    # invalid token
        "VERDICT: APPROVE\nVERDICT: REJECT\nFINDINGS: f\nCHANGES: none",
        "VERDICT: APPROVE\nFINDINGS: like it\nCHANGES:",       # empty CHANGES
        REVIEW_OK.replace("FINDINGS: everything verified\n", ""),  # no FINDINGS
        "no verdict at all here",
    ]
    agent = Ranger()
    for reply in bad:
        with mock.patch("ranger.subprocess.run",
                        return_value=fake_run(reply)):
            with pytest.raises(RangerError):
                agent.review("x")
    # and the same grammar holds for answers decoded from codex JSON
    codex = ('{"type":"item.completed","item":{"type":"agent_message",'
             '"text":"VERDICT: REJECT\\nFINDINGS: broke\\nCHANGES: fix it"}}\n')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(codex)):
        assert Ranger(backend="codex").review("x") == {
            "passed": False, "verdict": "REJECT",
            "findings": "broke", "changes": "fix it"}


def test_review_preserves_multiline_sections():
    reply = ("VERDICT: REQUEST_CHANGES\n"
             "FINDINGS:\n- a is broken\n- b is missing\n"
             "CHANGES:\n- fix a\n- add b")
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run(reply)):
        rev = agent.review("x")
    assert rev["findings"] == "- a is broken\n- b is missing"
    assert rev["changes"] == "- fix a\n- add b"


def test_challenge_rejects_broken_contracts():
    attacker, defender = Ranger(), Ranger()
    defender.context.append({"role": "assistant", "content": "CLAIM"})
    # defense with no terminal status
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("ATTACK: hole"), fake_run("I disagree entirely."),
    ]):
        with pytest.raises(RangerError, match="DEFENDED"):
            attacker.challenge(defender, rounds=1)
    # conflicting statuses
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("ATTACK: hole"), fake_run("d\nDEFENDED\nCONCEDED"),
    ]):
        with pytest.raises(RangerError, match="conflicting"):
            attacker.challenge(defender, rounds=1)
    # attack without the ATTACK: marker
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run("the hole is obvious")):
        with pytest.raises(RangerError, match="ATTACK"):
            attacker.challenge(defender, rounds=1)
    # double ruling
    with mock.patch("ranger.subprocess.run", side_effect=[
        fake_run("ATTACK: hole"), fake_run("d\nDEFENDED"),
        fake_run("RULING: SUSTAINED\nRULING: WITHDRAWN"),
    ]):
        with pytest.raises(RangerError, match="conflicting"):
            attacker.challenge(defender, rounds=1)


def test_challenge_judgments_run_pure():
    attacker, defender = Ranger(session="ses_bias"), Ranger()
    defender.context.append({"role": "assistant", "content": "CLAIM"})
    attacker.context = [{"role": "user", "content": "OLD_BIAS"}]
    cmds = []
    replies = iter(["ATTACK: hole", "d\nDEFENDED", "RULING: WITHDRAWN"])
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda cmd, **kw: (cmds.append(cmd),
                                                   fake_run(next(replies)))[1]):
        attacker.challenge(defender, rounds=1)
    attack_cmd, defense_cmd = cmds[0], cmds[1]
    assert "ses_bias" not in attack_cmd        # judgment never resumes a session
    assert "OLD_BIAS" not in attack_cmd[-1]    # nor recalls chat history
    ruling_cmd = cmds[2]
    assert "ses_bias" not in ruling_cmd and "OLD_BIAS" not in ruling_cmd[-1]
    assert "ses_bias" not in defense_cmd       # defense keeps user settings


def test_refine_with_gates_the_actual_report_not_history():
    builder = Ranger(memory=False, cwd="/tmp")
    critic = Ranger()
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd[-1])
        return (fake_run("the report text")
                if len(seen) == 1
                else fake_run(REVIEW_OK))

    with mock.patch("ranger.subprocess.run", side_effect=fake):
        out = builder.refine_with(critic, "goal", max_iter=1)
    assert out["approved"] is True
    # the review prompt carries the work report as claims — even though
    # memory=False means nothing was recorded in context
    assert "the report text" in seen[1]
    assert builder.context == []


def test_refine_and_debate_fail_fast_on_bad_overrides():
    builder, critic = Ranger(), Ranger()
    judge = Ranger()
    # session can never reach the session-free review -> TypeError BEFORE do()
    with mock.patch("ranger.subprocess.run") as m:
        with pytest.raises(TypeError, match="session"):
            builder.refine_with(critic, "goal", session="s1")
    assert m.call_count == 0
    # judge purity can't collide with user overrides
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd)
        return fake_run(f"pos{len(seen)}")

    with mock.patch("ranger.subprocess.run", side_effect=fake):
        ranger.debate(Ranger(), Ranger(), "topic", rounds=1, judge=judge,
                      session="s2", memory=False)
    assert len(seen) == 3
    assert "s2" not in seen[2]                # judge ran session-free
    # judge type validated before any speaker runs
    with mock.patch("ranger.subprocess.run") as m:
        with pytest.raises(TypeError, match="judge"):
            ranger.debate(Ranger(), Ranger(), "topic", rounds=1,
                          judge="not an agent")
    assert m.call_count == 0


# ==================================================================== #
# 12. extract(): the JSON grammar — truth table, same style as check()

def test_extract_parses_success_and_prompt_is_pinned():
    agent = Ranger()
    answer = '[{"test_id": "t1", "reason": "import"}, {"test_id": "t2", "reason": "typo"}]'
    cmds = []
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda c, **k: cmds.append(c)
                    or fake_run(answer)):
        rows = agent.extract("failing tests", keys=["test_id", "reason"])
    assert rows == [{"test_id": "t1", "reason": "import"},
                    {"test_id": "t2", "reason": "typo"}]
    # frozen prompt template — a breaking-change test (law 1)
    prompt = cmds[0][-1]
    assert prompt.startswith(
        'Extract structured data for this request: failing tests')
    assert '"test_id", "reason"' in prompt
    assert "EXACTLY ONE JSON array of objects" in prompt
    assert "no prose before or after, no markdown fences" in prompt


def test_extract_single_object_mode():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run('{"name": "ranger", "version": "0.7"}')):
        one = agent.extract("project metadata",
                            keys=["name", "version"], many=False)
    assert one == {"name": "ranger", "version": "0.7"}
    with mock.patch("ranger.subprocess.run",
                    return_value=fake_run('[{"name": "ranger", "version": "0.7"}]')):
        with mock.patch("ranger.subprocess.run",
                        return_value=fake_run('{"name": "ranger", "version": "0.7"}')):
            with pytest.raises(RangerError, match="many=True"):
                agent.extract("meta", keys=["name"],
                              many=True)  # object when array expected


@pytest.mark.parametrize("answer,pat", [
    ('not json at all', "could not parse JSON"),
    ('[{"a": 1}], trailing prose', "could not parse JSON"),
    ('```json\n{"a": 1}\n```', "could not parse JSON"),   # fences are prose
    ('[{"test_id": "t1"}]', "missing key"),
    ('[{"a": 1}]', "missing key"),
    ('["a string"]', "not a JSON object"),
    ('{"a": 1}', "expected a JSON array"),
    ('42', "expected a JSON array"),
    ('[{"test_id": "t1", "reason": "x"}, {"test_id": "z"}]', "missing key"),
])
def test_extract_failure_truth_table(answer, pat):
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run(answer)):
        with pytest.raises(RangerError, match=pat):
            agent.extract("q", keys=["test_id", "reason"])


def test_extract_single_mode_failure_shapes():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run('[{"a": 1}]')):
        with pytest.raises(RangerError, match="many=False"):
            agent.extract("q", keys=["a"], many=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run('{"b": 1}')):
        with pytest.raises(RangerError, match="missing key"):
            agent.extract("q", keys=["a"], many=False)


def test_extract_empty_results_are_legitimate():
    agent = Ranger()
    with mock.patch("ranger.subprocess.run", return_value=fake_run("[]")):
        assert agent.extract("q", keys=["k"]) == []
    with mock.patch("ranger.subprocess.run", return_value=fake_run("{}")):
        assert agent.extract("q", keys=["k"], many=False) == {}


def test_extract_validates_keys_up_front():
    agent = Ranger()
    for bad in (["ok", ""], [], "test_id", 42, ()):  # empty/str/num/empty tuple
        with pytest.raises((TypeError, ValueError)):
            agent.extract("q", keys=bad)


def test_extract_is_pure_no_session_no_recall():
    agent = Ranger(session="keep", memory=True, cwd=".")
    agent.context.append({"role": "user", "content": "old stuff"})
    cmds = []
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda c, **k: cmds.append(c) or
                    fake_run("[]")):
        agent.extract("q", keys=["k"])
    prompt = cmds[0][-1]
    assert "keep" not in prompt and "old stuff" not in prompt
    assert "## Previous interaction" not in prompt


# ==================================================================== #
# 13. costs(): the cumulative ledger — truth table (issue #6)

def test_costs_accumulates_across_calls():
    agent = Ranger(memory=False)
    a1, a2 = "hello world!", "short"
    with mock.patch("ranger.subprocess.run", return_value=fake_run(a1)):
        agent.ask("question one")
    with mock.patch("ranger.subprocess.run", return_value=fake_run(a2)):
        agent.do("goal two")
    c = agent.costs
    assert c["calls"] == 2
    assert c["chars_out"] == len(a1) + len(a2)
    assert c["chars_in"] > 0       # full prompts (contracts text) sent
    assert c["wall_s"] >= 0.0


def test_costs_prompt_chars_track_the_real_prompt():
    agent = Ranger(memory=False)
    sent = []
    with mock.patch("ranger.subprocess.run",
                    side_effect=lambda cmd, **k: sent.append(cmd[-1])
                    or fake_run("x")):
        agent.ask("precise question text")
    assert agent.costs["chars_in"] == len(sent[0])


def test_costs_tokens_none_until_backend_reports():
    agent = Ranger(memory=False)          # plain text mode: no telemetry
    with mock.patch("ranger.subprocess.run", return_value=fake_run("answer")):
        agent.ask("q")
    assert agent.costs["tokens_in"] is None
    assert agent.costs["tokens_out"] is None


def test_costs_tokens_accumulate_from_backend_telemetry():
    agent = Ranger(backend="claude", stats=True, memory=False)
    obj = ('{"result": "done", "session_id": "s1", "total_cost_usd": 0.01, '
           '"usage": {"input_tokens": 120, "output_tokens": 30}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(obj)):
        agent.ask("q1")
    obj2 = ('{"result": "done2", "session_id": "s2", "total_cost_usd": 0.02, '
            '"usage": {"input_tokens": 80, "output_tokens": 20}}')
    with mock.patch("ranger.subprocess.run", return_value=fake_run(obj2)):
        agent.ask("q2")
    assert agent.costs["calls"] == 2
    assert agent.costs["tokens_in"] == 200
    assert agent.costs["tokens_out"] == 50


def test_costs_reset_returns_and_zeroes():
    agent = Ranger(memory=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("abc")):
        agent.ask("q")
    before = agent.costs_reset()
    assert before["calls"] == 1 and before["chars_out"] == 3
    assert agent.costs == {"calls": 0, "chars_in": 0, "chars_out": 0,
                           "tokens_in": None, "tokens_out": None,
                           "wall_s": 0.0}
    with mock.patch("ranger.subprocess.run", return_value=fake_run("de")):
        agent.ask("q2")
    assert agent.costs["calls"] == 1          # counted from the reset only


def test_costs_failed_run_records_nothing():
    agent = Ranger(memory=False, retries=0)
    bad = mock.Mock()
    bad.returncode, bad.stdout, bad.stderr = 3, "", "kaput"
    with mock.patch("ranger.subprocess.run", return_value=bad):
        with pytest.raises(RangerError):
            agent.ask("q")
    assert agent.costs["calls"] == 0
    assert agent.costs["chars_in"] == 0


def test_costs_returns_a_copy_not_the_live_ledger():
    agent = Ranger(memory=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x")):
        agent.ask("q")
    agent.costs["calls"] = 999               # mutating a snapshot: harmless
    assert agent.costs["calls"] == 1


def test_costs_ledger_is_per_agent():
    a, b = Ranger(memory=False), Ranger(memory=False)
    with mock.patch("ranger.subprocess.run", return_value=fake_run("x")):
        a.ask("q")
    assert a.costs["calls"] == 1
    assert b.costs["calls"] == 0       # debate partners keep own ledgers


def test_costs_until_loop_is_bounded_accounting():
    agent = Ranger(memory=False, timeout=30)
    # replies, in order: pre-check NO, step, report, verdict NO (budget ends red)
    replies = [fake_run("NO"), fake_run("step"),
               fake_run("report"), fake_run("NO")]
    with mock.patch("ranger.subprocess.run", side_effect=replies):
        result = agent.until("goal", max_iter=1, condition="cond")
    assert result["achieved"] is False
    # pre-check ask + step ask + do run + verdict ask = 4 completed calls
    assert agent.costs["calls"] == 4
