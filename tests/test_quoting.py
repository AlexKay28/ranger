"""quote(): price a run BEFORE paying for it — no spawn, no state change.

quote() must share the _prepare_run seam with the real runs (law 1):
whatever it reports is exactly what the matching _run() would send.
"""

from pathlib import Path
from unittest import mock

import ranger
from ranger import Ranger


def test_quote_matches_the_real_prompt_byte_for_byte():
    agent = Ranger(memory=True, effort="low")
    agent.context.append({"role": "user", "content": "earlier turn"})
    q = agent.quote("do the thing", "do")
    prep = agent._prepare_run("do the thing", "do", {})
    assert q["chars_total"] == len(prep["full_prompt"])   # law 1: same seam
    assert q["label"] == "do" and q["backend"] == "opencode"
    seg = q["segments"]
    assert seg["request"] == len("do the thing")
    assert seg["recall"] > 0                              # memory carries history
    assert seg["effort"] > 0                              # low-effort directive
    assert sum(seg.values()) == q["chars_total"]          # breakdown is exhaustive


def test_quote_never_spawns_or_mutates():
    agent = Ranger(memory=True)
    agent.context.append({"role": "user", "content": "earlier turn"})
    ctx_len = len(agent.context)
    with mock.patch("ranger.subprocess.run",
                    side_effect=AssertionError("quote() must not spawn")):
        q = agent.quote("find the parser", "search")
    assert len(agent.context) == ctx_len          # quoting records nothing
    assert agent.costs["calls"] == 0              # and bills nothing
    assert q["segments"]["recall"] == 0           # pure fact label: no recall


def test_quote_counts_inline_skill_files_as_other():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        skill = Path(td) / "ops.md"
        skill.write_text("# ops\n" + "be terse. " * 40, encoding="utf-8")
        agent = Ranger(backend="codex", skills=[skill, "stay terse"])
        q = agent.quote("do the thing", "do")
        assert q["backend"] == "codex"
        assert q["skill_files"] == [str(skill)]
        assert q["segments"]["other"] > 200        # the file body, inlined
        assert q["segments"]["grants"] > 0         # the prose grant


def test_quote_estimate_is_honest_arithmetic():
    agent = Ranger(effort="high", memory=False)
    q = agent.quote("hello")
    assert q["est_tokens_in"] == round(q["chars_total"] / 4)
    assert q["segments"]["request"] == len("hello")
