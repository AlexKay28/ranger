"""Safety rails (issue #3): allow/deny path globs + dry-run — fully mocked.

Law 4 pinned here: the rails are pure-Python predicates (fnmatch on
paths), never prompt instructions. deny wins over allow; per-call
overrides win over the constructor; default (allow=None, deny=None)
adds ZERO subprocess calls on any path (backward compat).
"""

import subprocess
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError

RANGER_MOD = "ranger.subprocess"


class FakeRunner:
    """One seam, two voices: git plumbing vs the harness CLI run."""

    def __init__(self, agent_replies=None, git_replies=None, git_fails=False):
        self.runs = []          # every cmd, in order
        self.agent_replies = list(agent_replies or [])
        self.git_replies = {
            "rev-parse": "/repo\n",
            "status": " M src/ok.py\n",
        }
        self.git_replies.update(git_replies or {})
        self.git_fails = git_fails

    def __call__(self, cmd, **kw):
        self.runs.append(list(cmd))
        if cmd[0] == "git":
            sub = cmd[1]
            if sub == "rev-parse" and self.git_fails:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="fatal: not a git repository")
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.git_replies.get(sub, ""), stderr="")
        reply = self.agent_replies.pop(0) if self.agent_replies else "ok\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")


def fake_harness(stdout="done"):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


# --------------------------------------------------------------------- #
# spec validation

class TestSpecValidation:
    def test_ctor_rejects_bare_and_wrong_types(self):
        for bad in ("src/**", 42, {"a": 1}, [42], [""]):
            with pytest.raises((TypeError, ValueError)):
                Ranger(allow=bad)
            with pytest.raises((TypeError, ValueError)):
                Ranger(deny=bad)

    def test_none_and_empty_list_mean_no_rails(self):
        for spec in (None, []):
            agent = Ranger(allow=spec, deny=spec)
            assert agent.allow is None and agent.deny is None

    def test_per_call_bad_spec_raises_typeerror_before_spawn(self):
        agent = Ranger(cwd=".")
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            for bad in ({"allow": "src/**"}, {"deny": 42},
                        {"dry_run": "yes"}, {"allow": [42]}):
                with pytest.raises((TypeError, ValueError)):
                    agent.do("goal", **bad)
                with pytest.raises((TypeError, ValueError)):
                    agent.ask("q", **bad)   # shared seam validates too
        assert fake.runs == []

    def test_unknown_keywords_still_raise(self):
        agent = Ranger(cwd=".")
        with mock.patch(f"{RANGER_MOD}.run"):
            with pytest.raises(TypeError, match="unknown run option"):
                agent.do("goal", alow=["src/**"])   # typo: loud, not silent


# --------------------------------------------------------------------- #
# edit()/write(): known targets — pre-spawn path predicates

class TestTargetRails:
    def test_edit_denied_path_never_spawns(self, tmp_path):
        target = tmp_path / "secrets.env"
        target.write_text("k=v", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, deny=["**/secrets*"])
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="denied by the safety rails"):
                agent.edit(target, "add a comment")
        assert fake.runs == []          # law 4: refused BEFORE the spawn

    def test_edit_outside_allow_refused_before_spawn(self, tmp_path):
        target = tmp_path / "notes" / "other.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="outside the allow"):
                agent.edit(target, "bump")
        assert fake.runs == []

    def test_edit_allowed_target_runs_once(self, tmp_path):
        target = tmp_path / "src" / "mod.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["**/src/**"])
        with mock.patch(f"{RANGER_MOD}.run") as run:
            # tmp_path may live outside any git repo: mtime check is the
            # edit() contract — mutation must actually happen; the harness
            # did not touch the file in this mock, so edit() reports THAT
            run.return_value = fake_harness()
            with pytest.raises(RangerError, match="did not modify"):
                agent.edit(target, "bump")
        assert run.call_count == 1     # the run itself: allowed, one call

    def test_deny_wins_over_allow(self, tmp_path):
        target = tmp_path / "src" / "danger.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path,
                       allow=["src/**"], deny=["**/danger.py"])
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="denied"):
                agent.edit(target, "bump")
        assert fake.runs == []

    def test_write_path_respects_rails(self, tmp_path):
        agent = Ranger(cwd=tmp_path, deny=["**/private*"])
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="denied"):
                agent.write("report", path=tmp_path / "private.md")
        assert fake.runs == []

    def test_per_call_override_wins_over_ctor(self, tmp_path):
        target = tmp_path / "src" / "mod.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        fake = FakeRunner()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            # per-call allow REPLACES the ctor allow: this target is out
            with pytest.raises(RangerError, match="outside the allow"):
                agent.edit(target, "bump", allow=["docs/**"])
            # per-call deny REPLACES the ctor deny (nothing denied now)
            agent2 = Ranger(cwd=tmp_path, deny=["**/mod.py"])
            with mock.patch(f"{RANGER_MOD}.run") as run:
                run.return_value = fake_harness()
                with pytest.raises(RangerError, match="did not modify"):
                    agent2.edit(target, "bump", deny=["**/other.py"])
        assert fake.runs == []


# --------------------------------------------------------------------- #
# do(): target-LESS mutation — pre-flight verifiability + post-run check

