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

from _fakes import FakePopen, git_sub, harness_and_git

RANGER_MOD = "ranger.subprocess"


class FakeRunner:
    """One seam, two voices: git plumbing vs the harness CLI run."""

    def __init__(self, agent_replies=None, git_replies=None, git_fails=False):
        self.runs = []          # every cmd, in order
        self.agent_replies = list(agent_replies or [])
        # issue #25: parsed git calls answer in `status --porcelain -z`
        # form now — NUL-terminated records, no quoting/renames arrows
        self.git_replies = {
            "rev-parse": "/repo\n",
            "status": " M src/ok.py\x00",
        }
        self.git_replies.update(git_replies or {})
        self.git_fails = git_fails

    def __call__(self, cmd, **kw):
        self.runs.append(list(cmd))
        if cmd[0] == "git":
            sub = git_sub(cmd)
            if sub == "rev-parse" and self.git_fails:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="fatal: not a git repository")
            reply = self.git_replies.get(sub, "")
            if isinstance(reply, list):
                # a SEQUENCE of answers, in call order (pre-run baseline
                # snapshot -> post-run delta check consume two statuses;
                # the last one repeats for any further call)
                reply = reply.pop(0) if len(reply) > 1 else reply[0]
            return subprocess.CompletedProcess(
                cmd, 0, stdout=reply, stderr="")
        reply = self.agent_replies.pop(0) if self.agent_replies else "ok\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")


