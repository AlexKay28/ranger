"""The fix/transform/commit tier (issue #4) — fully mocked.

fix() inherits until()'s honesty rules (pre-verdict, bounded rounds,
mechanical verdicts, never a sympathy pass); transform() is batch
edit() with per-file isolation; commit() stages + commits only,
refusing non-repos, clean trees and rail violations.
"""

import os
import subprocess
import time
from unittest import mock

import pytest

from ranger import Ranger, RangerError

RANGER_MOD = "ranger.subprocess"


class FakeRunner:
    def __init__(self, agent_replies=None, git_replies=None, git_fails=False):
        self.runs = []
        self.agent_replies = list(agent_replies or [])
        self.git_replies = {"rev-parse": "/repo\n",
                            "status": " M src/ok.py\n"}
        self.git_replies.update(git_replies or {})
        self.git_fails = git_fails

    def __call__(self, cmd, **kw):
        self.runs.append(list(cmd))
        if cmd[0] == "git":
            if cmd[1] == "rev-parse" and self.git_fails:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="fatal: not a git repository")
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.git_replies.get(cmd[1], ""), stderr="")
        reply = self.agent_replies.pop(0) if self.agent_replies else "ok\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")


# --------------------------------------------------------------------- #
# fix()

class TestFix:
    def test_already_green_never_invents_work(self):
        agent = Ranger(cwd=".", timeout=30)
        fake = FakeRunner(
            agent_replies=["YES\n"], git_replies={"status": ""})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.fix("the bug", condition="conv")
        assert result == {"status": "ALREADY_GREEN", "problem": "the bug",
                          "diagnosis": "", "iterations": 0,
                          "last_gate": {"kind": "condition", "ok": True,
                                        "output": ""}}

    def test_fixed_in_one_round(self):
        agent = Ranger(cwd=".", timeout=30)
        # pre-check NO, diagnosis, do report, verdict YES
        replies = ["NO\n", "the root cause is X\n",
                   "fixed it\n", "YES\n"]
        fake = FakeRunner(agent_replies=replies, git_replies={"status": ""})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.fix("the bug", condition="conv")
        assert result["status"] == "FIXED"
        assert result["iterations"] == 1
        assert "root cause is X" in result["diagnosis"]
        assert result["last_gate"]["ok"] is True
        # diagnosis traveled INTO the repair prompt (frozen carrier)
        work_prompt = fake.runs[2][-1]
        assert "root cause is X" in work_prompt

    def test_budget_exhaustion_is_honest(self):
        agent = Ranger(cwd=".", timeout=30)
        # pre-check NO, diagnosis, then 2 rounds of (do, verdict-NO)
        replies = ["NO\n", "dx\n", "r1\n", "NO\n", "r2\n", "NO\n"]
        fake = FakeRunner(agent_replies=replies, git_replies={"status": ""})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.fix("the bug", condition="conv", max_iter=2)
        assert result["status"] == "FAILED"
        assert result["iterations"] == 2        # never a sympathy round

    def test_refused_environment_rails_gates_the_work(self):
        agent = Ranger(cwd="/somewhere", timeout=30, deny=["**/.env"])
        fake = FakeRunner(agent_replies=["NO\n", "dx\n"], git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.fix("the bug", condition="conv", max_iter=2)

    def test_bad_budget_raises_up_front(self):
        agent = Ranger(cwd=".")
        for bad in (0, -1, 2.5, True, "3"):
            with pytest.raises(ValueError, match="max_iter"):
                agent.fix("bug", max_iter=bad)


# --------------------------------------------------------------------- #
# transform()

class TestTransform:
    def _files(self, tmp_path, name, n):
        folder = tmp_path / name
        folder.mkdir()
        for i in range(n):
            (folder / f"f{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        return folder

    def test_batch_applies_sorted_and_capped(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        for i, name in enumerate("abcd"):
            (tmp_path / f"{name}.py").write_text(f"x = {i}\n", encoding="utf-8")
        # mocked edits do not touch mtimes: use dry_run to make each
        # edit a read-only plan run (still ONE harness call per file)
        with mock.patch(f"{RANGER_MOD}.run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="planned", stderr="")
            results = agent.transform("*.py", "add docstring",
                                      max_files=2, dry_run=True)
        assert [r["file"].split("/")[-1] for r in results] == \
            ["a.py", "b.py"]      # sorted, capped at max_files
        assert run.call_count == 2
        assert all("report" in r and "error" not in r for r in results)

    def test_per_file_failure_isolation(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        folder = self._files(tmp_path, "m", 2)
        broken = folder / "f1.py"

        def mutate_or_not(cmd, **kw):
            prompt = cmd[-1]
            # the frozen edit template carries the resolved file path
            if str(broken) in prompt:
                return subprocess.CompletedProcess(
                    [], 0, stdout="did nothing", stderr="")
            # genuinely touch every other target so the mtime post-check
            # sees a real change (explicit utime: FS timestamp granularity
            # can collapse two writes into the same mtime_ns under load)
            for f in folder.glob("*.py"):
                if str(f) in prompt and str(broken) not in str(f):
                    line = f.read_text(encoding="utf-8")
                    f.write_text(line + "# touched\n", encoding="utf-8")
                    os.utime(f, ns=(time.time_ns() + 10**9,
                                    time.time_ns() + 10**9))
                    return subprocess.CompletedProcess(
                        [], 0, stdout="edited it", stderr="")
            return subprocess.CompletedProcess([], 0, stdout="?", stderr="")

        with mock.patch(f"{RANGER_MOD}.run", side_effect=mutate_or_not):
            results = agent.transform("m/*.py", "double it")
        assert len(results) == 2
        ok = [r for r in results if "report" in r]
        bad = [r for r in results if "error" in r]
        assert len(ok) == 1 and len(bad) == 1
        assert "f1.py" in bad[0]["file"]            # the failure is NAMED
        assert "did not modify" in bad[0]["error"]

    def test_no_matches_is_an_honest_refusal(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch(f"{RANGER_MOD}.run"):
            with pytest.raises(RangerError, match="no files match"):
                agent.transform("**/*.nope", "instr")

    def test_deny_rail_records_per_file_refusals(self, tmp_path):
        self._files(tmp_path, "m", 2)
        agent = Ranger(cwd=tmp_path, deny=["**/f0.py"])
        with mock.patch(f"{RANGER_MOD}.run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="planned", stderr="")
            results = agent.transform("m/*.py", "x", dry_run=True)
        denied = [r for r in results if r["file"].endswith("f0.py")]
        assert "error" in denied[0] and "denied" in denied[0]["error"]
        # zero harness calls: the denied target is refused pre-spawn AND
        # the allowed one ran exactly once
        assert run.call_count == 1

    def test_spec_validation(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        for bad in (42, "", None):
            with pytest.raises(TypeError):
                agent.transform(bad, "x")
        for bad in ("", "  ", 42):
            with pytest.raises(TypeError):
                agent.transform("*", bad)
        for bad in (0, -3, True, 2.5):
            with pytest.raises(ValueError):
                agent.transform("*", "x", max_files=bad)


# --------------------------------------------------------------------- #
# commit()

class TestCommit:
    def test_happy_path_stages_and_commits_only(self):
        agent = Ranger(cwd="/repo")
        fake = FakeRunner(git_replies={"rev-parse": "/repo\n",
                                       "status": " M src/a.py\n",
                                       "commit": ""})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            sha = agent.commit("my fix", allow=["src/**"])
        argvs = [c for c in fake.runs]
        assert argvs[0] == ["git", "rev-parse", "--show-toplevel"]
        assert argvs[1] == ["git", "status", "--porcelain"]
        assert argvs[2] == ["git", "add", "-A", "--"]
        assert argvs[3] == ["git", "commit", "-m", "my fix"]
        assert argvs[4] == ["git", "rev-parse", "HEAD"]
        assert sha == "/repo"     # rev-parse reply doubles as the "sha"
        # never any destructive verb anywhere in the method's lifetime
        flat = " ".join(" ".join(map(str, c)) for c in argvs)
        for verb in ("push", "reset", "clean", "checkout", "rebase",
                    "revert", "filter-branch", "force"):
            assert verb not in flat

    def test_clean_tree_is_refused(self):
        agent = Ranger(cwd="/repo")
        fake = FakeRunner(git_replies={"status": ""})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="nothing to commit"):
                agent.commit()
        assert fake.runs[-1] == ["git", "status", "--porcelain"]  # no add

    def test_non_repo_is_refused(self):
        agent = Ranger(cwd="/somewhere")
        fake = FakeRunner(git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.commit()

    def test_rail_violation_in_changeset_never_stages(self):
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        fake = FakeRunner(git_replies={
            "status": " M src/ok.py\n?? secrets.key\n"})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="denied"):
                agent.commit()
        kinds = [c[:2] for c in fake.runs]
        assert all("add" not in k for k in kinds)      # staged NOTHING

    def test_default_message_is_marked(self):
        agent = Ranger(cwd="/repo")
        fake = FakeRunner(git_replies={"status": " M a.py\n"})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            agent.commit()
        commit_argv = next(c for c in fake.runs if c[:2] == ["git", "commit"])
        assert "ranger: agent work" in commit_argv[3]

    def test_per_call_rails_replace_the_deny(self):
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        fake = FakeRunner(git_replies={
            "status": " M secrets.py\n"})
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            # replacing deny=[] clears the rail for THIS commit
            agent.commit(deny=[])
        assert ["git", "add", "-A", "--"] in [c for c in fake.runs]
