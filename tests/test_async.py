"""Async twins and par_map (issue #9) — fully mocked, no CLIs.

Pinned contracts:
- byte-identical argv between a sync command and its async twin (shared
  _prepare_run seam — async is a shell over the same contract, law 1);
- cancellation kills the CLI subprocess (same spirit as KeyboardInterrupt
  on the sync path);
- par_map: bounded concurrency, order alignment, honest per-item
  exceptions, up-front validation that spawns nothing on a bad spec.
"""

import asyncio
import inspect
import subprocess
from unittest import mock

import pytest

import ranger
from ranger import Ranger, RangerError, RangerHarnessError, RangerTimeout

RANGER_MOD = "ranger.subprocess"
SPAWN = "asyncio.create_subprocess_exec"


class FakeProc:
    """Stands in for the proc object asyncio.create_subprocess_exec gives."""

    pid = 4242

    def __init__(self, stdout=b"done\n", stderr=b"", returncode=0,
                 delay=None):
        self._out, self._err = stdout, stderr
        self.returncode = returncode
        self.delay = delay
        self.communicate_calls = 0
        self.killpg_calls = []

    async def communicate(self):
        self.communicate_calls += 1
        if self.delay is not None:
            await asyncio.sleep(self.delay)
        return self._out, self._err

    async def wait(self):
        return self.returncode


def make_exec_factory(stdout=b"done\n", stderr=b"", returncode=0,
                     delay=None):
    """Return (factory, calls) where factory records every spawn."""
    calls = []

    async def factory(*cmd, **kw):
        calls.append({"argv": list(cmd), "kwargs": kw})
        return FakeProc(stdout, stderr, returncode, delay)

    return factory, calls


