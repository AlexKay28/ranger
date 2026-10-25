"""Reliability of the exception taxonomy.

RangerTimeout and RangerHarnessError are RangerError subclasses, so the
public API stays backward compatible: `except RangerError` still catches
everything. Transport failures raise RangerHarnessError while
prompt-contract failures (unparseable check() verdicts, missing write()
files) keep raising plain RangerError. All subprocess calls are mocked —
no live harness runs.
"""

import logging
import subprocess
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError, RangerHarnessError, RangerTimeout


def fake_run(stdout: str, stderr: str = "", returncode: int = 0):
    """Mock subprocess.run result for the ranger.subprocess.run seam."""
    return subprocess.CompletedProcess(
        args=["mock"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestTaxonomy:
    def test_subclass_relations(self):
        assert issubclass(RangerError, RuntimeError)
        assert issubclass(RangerTimeout, RangerError)
        assert issubclass(RangerHarnessError, RangerError)

    def test_exported_in_all(self):
        for name in ("RangerError", "RangerTimeout", "RangerHarnessError"):
            assert name in ranger.__all__
            assert getattr(ranger, name) is not None

    def test_catching_base_still_works(self):
        """except RangerError must keep catching subclass raises."""
        agent = Ranger(cwd=".")
        with mock.patch("ranger.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RangerError):
                agent.ask("hello")


class TestHarnessFailures:
    def test_missing_cli_raises_harness_error(self):
        agent = Ranger(cwd=".")
        with mock.patch("ranger.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RangerHarnessError, match="CLI not found"):
                agent.ask("hello")

    def test_nonzero_exit_raises_harness_error(self):
        agent = Ranger(cwd=".")
        with mock.patch(
            "ranger.subprocess.run",
            return_value=fake_run("", stderr="boom", returncode=3),
        ):
            with pytest.raises(RangerHarnessError, match="exit 3"):
                agent.ask("hello")

    def test_spawn_oserror_raises_harness_error(self):
        agent = Ranger(cwd=".")
        with mock.patch("ranger.subprocess.run", side_effect=OSError("no exec")):
            with pytest.raises(RangerHarnessError, match="could not be spawned"):
                agent.ask("hello")

    def test_timeout_raises_ranger_timeout(self):
        agent = Ranger(cwd=".", timeout=5)
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5),
        ):
            with pytest.raises(RangerTimeout, match="timed out after 5"):
                agent.ask("hello")


class TestContractFailuresStayPlain:
    def test_unparseable_check_verdict_is_plain_ranger_error(self):
        agent = Ranger(cwd=".")
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("Probably fine?")
        ):
            with pytest.raises(RangerError, match="YES/NO") as exc_info:
                agent.check("all tests pass")
        # plain contract failure: not a timeout, not a harness failure
        assert not isinstance(exc_info.value, RangerTimeout)
        assert not isinstance(exc_info.value, RangerHarnessError)


class TestRetries:
    def test_retries_survives_failing_then_succeeding_transport(self):
        agent = Ranger(cwd=".", retries=2)
        outcomes = [
            fake_run("", stderr="boom", returncode=1),
            fake_run("all good"),
        ]
        with mock.patch("ranger.subprocess.run", side_effect=outcomes):
            assert agent.ask("hello") == "all good"
        # exactly two transport attempts: one failure, one success
        assert len(outcomes) == 2

    def test_retries_zero_raises_immediately(self):
        agent = Ranger(cwd=".", retries=0)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("", stderr="x", returncode=1)
        ) as run_mock:
            with pytest.raises(RangerHarnessError):
                agent.ask("hello")
        run_mock.assert_called_once()

    def test_retries_exhausted_raises(self):
        agent = Ranger(cwd=".", retries=2)
        with mock.patch(
            "ranger.subprocess.run",
            side_effect=[fake_run("", stderr="x", returncode=1)] * 3,
        ) as run_mock:
            with pytest.raises(RangerHarnessError):
                agent.ask("hello")
        # 1 initial attempt + 2 retries
        assert run_mock.call_count == 3

    def test_per_call_retry_override(self):
        agent = Ranger(cwd=".")
        outcomes = [
            fake_run("", stderr="x", returncode=1),
            fake_run("recovered"),
        ]
        with mock.patch("ranger.subprocess.run", side_effect=outcomes):
            assert agent.ask("hello", retries=1) == "recovered"

    def test_retry_on_timeout(self):
        agent = Ranger(cwd=".", timeout=5, retries=1)
        outcomes = [
            subprocess.TimeoutExpired(cmd="x", timeout=5),
            fake_run("made it"),
        ]
        with mock.patch("ranger.subprocess.run", side_effect=outcomes):
            assert agent.ask("hello") == "made it"

    def test_contract_failure_never_retries(self):
        agent = Ranger(cwd=".", retries=3)
        with mock.patch(
            "ranger.subprocess.run", return_value=fake_run("Probably fine?")
        ) as run_mock:
            with pytest.raises(RangerError) as exc_info:
                agent.check("all tests pass")
        # immediate raise — prompt-contract failures consume no retries
        run_mock.assert_called_once()
        assert not isinstance(exc_info.value, (RangerTimeout, RangerHarnessError))
        assert type(exc_info.value) is RangerError