def fake_harness(stdout="done"):
    return FakePopen(stdout=stdout)


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
        with harness_and_git(fake):
            for bad in ({"allow": "src/**"}, {"deny": 42},
                        {"dry_run": "yes"}, {"allow": [42]}):
                with pytest.raises((TypeError, ValueError)):
                    agent.do("goal", **bad)
                with pytest.raises((TypeError, ValueError)):
                    agent.ask("q", **bad)   # shared seam validates too
        assert fake.runs == []

    def test_unknown_keywords_still_raise(self):
        agent = Ranger(cwd=".")
        with mock.patch(f"{RANGER_MOD}.run") as gitrun, \
             mock.patch("ranger._engine._Popen") as spawn:
            with pytest.raises(TypeError, match="unknown run option"):
                agent.do("goal", alow=["src/**"])   # typo: loud, not silent
        gitrun.assert_not_called()      # neither seam ever spawned
        spawn.assert_not_called()

    def test_unknown_keyword_beats_the_rails_git_probe(self):
        # second-pass audit: with rails ACTIVE, do() used to run the
        # rev-parse verifiability probe BEFORE the seam's TypeError —
        # validation must precede any outside-world touch
        agent = Ranger(cwd=".", allow=["src/**"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(TypeError, match="unknown run option"):
                agent.do("goal", badkey=1)
        assert fake.runs == []     # no git probe, no snapshot, no spawn


# --------------------------------------------------------------------- #
# edit()/write(): known targets — pre-spawn path predicates

class TestTargetRails:
    def test_edit_denied_path_never_spawns(self, tmp_path):
        target = tmp_path / "secrets.env"
        target.write_text("k=v", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, deny=["**/secrets*"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="denied by the safety rails"):
                agent.edit(target, "add a comment")
        assert fake.runs == []          # law 4: refused BEFORE the spawn

    def test_edit_outside_allow_refused_before_spawn(self, tmp_path):
        target = tmp_path / "notes" / "other.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="outside the allow"):
                agent.edit(target, "bump")
        assert fake.runs == []

    def test_edit_allowed_target_runs_once(self, tmp_path):
        target = tmp_path / "src" / "mod.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["**/src/**"])
        with mock.patch("ranger._engine._Popen") as run:
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
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="denied"):
                agent.edit(target, "bump")
        assert fake.runs == []

    def test_write_path_respects_rails(self, tmp_path):
        agent = Ranger(cwd=tmp_path, deny=["**/private*"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="denied"):
                agent.write("report", path=tmp_path / "private.md")
        assert fake.runs == []

    def test_edit_cwd_relative_deny_form_is_enforced(self, tmp_path):
        """audit fix: `deny=["secrets/**"]` must refuse edit() on the
        matching cwd-RELATIVE target — without root in the assert the
        absolute target only matched absolute glob forms (a bypass)."""
        target = tmp_path / "secrets" / "x.py"
        target.parent.mkdir()
        target.write_text("k=v", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, deny=["secrets/**"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="denied"):
                agent.edit("secrets/x.py", "bump")
        assert fake.runs == []          # refused BEFORE the spawn

    def test_edit_cwd_relative_allow_form_permits(self, tmp_path):
        target = tmp_path / "src" / "x.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness()
            # the run happens; the mtime postcheck then reports the mock
            # never touched the file — allowed, exactly one spawn
            with pytest.raises(RangerError, match="did not modify"):
                agent.edit("src/x.py", "bump")
        assert run.call_count == 1

    def test_write_cwd_relative_deny_form_is_enforced(self, tmp_path):
        agent = Ranger(cwd=tmp_path, deny=["secrets/**"])
        fake = FakeRunner()
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="denied"):
                agent.write("report", path="secrets/out.md")
        assert fake.runs == []

    def test_write_cwd_relative_allow_form_permits(self, tmp_path):
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        out = tmp_path / "src" / "report.md"
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness()
            # allowed run; the file postcheck then reports the mock
            # write never landed — one spawn, the rail did not refuse
            with pytest.raises(RangerError, match="did not write"):
                agent.write("report", path=out)
        assert run.call_count == 1

    def test_per_call_override_wins_over_ctor(self, tmp_path):
        target = tmp_path / "src" / "mod.py"
        target.parent.mkdir()
        target.write_text("x = 1", encoding="utf-8")
        agent = Ranger(cwd=tmp_path, allow=["src/**"])
        fake = FakeRunner()
        with harness_and_git(fake):
            # per-call allow REPLACES the ctor allow: this target is out
            with pytest.raises(RangerError, match="outside the allow"):
                agent.edit(target, "bump", allow=["docs/**"])
            # per-call deny REPLACES the ctor deny (nothing denied now)
            agent2 = Ranger(cwd=tmp_path, deny=["**/mod.py"])
            with mock.patch("ranger._engine._Popen") as run:
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
        with harness_and_git(fake):
            assert agent.do("goal") == "did it"
        assert len(fake.runs) == 1 and fake.runs[0][0] == "opencode"

    def test_rails_with_no_git_repo_refuse_up_front(self):
        agent = Ranger(cwd="/somewhere", deny=["**/.env"])
        fake = FakeRunner(git_fails=True)
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.do("goal")
        # the ONLY subprocess call was the verifiability probe: no
        # harness was ever spawned for an unverifiable mutation
        assert fake.runs == [["git", "rev-parse", "--show-toplevel"]]

    def test_do_post_run_violation_raises_naming_paths(self):
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        # issue #25: status answers are -z records (NUL-terminated);
        # pre-run baseline CLEAN, the run itself leaves the violation
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["",
                                        " M src/ok.py\x00?? secrets.key\x00"]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"secrets\.key"):
                agent.do("goal")
        kinds = [c[0] for c in fake.runs]
        # rev-parse probe -> pre-run baseline status -> harness round
        # -> post-run delta status check
        assert kinds == ["git", "git", "opencode", "git"]

    def test_do_allowed_paths_pass_quietly(self):
        agent = Ranger(cwd="/repo", allow=["src/**", "README*"])
        fake = FakeRunner(agent_replies=["did it\n"])
        with harness_and_git(fake):
            assert agent.do("goal") == "did it"

    def test_do_dry_run_skips_the_boundary_check(self):
        agent = Ranger(cwd="/somewhere", deny=["**/.env"])
        fake = FakeRunner(agent_replies=["here is the plan\n"])
        with harness_and_git(fake):
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
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="git rev-parse"):
                agent.until("goal", max_iter=2, condition="cond")
        kinds = [c[0] for c in fake.runs]
        # pre-check verdict + step ask ran; the do round died at its
        # verifiability probe — never spawned the harness
        assert kinds == ["opencode", "opencode", "git"]


# --------------------------------------------------------------------- #
# audit fix: do() rails judge the DELTA vs a pre-run baseline — never
# the repo's full current status

class TestDoBaselineDelta:
    """The post-run check captures a pre-run `{path: XY}` snapshot and
    flags only entries NEW to it or whose XY pair CHANGED. Pre-existing
    dirt outside the rails is no longer blamed on the agent."""

    def test_predirty_out_of_rails_files_are_not_blamed(self):
        # the repo was dirty BEFORE the run; the agent changed nothing
        # (identical status pre and post) — no false accusation
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        dirt = " M notes/old_dirt.py\x00?? legacy/scratch.txt\x00"
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status": dirt})
        with harness_and_git(fake):
            assert agent.do("goal") == "did it"

    def test_agent_touching_a_denied_path_in_the_delta_still_raises(self):
        # same pre-existing dirt, PLUS a new denied entry the agent made
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       [" M notes/old_dirt.py\x00",
                                        " M notes/old_dirt.py\x00"
                                        "?? secrets.key\x00"]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"secrets\.key"):
                agent.do("goal")

    def test_agent_creating_a_new_out_of_allow_path_raises(self):
        agent = Ranger(cwd="/repo", allow=["src/**"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       [" M src/ok.py\x00",
                                        " M src/ok.py\x00?? stray.txt\x00"]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"stray\.txt"):
                agent.do("goal")

    def test_status_change_in_the_delta_is_flagged(self):
        # a path present pre-run whose XY pair CHANGED (worktree edit
        # became a staged edit) counts as touched by the run — the
        # delta rule is path + XY, not path alone. The path is outside
        # allow both times, but only the CHANGED entry is judged.
        agent = Ranger(cwd="/repo", allow=["docs/**"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       [" M src/ok.py\x00",
                                        "M  src/ok.py\x00"]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"src/ok\.py"):
                agent.do("goal")

    def test_subdir_cwd_with_root_dirt_is_not_falsely_accused(self):
        # status is repo-wide from a subdirectory cwd; root-level dirt
        # outside the rails existed before the run and stays unblamed
        agent = Ranger(cwd="/repo/sub", deny=["**/secrets*"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={
                              "rev-parse": "/repo\n",
                              "status": " M top_dirt.py\x00?? notes/x\x00"})
        with harness_and_git(fake):
            assert agent.do("goal") == "did it"

    def test_same_status_predirty_retouch_is_the_stated_blind_spot(self):
        # honest limit of the delta rule: a file dirty pre-run (" M")
        # that the agent modifies AGAIN without changing its XY pair
        # is indistinguishable in porcelain status from pre-existing
        # dirt — documented, not silently claimed as checked
        agent = Ranger(cwd="/repo", deny=["**/secrets*"])
        dirty_denied = " M secrets/key.py\x00"
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status": dirty_denied})
        with harness_and_git(fake):
            # no raise: the (path, XY) delta is empty even though the
            # agent may have re-touched the pre-dirty denied file
            assert agent.do("goal") == "did it"


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
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness("planned changes: ...")
            report = agent.edit(target, "double it", dry_run=True)
        assert "planned changes" in report     # no "did not modify" error
        argv = run.call_args.args[0]
        assert argv[argv.index("--agent") + 1] == "plan"

    def test_write_dry_run_has_no_file_postcheck(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        out = tmp_path / "never.md"
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness("would write ...")
            assert agent.write("report", path=out, dry_run=True) == str(out)
        assert not out.is_file()               # nothing was applied

    def test_dry_run_policy_skips_write_edit_postchecks(self, tmp_path):
        """audit fix: with_config(dry_run=True) makes write()/edit()
        read-only for the RUN — the postchecks must resolve the SAME
        policy (instance-blind dry_run made every one fail loudly)."""
        agent = Ranger(cwd=tmp_path).with_config(dry_run=True)
        target = tmp_path / "t.py"
        target.write_text("x = 1", encoding="utf-8")
        out = tmp_path / "never.md"
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness("planned changes ...")
            assert agent.edit(target, "double it") == "planned changes ..."
            assert agent.write("report", path=out) == str(out)
        argv = run.call_args_list[0].args[0]
        assert argv[argv.index("--agent") + 1] == "plan"  # run was read-only
        # and the untouched targets prove it: no postcheck RangerError
        assert target.read_text(encoding="utf-8") == "x = 1"
        assert not out.is_file()

    def test_dry_run_costs_still_record(self, tmp_path):
        agent = Ranger(cwd=tmp_path)
        with mock.patch("ranger._engine._Popen") as run:
            run.return_value = fake_harness("plan")
            agent.do("goal", dry_run=True)
        assert agent.costs["calls"] == 1


# --------------------------------------------------------------------- #
# issue #25: `status --porcelain -z` records — renames, spaces, non-ASCII

# REAL bytes captured from a scratch repo (`R  deny_target.py\0deny_me.py\0`
# is what `git status --porcelain -z` emits for `git mv deny_me.py
# deny_target.py` — the NEW path first, then the old one; plain porcelain
# says `R  deny_me.py -> deny_target.py`). -z records are NUL-terminated
# and never quoted, even for `"another file.py"`.
RENAMED_STATUS_Z = (
    "R  deny_target.py\x00deny_me.py\x00"
    " M ok.py\x00"
    "?? another file.py\x00")

# REAL bytes captured with non-ASCII names and -z (no core.quotepath
# escapes: the ü renders as literal UTF-8, never "\303\274…").
UNICODE_STATUS_Z = " M ünïcode.py\x00?? new ünïcode2.py\x00"


class TestPorcelainZRecords:
    """do()'s post-run boundary parses -z records: a rename is checked
    on BOTH sides, and spaces/non-ASCII paths stay whole."""

    def test_rename_record_checks_the_new_path(self):
        agent = Ranger(cwd="/repo", deny=["**/deny_target.py"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["", RENAMED_STATUS_Z]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"deny_target\.py"):
                agent.do("goal")

    def test_rename_record_checks_the_old_path_too(self):
        # renaming AWAY from a denied path is as much a violation: the
        # old side of the `new\0old` pair must be checked too
        agent = Ranger(cwd="/repo", deny=["**/deny_me.py"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["", RENAMED_STATUS_Z]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"deny_me\.py"):
                agent.do("goal")

    def test_spaced_untracked_path_is_seen_whole(self):
        # "another file.py" — a path with a space — no longer splits on
        # the space: an allow=src/** rail flags the exact whole path
        agent = Ranger(cwd="/repo", allow=["src/**"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["", RENAMED_STATUS_Z]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match=r"another file\.py"):
                agent.do("goal")

    def test_admitting_rails_are_not_spooked_by_renames(self):
        # the same -z fixture under rails that admit every path: no
        # phantom `old -> new` path, no false positive, quiet pass
        agent = Ranger(cwd="/repo", allow=["**"], deny=["**/secrets*"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["", RENAMED_STATUS_Z]})
        with harness_and_git(fake):
            assert agent.do("goal") == "did it"

    def test_non_ascii_path_matches_literal_bytes(self):
        # quoting is off (-z + core.quotepath=false): ünïcode.py
        # matches a plain glob byte-for-byte, not a "\303\274" escape
        agent = Ranger(cwd="/repo", deny=["**/ünïcode.py"])
        fake = FakeRunner(agent_replies=["did it\n"],
                          git_replies={"status":
                                       ["", UNICODE_STATUS_Z]})
        with harness_and_git(fake):
            with pytest.raises(RangerError, match="ünïcode.py"):
                agent.do("goal")