class TestDoRails:
    def test_default_rails_add_zero_calls(self):
        agent = Ranger(cwd=".")
        fake = FakeRunner(agent_replies=["did it\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("goal") == "did it"
        assert len(fake.runs) == 1 and fake.runs[0][0] == "opencode"

    def test_rails_with_no_git_repo_refuse_up_front(self):
        agent = Ranger(cwd="/somewhere", deny=["**/.env"])
        fake = FakeRunner(git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.do("goal")
        # the ONLY subprocess call was the verifiability probe: no
        # harness was ever spawned for an unverifiable mutation
        assert fake.runs == [["git", "rev-parse", "--show-toplevel"]]

    def test_do_post_run_violation_raises_naming_paths(self):
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status": " M src/ok.py\n?? secrets.key\n"})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match=r"secrets\.key"):
                agent.do("goal")
        kinds = [c[0] for c in fake.runs]
        # rev-parse probe -> harness round -> post-run status check
        assert kinds == ["git", "opencode", "git"]

    def test_do_allowed_paths_pass_quietly(self):
        agent = Ranger(cwd="/repo", allow=["src/**", "README*"])
        fake = FakeRunner(agent_replies=["did it\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("goal") == "did it"

    def test_do_dry_run_skips_the_boundary_check(self):
        agent = Ranger(cwd="/somewhere", deny=["**/.env"])
        fake = FakeRunner(agent_replies=["here is the plan\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("goal", dry_run=True) == "here is the plan"
        # dry run cannot mutate: no rev-parse probe, no post-run status
        assert [c[0] for c in fake.runs] == ["opencode"]
        argv = fake.runs[0]
        assert argv[argv.index("--agent") + 1] == "plan"

    def test_until_passes_rails_through_its_do_rounds(self):
        agent = Ranger(cwd="/somewhere", timeout=30,
                       deny=["**/.env"], retries=0)
        # rails active + cwd not a git repo: the loop's work round must
        # refuse BEFORE any harness spawn for that round — rails gate
        # every do() inside until()/resolve()/attempt() automatically
        fake = FakeRunner(agent_replies=["NO\n", "a step\n"],
                          git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.until("goal", max_iter=2, condition="cond")
        kinds = [c[0] for c in fake.runs]
        # pre-check verdict + step ask ran; the do round died at its
        # verifiability probe — never spawned the harness
        assert kinds == ["opencode", "opencode", "git"]


# --------------------------------------------------------------------- #
# dry_run: backend read-only mappings (argv pins, all mocked)

class TestDryRunArgv:
    def _opts(self, **kw):
        base = dict(model="m", cwd=None, timeout=600.0, auto=True,
                    session=None, agent=None, mode=None, title=None,
                    thinking=False, pretty=True, memory=True, skills=None,
                    effort="medium", stats=False, backend="opencode",
                    memory_budget=1000, retries=0, env=None,
                    allow=None, deny=None, dry_run=True)
        base.update(kw)
        return base

    def test_opencode_maps_to_plan_agent(self):
        adapter = ranger._BACKEND_CLASSES["opencode"]()
        cmd, _ = adapter.build_cmd(self._opts(), "hi", [])
        assert cmd[cmd.index("--agent") + 1] == "plan"

    def test_opencode_dry_run_conflicts_with_agent(self):
        adapter = ranger._BACKEND_CLASSES["opencode"]()
        with pytest.raises(RangerError, match="plan agent"):
            adapter.build_cmd(self._opts(agent="build"), "hi", [])

    def test_codex_maps_to_read_only_sandbox(self):
        adapter = ranger._BACKEND_CLASSES["codex"]()
        cmd, _ = adapter.build_cmd(self._opts(), "hi", [])
        assert cmd[cmd.index("-s") + 1] == "read-only"
        assert "--approve-for-me" not in cmd
        # resume branch honors read-only via -c (resume takes no -s)
        cmd, _ = adapter.build_cmd(self._opts(session="th-1"), "hi", [])
        assert 'sandbox_mode="read-only"' in cmd

    def test_claude_dry_run_strips_permission_grants(self):
        adapter = ranger._BACKEND_CLASSES["claude"]()
        cmd, _ = adapter.build_cmd(self._opts(), "hi", [])
        assert "--permission-mode" not in cmd
        assert "--allowedTools" not in cmd          # nothing may be edited

    def test_pi_and_openhands_refuse_honestly(self):
        for name in ("pi", "openhands"):
            adapter = ranger._BACKEND_CLASSES[name]()
            with pytest.raises(RangerError, match="does not support"):
                adapter.build_cmd(self._opts(), "hi", [])

    def test_edit_dry_run_has_no_mtime_postcheck(self, tmp_path):
        target = tmp_path / "t.py"
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path)
        with mock.patch(f"{RANGER_MOD}.run") as run:
            run.return_value = fake_harness("planned changes: ...")
            report = agent.edit(target, "double it", dry_run=True)
        assert "planned changes" in report     # no "did not modify" error
        argv = run.call_args.args[0]
        assert argv[argv.index("--agent") + 1] == "plan"

    def test_write_dry_run_has_no_file_postcheck(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        out = tmp_path / "never.md"
        with mock.patch(f"{RANGER_MOD}.run") as run:
            run.return_value = fake_harness("would write ...")
            assert agent.write("report", path=out, dry_run=True) == str(out)
        assert not out.is_file()               # nothing was applied

    def test_dry_run_costs_still_record(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(f"{RANGER_MOD}.run") as run:
            run.return_value = fake_harness("plan")
            agent.do("goal", dry_run=True)
        assert agent.costs["calls"] == 1
