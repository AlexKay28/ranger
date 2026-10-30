"""Git snapshots & rollback (issue #7) — fully mocked, no real git.

The _git plumbing rides the same `ranger.subprocess.run` seam as the
harness runs; a dispatcher fakes git replies by argv[0]. Everything else
is flow truth: pre-round snapshots are best-effort, explicit calls raise
honestly, rollback_on_fail restores only when a snapshot exists.
"""

import subprocess
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError

RANGER_MOD = "ranger.subprocess"


class FakeGit:
    """Dispatches mocked subprocess.run replies: git vs harness."""

    def __init__(self, agent_replies=None, git_replies=None, git_fails=False):
        self.runs = []                 # every cmd seen, in order
        self.kws = []                  # kwargs per call (env etc.)
        self.agent_replies = list(agent_replies or [])
        # replies keyed by git SUBCOMMAND, overridable per test
        self.git_replies = {
            "rev-parse": ("/repo", 0),
            "add": ("", 0),
            "write-tree": ("TREE1", 0),
            "commit-tree": ("SHA1", 0),
            "update-ref": ("", 0),
            "diff": ("a.py\nb.py\n", 0),
            "ls-files": ("new1.py\nkept.py\n", 0),
            "ls-tree": ("kept.py\na.py\n", 0),
            "read-tree": ("", 0),
            "clean": ("", 0),
        }
        for k, v in (git_replies or {}).items():
            self.git_replies[k] = (v, 0) if isinstance(v, str) else v
        self.git_fails = git_fails     # True → rev-parse exit 128 (non-repo)

    def __call__(self, cmd, **kw):
        self.runs.append(list(cmd))
        self.kws.append(dict(kw))
        if cmd[0] != "git":
            reply = self.agent_replies.pop(0) if self.agent_replies else "ok\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")
        sub = cmd[1]
        if sub == "rev-parse" and self.git_fails:
            return subprocess.CompletedProcess(cmd, 128, stdout="",
                                               stderr="fatal: not a git repository")
        out, rc = self.git_replies[sub]
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")


def git_calls(fake):
    return [c for c in fake.runs if c[0] == "git"]


# --------------------------------------------------------------------- #
# snapshot()