class TestLogging:
    """Stdlib logging: DEBUG per run, INFO per loop iteration.

    ranger configures NO handlers and never writes log output to the
    pretty stderr spinner UI; records go to the 'ranger' logger only.
    """

    def test_module_logger_is_ranger(self):
        assert ranger._LOG is logging.getLogger("ranger")
        assert not logging.getLogger("ranger").handlers  # no handlers wired

    def test_one_debug_record_per_run(self, caplog):
        """One DEBUG record at run start and one at run finish, per command."""
        agent = Ranger(cwd=".")
        with caplog.at_level(logging.DEBUG, logger="ranger"):
            with mock.patch(
                "ranger.subprocess.run", return_value=fake_run("hello back")
            ):
                assert agent.ask("hi") == "hello back"
        debugs = [r.getMessage() for r in caplog.records
                  if r.name == "ranger" and r.levelno == logging.DEBUG]
        assert len(debugs) == 2, debugs
        assert sum(m.startswith("run start") for m in debugs) == 1
        assert sum(m.startswith("run finish") for m in debugs) == 1

    def test_debug_start_and_finish_records(self, caplog):
        """Run start/finish both carry model, command label and duration."""
        agent = Ranger(cwd=".")
        with caplog.at_level(logging.DEBUG, logger="ranger"):
            with mock.patch(
                "ranger.subprocess.run", return_value=fake_run("ok")
            ):
                agent.do("write a file")
        messages = [r.getMessage() for r in caplog.records
                    if r.name == "ranger"]
        starts = [m for m in messages if m.startswith("run start")]
        finishes = [m for m in messages if m.startswith("run finish")]
        assert len(starts) == 1 and len(finishes) == 1
        assert "label=do" in starts[0] and "model=" in starts[0]
        assert "label=do" in finishes[0] and "duration=" in finishes[0]

    def test_one_info_record_per_until_iteration(self, caplog):
        """Each until() iteration emits exactly one INFO record."""
        agent = Ranger(cwd=".")
        ok_flags = iter([False, False, True])   # pre-check, iter 1, iter 2

        def fake_gate(cmd, timeout=None):
            return next(ok_flags)

        with caplog.at_level(logging.INFO, logger="ranger"):
            outs = [fake_run("step: fix the parser test"),      # ask() iter 1
                    fake_run("fixed the parser"),               # do()  iter 1
                    fake_run("step: add a regression test"),     # ask() iter 2
                    fake_run("added the test")]                 # do()  iter 2
            with mock.patch("ranger.subprocess.run", side_effect=outs), \
                    mock.patch.object(Ranger, "gate",
                                      side_effect=fake_gate) as g:
                result = agent.until(
                    "make tests pass",
                    gate_cmd="python -m pytest -q",
                    max_iter=2,
                )
        assert result["achieved"] is True
        assert g.call_count == 3   # vacuous pre-check + two work gates
        infos = [r for r in caplog.records
                 if r.name == "ranger" and r.levelno == logging.INFO]
        assert len(infos) == 2, [r.getMessage() for r in infos]
        assert "iteration 1/2" in infos[0].getMessage()
        assert "iteration 2/2" in infos[1].getMessage()
        assert "gate(gate_cmd)" in infos[0].getMessage()
    def test_info_record_per_refine_with_iteration(self, caplog):
        """Each refine_with() round emits one INFO record with the verdict."""
        builder = Ranger(cwd=".")
        critic = Ranger(cwd=".")
        review_results = iter([
            {"passed": False, "verdict": "REJECT",
             "findings": "no test", "changes": "add a test"},
            {"passed": True, "verdict": "APPROVE",
             "findings": "test present", "changes": "none"},
        ])
        with caplog.at_level(logging.INFO, logger="ranger"):
            with mock.patch(
                "ranger.subprocess.run", return_value=fake_run("work done")
            ), mock.patch.object(
                Ranger, "review", side_effect=lambda *a, **k: next(review_results)
            ):
                outcome = builder.refine_with(critic, "add a test",
                                              max_iter=2)
        assert outcome["approved"] is True
        infos = [r for r in caplog.records
                 if r.name == "ranger" and r.levelno == logging.INFO]
        assert len(infos) == 2, [r.getMessage() for r in infos]
        assert "refine_with iteration 1/2 · verdict=REJECT" == infos[0].getMessage()
        assert "refine_with iteration 2/2 · verdict=APPROVE" == infos[1].getMessage()

    def test_no_log_writes_to_spinner_ui(self):
        """Logging configures no handlers; the pretty UI path is untouched."""
        logger = logging.getLogger("ranger")
        assert logger.handlers == []