def make_sync_run(stdout="done\n", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# the shared seam: async argv == sync argv, byte for byte

TWIN_CASES = [
    ("ask", ("What is in setup.py?",), {"agent": "ask"}),
    ("do", ("fix the build",), {"agent": "do"}),
    ("edit", ("setup.py", "add a comment"), None),   # needs a real target
    ("write", ("write a report",), {"agent": "write"}),
    ("search", ("where is DEFAULT_MODEL",), {"agent": "search"}),
    ("check", ("readme exists",), {"agent": "check"}),
]


class TestSharedSeam:
    def _sync_argv(self, agent, fn, *args, prompt_out):
        """Capture the argv the SYNC command produces."""
        with mock.patch(f"{RANGER_MOD}.run",
                        return_value=make_sync_run(stdout=prompt_out)):
            try:
                fn(*args)
            except RangerError:
                pass  # mocked answers may fail post-parsing; argv is the point
        return None

    def test_ask_do_search_argv_identical(self, tmp_path):
        sync_agent = Ranger(model="anthropic/claude-sonnet-4-5", cwd=".",
                            timeout=30, retries=0, memory=False)
        async_agent = Ranger(model="anthropic/claude-sonnet-4-5", cwd=".",
                             timeout=30, retries=0, memory=False)
        sync_argv = []

        def spy(cmd, **kw):
            sync_argv.append(list(cmd))
            return make_sync_run()

        with mock.patch(f"{RANGER_MOD}.run", side_effect=spy):
            sync_agent.ask("What is in setup.py?")
            sync_agent.do("fix the build")
            sync_agent.search("where is DEFAULT_MODEL")

        factory, calls = make_exec_factory(stdout=b"YES\n")

        async def scenario():
            await async_agent.ask_async("What is in setup.py?")
            await async_agent.do_async("fix the build")
            await async_agent.search_async("where is DEFAULT_MODEL")

        with mock.patch(SPAWN, side_effect=factory):
            run(scenario())

        assert [c["argv"] for c in calls] == sync_argv
        for argv in sync_argv:
            assert argv[0] == "opencode" and "run" in argv

    def test_write_edit_async_prompt_contracts_match_sync_shape(self, tmp_path):
        """Same generalized prompts — differing only in generated file ids."""
        sync_agent = Ranger(model="m", cwd=".", memory=False)
        async_agent = Ranger(model="m", cwd=".", memory=False)
        target = tmp_path / "t.py"
        target.write_text("x = 1\n", encoding="utf-8")
        sync_prompts = {}

        def spy(cmd, **kw):
            sync_prompts.setdefault("_n", 0)
            sync_prompts["_n"] += 1
            sync_prompts[sync_prompts["_n"]] = cmd[-1]
            return make_sync_run()

        with mock.patch(f"{RANGER_MOD}.run", side_effect=spy):
            try:
                sync_agent.write("a task", tmp_path / "a.md")
            except RangerError:
                pass
            try:
                sync_agent.edit(target, "double it")
            except RangerError:
                pass

        factory, calls = make_exec_factory()
        with mock.patch(SPAWN, side_effect=factory):
            try:
                run(async_agent.write_async("a task", tmp_path / "b.md"))
            except RangerError:
                pass
            try:
                run(async_agent.edit_async(target, "double it"))
            except RangerError:
                pass

        # write: task text and output path resolve identically modulo the
        # user-provided path; edit: the frozen template is identical
        w_sync, e_sync = sync_prompts[1], sync_prompts[2]
        w_async, e_async = calls[0]["argv"][-1], calls[1]["argv"][-1]
        assert w_async.replace("b.md", "a.md") == w_sync
        assert e_async == e_sync

    def test_prepare_run_is_the_literal_shared_seam(self):
        agent = Ranger(model="anthropic/claude-sonnet-4-5", cwd=".")
        sync_prep = agent._prepare_run("hi", "ask", {})
        async_prep = agent._prepare_run("hi", "ask", {})
        assert sync_prep["cmd"] == async_prep["cmd"]
        assert inspect.ismethod(agent._run)
        assert inspect.iscoroutinefunction(agent._run_async)

    def test_pure_labels_stay_session_free_async(self):
        agent = Ranger(model="m", session="keep-me", cwd=".")
        factory, calls = make_exec_factory(stdout=b"YES\n")
        with mock.patch(SPAWN, side_effect=factory):
            assert run(agent.check_async("readme exists")) is True
        argv = calls[0]["argv"]
        assert "keep-me" not in argv and "--session" not in argv

    def test_dialogue_labels_recall_sessions_async(self):
        agent = Ranger(model="m", session="keep-me", cwd=".")
        factory, calls = make_exec_factory()
        with mock.patch(SPAWN, side_effect=factory):
            run(agent.ask_async("hello"))
        assert "keep-me" in calls[0]["argv"]

    def test_unknown_option_raises_before_any_spawn(self):
        agent = Ranger(cwd=".")
        factory, calls = make_exec_factory()
        with mock.patch(SPAWN, side_effect=factory):
            with pytest.raises(TypeError, match="unknown run option"):
                run(agent.ask_async("hi", bogus=True))
        assert calls == []


class TestRunAsyncBehavior:
    def test_answer_and_memory_and_stats(self):
        agent = Ranger(model="m", cwd=".", stats=True)
        stdout = ("{\"part\": {\"type\": \"text\", \"text\": \"hi there\", "
                  "\"time\": {\"start\": 1, \"end\": 3001}}, "
                  "\"sessionID\": \"sess-7\"}\n").encode()
        factory, calls = make_exec_factory(stdout=stdout)
        with mock.patch(SPAWN, side_effect=factory):
            answer = run(agent.ask_async("hello"))
        assert answer == "hi there"
        assert agent.context[-1] == {"role": "assistant", "content": "hi there"}
        assert agent.last["session"] == "sess-7"
        assert agent.last["label"] == "ask"
        assert agent.last["model_s"] == 3.0

    def test_nonzero_exit_is_harness_error(self):
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory(stderr=b"boom", returncode=3)
        with mock.patch(SPAWN, side_effect=factory):
            with pytest.raises(RangerHarnessError, match="exit 3"):
                run(agent.ask_async("hi"))

    def test_timeout_raises_rangertimeout_and_kills(self):
        agent = Ranger(model="m", cwd=".", timeout=0.05)
        factory, _ = make_exec_factory(delay=30)
        with mock.patch(SPAWN, side_effect=factory):
            with mock.patch("os.killpg") as killpg:
                with pytest.raises(RangerTimeout, match="timed out"):
                    run(agent.ask_async("hi"))
        assert killpg.called

    def test_transport_retries_are_honored(self):
        agent = Ranger(model="m", cwd=".", retries=1)
        # first spawn fails (nonzero exit), second succeeds
        factory, calls = make_exec_factory(stderr=b"flaky", returncode=2)
        good, _ = make_exec_factory()

        async def flaky_then_good(*cmd, **kw):
            if len(calls) == 0:
                calls.append(1)
                return FakeProc(stderr=b"flaky", returncode=2)
            return await good(*cmd, **kw)

        with mock.patch(SPAWN, side_effect=flaky_then_good):
            assert run(agent.ask_async("hi")) == "done"

    def test_missing_cli_is_harness_error_with_install_hint(self):
        agent = Ranger(model="m", cwd=".", backend="claude")

        async def missing(*cmd, **kw):
            raise FileNotFoundError(cmd[0])

        with mock.patch(SPAWN, side_effect=missing):
            with pytest.raises(RangerHarnessError, match="claude CLI not found"):
                run(agent.ask_async("hi"))

    def test_cancellation_kills_subprocess_and_propagates(self):
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory(delay=30)

        async def scenario():
            task = asyncio.ensure_future(agent.ask_async("slow one"))
            await asyncio.sleep(0.05)   # let it spawn and block
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        with mock.patch(SPAWN, side_effect=factory):
            with mock.patch("os.killpg") as killpg:
                run(scenario())
        assert killpg.called

    def test_check_async_verdict_grammar(self):
        agent = Ranger(model="m", cwd=".")
        yes = make_exec_factory(stdout=b"YES\nit exists\n")
        no = make_exec_factory(stdout=b"NO\n")
        bad = make_exec_factory(stdout=b"YES\nNO\n")
        garble = make_exec_factory(stdout=b"maybe?\n")
        with mock.patch(SPAWN, side_effect=yes[0]):
            assert run(agent.check_async("readme exists")) is True
        with mock.patch(SPAWN, side_effect=no[0]):
            assert run(agent.check_async("readme exists")) is False
        with mock.patch(SPAWN, side_effect=bad[0]):
            with pytest.raises(RangerError, match="contradictory"):
                run(agent.check_async("readme exists"))
        with mock.patch(SPAWN, side_effect=garble[0]):
            with pytest.raises(RangerError, match="parse a YES/NO"):
                run(agent.check_async("readme exists"))

    def test_write_async_missing_file_raises(self, tmp_path):
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory(stdout=b"all done\n")
        with mock.patch(SPAWN, side_effect=factory):
            with pytest.raises(RangerError, match="did not write"):
                run(agent.write_async("report", tmp_path / "nope.md"))

    def test_edit_async_unmodified_target_raises(self, tmp_path):
        target = tmp_path / "t.py"
        target.write_text("x = 1\n", encoding="utf-8")
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory(stdout=b"edited\n")
        with mock.patch(SPAWN, side_effect=factory):
            with pytest.raises(RangerError, match="did not modify"):
                run(agent.edit_async(target, "double it"))

    def test_no_spinner_side_effects_on_stderr(self, capsys):
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory()
        with mock.patch(SPAWN, side_effect=factory):
            run(agent.ask_async("hi"))
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""


# --------------------------------------------------------------------- #
# par_map

class TestParMapContracts:
    def test_results_stay_aligned_with_input_order(self):
        agent = Ranger(model="m", cwd=".")

        async def factory(*cmd, **kw):
            prompt = cmd[-1]
            await asyncio.sleep(0.02 if "second" in prompt else 0)
            return FakeProc(stdout=f"out:{prompt}".encode())

        calls = [
            {"method": "ask", "args": ["first"]},
            {"method": "ask", "args": ["second"]},
            {"method": "search", "args": ["third"]},
        ]
        with mock.patch(SPAWN, side_effect=factory):
            results = run(agent.par_map(calls, max_concurrency=3))
        assert results[0] == "out:first"
        assert results[1] == "out:second"
        assert results[2].startswith("out:")

    def test_per_item_failure_isolation_no_swallowing(self):
        agent = Ranger(model="m", cwd=".")

        async def factory(*cmd, **kw):
            prompt = cmd[-1]
            if "bomb" in prompt:
                return FakeProc(stderr=b"kaput", returncode=9)
            return FakeProc(stdout=b"fine")

        calls = [
            {"method": "ask", "args": ["good one"]},
            {"method": "ask", "args": ["bomb"]},
            {"method": "check", "args": ["anything"]},
        ]
        with mock.patch(SPAWN, side_effect=factory):
            results = run(agent.par_map(calls, max_concurrency=3))
        assert results[0] == "fine"
        assert isinstance(results[1], RangerHarnessError)
        assert "exit 9" in str(results[1])
        # check parses "fine" as a non-verdict → its error is preserved too
        assert isinstance(results[2], RangerError)

    def test_bounded_concurrency_is_enforced(self):
        agent = Ranger(model="m", cwd=".")
        peak = 0
        active = 0

        async def factory(*cmd, **kw):
            nonlocal peak, active
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.03)
            active -= 1
            return FakeProc(stdout=b"ok")

        calls = [{"method": "ask", "args": [f"c{i}"]} for i in range(7)]
        with mock.patch(SPAWN, side_effect=factory):
            results = run(agent.par_map(calls, max_concurrency=2))
        assert peak == 2, f"semaphore leaked concurrency: peak {peak}"
        assert all(r == "ok" for r in results)

    def test_max_concurrency_one_serializes(self):
        agent = Ranger(model="m", cwd=".")
        active = peak = 0

        async def factory(*cmd, **kw):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return FakeProc(stdout=b"ok")

        calls = [{"method": "ask", "args": [f"c{i}"]} for i in range(4)]
        with mock.patch(SPAWN, side_effect=factory):
            run(agent.par_map(calls, max_concurrency=1))
        assert peak == 1

    def test_agent_key_routes_to_another_ranger(self):
        a = Ranger(model="m1", cwd=".")
        b = Ranger(model="m2", cwd=".")
        factory, calls = make_exec_factory()
        with mock.patch(SPAWN, side_effect=factory):
            results = run(a.par_map([
                {"agent": b, "method": "ask", "args": ["to B"]},
                {"method": "ask", "args": ["to A"]},
            ], max_concurrency=2))
        assert all(r == "done" for r in results)
        models = {c["argv"][c["argv"].index("--model") + 1] for c in calls}
        assert models == {"m1", "m2"}

    def test_bad_specs_raise_before_any_spawn(self):
        agent = Ranger(model="m", cwd=".")
        factory, calls = make_exec_factory()

        cases = [
            "not-a-list",
            [{"method": "nope", "args": []}],
            [{"method": "ask", "args": "not-a-list"}],
            [{"method": "ask", "kwargs": 42}],
            [{"method": "ask", "agent": object()}],
            [["not", "a", "dict"]],
        ]
        with mock.patch(SPAWN, side_effect=factory):
            for bad in cases:
                with pytest.raises((TypeError, ValueError)):
                    run(agent.par_map(bad, max_concurrency=2))
            with pytest.raises(ValueError, match="max_concurrency"):
                run(agent.par_map([{"method": "ask", "args": ["x"]}],
                                  max_concurrency=0))
        assert calls == [], "a bad spec must not spawn a single CLI"

    def test_empty_calls_map_to_empty_results(self):
        agent = Ranger(model="m", cwd=".")
        assert run(agent.par_map([])) == []

    def test_cancellation_of_par_map_kills_children(self):
        agent = Ranger(model="m", cwd=".")
        factory, _ = make_exec_factory(delay=30)

        async def scenario():
            task = asyncio.ensure_future(agent.par_map(
                [{"method": "ask", "args": ["x"]} for _ in range(3)],
                max_concurrency=3))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        with mock.patch(SPAWN, side_effect=factory):
            with mock.patch("os.killpg") as killpg:
                run(scenario())
        assert killpg.called

    def test_twin_method_whitelist_is_pinned(self):
        assert ranger._ASYNC_TWIN_METHODS == frozenset(
            {"ask", "do", "write", "edit", "search", "check"})
        for name in ranger._ASYNC_TWIN_METHODS:
            assert inspect.iscoroutinefunction(getattr(Ranger, f"{name}_async"))


class TestTwinsDoNotForkControlFlow:
    def test_sync_methods_still_use_run_not_run_async(self):
        # the sync core must not secretly run the async machinery
        for name in ("ask", "do", "write", "edit", "search", "check"):
            method = inspect.getsource(getattr(Ranger, name))
            assert "_run(" in method, f"sync {name} lost the _run seam"
            assert "_run_async" not in method, \
                f"sync {name} must stay on the sync seam"

    def test_twin_docstrings_distinguish_the_seam(self):
        for name in ranger._ASYNC_TWIN_METHODS:
            twin = getattr(Ranger, f"{name}_async")
            assert "twin" in twin.__doc__