class TestSnapshot:
    def test_needs_a_git_repository(self):
        agent = Ranger(cwd=".")
        fake = FakeGit(git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.snapshot("t1")

    def test_plumbing_shapes_and_temp_index(self):
        agent = Ranger(cwd="/repo")
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            snap = agent.snapshot("before-refactor")
        assert snap == {"tag": "before-refactor", "sha": "SHA1",
                        "tree": "TREE1", "root": "/repo"}
        argvs = git_calls(fake)
        assert argvs[0] == ["git", "rev-parse", "--show-toplevel"]
        assert argvs[1] == ["git", "add", "-A", "--"]
        assert argvs[2] == ["git", "write-tree"]
        assert argvs[3][:2] == ["git", "commit-tree"]
        assert "TREE1" in argvs[3] and "ranger snapshot before-refactor" in argvs[3]
        assert argvs[4] == ["git", "update-ref",
                            "refs/ranger/snapshots/before-refactor", "SHA1"]
        # the index used is TEMPORARY — the real index is never touched
        add_kw = fake.kws[1]
        assert add_kw["env"]["GIT_INDEX_FILE"].startswith("/repo/.git/ranger-index-")
        assert agent.snapshot_log == [
            {"tag": "before-refactor", "sha": "SHA1", "tree": "TREE1",
             "time": agent.snapshot_log[0]["time"]}]

    def test_auto_tags_increment(self):
        agent = Ranger(cwd="/repo")
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            agent.snapshot()
            agent.snapshot()
        assert [s["tag"] for s in agent.snapshot_log] == ["snap-1", "snap-2"]

    def test_tag_validation_and_uniqueness(self):
        agent = Ranger(cwd="/repo")
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            agent.snapshot("t1")
            with pytest.raises(ValueError, match="already used"):
                agent.snapshot("t1")
            for bad in ("", "has spaces", "..", "-lead", "ok; rm -rf"):
                with pytest.raises(ValueError, match="invalid snapshot tag"):
                    agent.snapshot(bad)

    def test_temp_index_env_is_isolated(self):
        agent = Ranger(cwd="/repo")
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            agent.snapshot("t")
        git_adds = [c for c in fake.runs if c[:3] == ["git", "add", "-A"]]
        kw = None
        # env flows through kwargs on every call; assert via call capture
        assert git_adds, "snapshot must run git add -A on the temp index"


# --------------------------------------------------------------------- #
# rollback()

class TestRollback:
    def test_no_snapshot_is_honest_refusal(self):
        agent = Ranger(cwd=".")
        with mock.patch(f"{RANGER_MOD}.run"):
            with pytest.raises(RangerError, match="no snapshot recorded"):
                agent.rollback()

    def test_unknown_tag_is_honest_refusal(self):
        agent = Ranger(cwd=".")
        agent.snapshot_log.append({"tag": "real", "sha": "S", "tree": "T",
                                   "time": 0.0})
        with mock.patch(f"{RANGER_MOD}.run"):
            with pytest.raises(RangerError, match="unknown snapshot tag"):
                agent.rollback("ghost")

    def test_restore_shapes_and_restored_list(self):
        agent = Ranger(cwd="/repo")
        agent.snapshot_log.append({"tag": "t1", "sha": "SHA1", "tree": "TREE1",
                                   "time": 0.0})
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            rb = agent.rollback("t1")
        assert rb["tag"] == "t1" and rb["sha"] == "SHA1"
        assert rb["restored"] == ["a.py", "b.py", "new1.py"]
        argvs = git_calls(fake)
        # diff vs the snapshot decides the "restored" report — BEFORE restoring
        assert ["git", "diff", "--name-only", "SHA1"] in argvs
        assert ["git", "ls-files", "--others", "--exclude-standard"] in argvs
        assert ["git", "ls-tree", "-r", "--name-only", "TREE1"] in argvs
        # the rewind: index+worktree <- snapshot tree, HEAD untouched
        assert ["git", "read-tree", "--reset", "-u", "TREE1"] in argvs
        # leftovers die by exact path, never a shotgun clean
        assert ["git", "clean", "-fd", "--", "new1.py"] in argvs
        assert not any(c[:2] == ["git", "reset"] for c in argvs)
        assert not any("checkout" in c for c in argvs)

    def test_rollback_to_last_snapshot_by_default(self):
        agent = Ranger(cwd="/repo")
        agent.snapshot_log.append({"tag": "older", "sha": "S1", "tree": "T1",
                                   "time": 0.0})
        agent.snapshot_log.append({"tag": "newer", "sha": "S2", "tree": "T2",
                                   "time": 1.0})
        fake = FakeGit()
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            rb = agent.rollback()
        assert rb["tag"] == "newer"
        assert ["git", "read-tree", "--reset", "-u", "T2"] in git_calls(fake)


# --------------------------------------------------------------------- #
# best-effort hooks and loop integration

class TestAutoSnapshotAndLoops:
    def test_snapshots_off_means_no_git_calls(self):
        agent = Ranger(cwd=".", snapshots=False)
        fake = FakeGit(agent_replies=["did it\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("fix things") == "did it"
        assert git_calls(fake) == []
        assert len(fake.runs) == 1 and fake.runs[0][0] == "opencode"

    def test_do_snapshots_best_effort(self):
        agent = Ranger(cwd="/repo", snapshots=True)
        fake = FakeGit(agent_replies=["did it\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("fix things") == "did it"
        assert argv_of(fake, "git", "update-ref")
        assert [s["tag"] for s in agent.snapshot_log] == ["pre-do-1"]

    def test_do_survives_non_git_cwd(self):
        agent = Ranger(cwd=".", snapshots=True)
        fake = FakeGit(agent_replies=["did it\n"], git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            assert agent.do("fix things") == "did it"   # never claimed
        assert agent.snapshot_log == []

    def test_until_rollback_on_fail_restores_tree(self):
        agent = Ranger(cwd="/repo", timeout=30, retries=0)
        # agent answers in order: pre-check NO, ask step, do report, NO
        fake = FakeGit(agent_replies=["NO\n", "one more step\n",
                                      "changed stuff\n", "NO\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.until("goal", max_iter=1, condition="c",
                                 rollback_on_fail=True)
        assert result["achieved"] is False
        assert result["rolled_back"] is True
        assert result["rollback"]["tag"] == result["rollback"]["tag"].strip()
        assert result["rollback"]["restored"] == ["a.py", "b.py", "new1.py"]
        assert argv_of(fake, "git", "read-tree")
        # the snapshot predates round 1: update-ref arrives before the ask
        assert idx_of(fake, "git", "update-ref") < idx_of_agent_call(fake, 2)

    def test_until_rollback_on_fail_without_git_is_honest(self):
        agent = Ranger(cwd="/somewhere", timeout=30, retries=0)
        fake = FakeGit(agent_replies=["NO\n", "step\n", "report\n", "NO\n"],
                       git_fails=True)
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.until("goal", max_iter=1, condition="c",
                                 rollback_on_fail=True)
        assert result["achieved"] is False
        assert "rolled_back" not in result       # nothing was claimed
        assert "rollback" not in result

    def test_until_green_never_rolls_back(self):
        agent = Ranger(cwd="/repo", timeout=30, retries=0)
        fake = FakeGit(agent_replies=["NO\n", "step\n", "report\n", "YES\n"])
        with mock.patch(f"{RANGER_MOD}.run", side_effect=fake):
            result = agent.until("goal", max_iter=1, condition="c",
                                 rollback_on_fail=True)
        assert result["achieved"] is True
        assert "rolled_back" not in result
        assert not any("read-tree" in c for c in git_calls(fake))


def argv_of(fake, *prefix):
    for c in fake.runs:
        if c[:len(prefix)] == list(prefix):
            return c
    return None


def idx_of(fake, *prefix):
    for i, c in enumerate(fake.runs):
        if c[:len(prefix)] == list(prefix):
            return i
    return -1


def idx_of_agent_call(fake, n):
    agent_calls = [i for i, c in enumerate(fake.runs) if c[0] != "git"]
    return agent_calls[n - 1] if len(agent_calls) >= n else -1