class TestVacuousGateDetection:
    """until() must not claim an agent win over a gate that was green
    before any work — run 1 of the issue-#1 experiment false-greened
    exactly this way. Honesty rule: pre-check the gate, report
    already_green instead of a fake 1-iteration success.
    """

    def test_green_gate_cmd_never_runs_the_agent(self):
        """Gate green before iteration 1 -> zero agent work, already_green."""
        agent = Ranger(cwd=".")
        with mock.patch.object(Ranger, "gate", return_value=True) as g, \
                mock.patch("ranger.subprocess.run") as run_mock:
            out = agent.until("make tests pass",
                              gate_cmd="true", max_iter=3)
        assert out["achieved"] is True
        assert out["iterations"] == 0
        assert out["already_green"] is True
        assert out["steps"] == []
        g.assert_called_once()          # the pre-check, and nothing else
        run_mock.assert_not_called()    # no ask/do model runs happened

    def test_green_condition_precheck_reports_already_green(self):
        agent = Ranger(cwd=".")
        with mock.patch.object(Ranger, "check", return_value=True) as c, \
                mock.patch("ranger.subprocess.run") as run_mock:
            out = agent.until("goal already true",
                              condition="is it true?", max_iter=3)
        assert out["already_green"] is True and out["iterations"] == 0
        c.assert_called_once()
        run_mock.assert_not_called()

    def test_red_gate_precheck_proceeds_to_work_normally(self):
        """A red pre-check costs one gate run, then the loop proceeds."""
        agent = Ranger(cwd=".")
        gate_flags = iter([False, True])       # pre-check red, then green
        def fake_gate(cmd, timeout=None):
            return next(gate_flags)
        outs = [fake_run("step: fix it"),        # ask() iteration 1
                fake_run("fixed it")]            # do()  iteration 1
        with mock.patch.object(Ranger, "gate",
                               side_effect=fake_gate) as g, \
                mock.patch("ranger.subprocess.run", side_effect=outs):
            out = agent.until("make tests pass",
                              gate_cmd="pytest", max_iter=2)
        assert out["achieved"] is True and out["iterations"] == 1
        assert out.get("already_green") is not True
        assert g.call_count == 2               # pre-check + iteration 1

    def test_no_already_green_key_on_real_work(self):
        """Normal (non-vacuous) achievement keys stay backward compatible."""
        agent = Ranger(cwd=".")
        gate_flags = iter([False, True])
        def fake_gate(cmd, timeout=None):
            return next(gate_flags)
        outs = [fake_run("step"), fake_run("done")]
        with mock.patch.object(Ranger, "gate", side_effect=fake_gate), \
                mock.patch("ranger.subprocess.run", side_effect=outs):
            out = agent.until("goal", gate_cmd="x", max_iter=1)
        assert "already_green" not in out
        assert out["achieved"] is True and out["iterations"] == 1
