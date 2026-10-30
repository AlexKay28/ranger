"""The transport engine: run-option resolution, prompt composition, spawn/kill/complete pipelines for BOTH seams (sync subprocess.run, asyncio), the costs ledger."""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ._util import (DEFAULT_MODEL, _LOG, _NO_COLOR, _RESET, _COLORS, _c,
                    _clip, _interrupt_payload, _kill_tree,
                    _RUN_KEYS, _normalize_patterns,
                    _path_matches, RangerError, RangerTimeout,
                    RangerHarnessError, UI_NOTE_CLIP, UI_RETRY_CLIP)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)


def _warn_default_model():
    """Mock seam forwarder: the patchable guard lives on the package."""
    import ranger
    ranger._warn_default_model()


from ._backends import _BACKEND_CLASSES  # noqa: E402 (runs reference it)


def _spinner_cls():
    """Resolve _Spinner through the package at CALL time.

    Tests patch the package attribute ``ranger._Spinner`` — baking the
    class into this module would hide the attribute the mock seam targets.
    """
    import ranger
    return ranger._Spinner


class EngineMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    def _child_env(self, env: dict | None = None) -> dict | None:
        """Environment for child CLI processes.

        Full inherited ``os.environ`` (including secrets) extended with
        ``PWD=agent.cwd`` and the ``env`` overlay(s). A per-call ``env``
        merges OVER the per-instance ``env`` (same-key wins, unrelated
        keys survive) — it extends, never replaces. ``None`` overlays
        mean inherit everything untouched.
        """
        overlay: dict = dict(self.env) if self.env else {}
        if env:
            overlay.update(env)
        if self.cwd is None and not overlay:
            return None
        child = dict(os.environ)
        if self.cwd is not None:
            child["PWD"] = self.cwd
        if overlay:
            child.update(overlay)
        return child

    @property
    def costs(self) -> dict:
        """Cumulative cost/telemetry ledger across ALL completed calls.

        Law-4 state: explicit, Python-side, always recorded —
        `stats=True` is NOT required (it only switches the harness run
        into JSON mode for `last`; the ledger feeds on whatever
        telemetry any run happens to produce, plus prompt/answer sizes
        and wall time, which need no harness cooperation).

            {"calls": int,          # completed agent runs
             "chars_in": int,       # prompt characters sent, total
             "chars_out": int,      # answer characters received, total
             "tokens_in": None|int, # None until a backend reports tokens
             "tokens_out": None|int,
             "wall_s": float}       # summed subprocess wall time

        Per agent: a `debate`/`refine_with` partner keeps its own
        ledger — inspect each agent's `costs` separately. Reset (and
        collect) with `costs_reset()`. The returned dict is a copy;
        mutating it never touches the ledger.
        """
        return dict(self._costs)

    def costs_reset(self) -> dict:
        """Return the current ledger and zero it (bounded accounting).

        The classic "what did this loop cost?" idiom:

            agent.costs_reset()
            result = agent.until("make tests green", gate_cmd=...)
            print(result["iterations"], agent.costs)   # this loop only

        Failed and interrupted runs never record — `calls` counts
        completed agent runs only.
        """
        ledger = dict(self._costs)
        self._costs = {
            "calls": 0, "chars_in": 0, "chars_out": 0,
            "tokens_in": None, "tokens_out": None, "wall_s": 0.0,
        }
        return ledger

    def _record_costs(self, chars_in: int, chars_out: int,
                      info: dict | None, wall_s: float) -> None:
        """Merge one completed run into the ledger. Never raises."""
        c = self._costs
        c["calls"] += 1
        c["chars_in"] += chars_in
        c["chars_out"] += chars_out
        c["wall_s"] = round(c["wall_s"] + max(wall_s, 0.0), 2)
        if info:
            ti, to = info.get("input_tokens"), info.get("output_tokens")
            if ti is not None:
                c["tokens_in"] = (c["tokens_in"] or 0) + int(ti)
            if to is not None:
                c["tokens_out"] = (c["tokens_out"] or 0) + int(to)

    def _resolve_run_options(self, label: str, ov: dict) -> tuple:
        """Merge ctor + per-call run options into `o`; validate everything.

        Returns (opts, o, adapter, backend_name). Raises TypeError for
        unknown keywords / unknown backends / bad effort, and validates
        the safety-rail specs — all BEFORE any outside world is touched.
        """
        opts = {k: getattr(self, k) for k in _RUN_KEYS}
        opts.update({k: v for k, v in ov.items() if k in _RUN_KEYS})
        unknown = set(ov) - set(_RUN_KEYS)
        if unknown:
            raise TypeError(f"unknown run option(s): {', '.join(sorted(unknown))}")
        # safety-rail specs are validated on the shared seam too, so even
        # read-only commands reject a malformed spec before any spawn
        self._resolve_safety(ov)

        backend_name = opts["backend"]
        try:
            adapter = _BACKEND_CLASSES[backend_name]()
        except KeyError:
            raise TypeError(
                f"unknown backend {backend_name!r} (registered: "
                f"{', '.join(sorted(_BACKEND_CLASSES))})"
            ) from None

        o = dict(opts)
        o["cwd"] = self.cwd  # adapters reference it for native cd flags
        # law 4 corollary: fact commands run history-independent — the
        # harness session is continuation state, so drop it for pure labels
        if label in _PURE_LABELS:
            o["session"] = None
        # priority: per-call agent/mode beats constructor mode beats agent
        per_call_agent = ov.get("agent") or ov.get("mode")
        ctor_agent = opts.get("mode") or opts.get("agent")
        o["agent"] = per_call_agent or ctor_agent
        o["mode"] = None
        effort = (o["effort"] or "medium").lower()
        if effort not in ("low", "medium", "high"):
            raise TypeError(f"effort must be low|medium|high, got {effort!r}")
        # high effort implies thinking blocks / reasoning effort
        o["thinking"] = bool(o["thinking"] or effort == "high")
        return opts, o, adapter, backend_name

    def _effective_model(self, ov: dict, backend_name: str):
        """Model precedence: per-call > explicit ctor > env > backend.

        Resolved AFTER the effective backend is known so a per-call
        backend switch never inherits the wrong package default.
        """
        if "model" in ov:
            return ov["model"]
        if self._model_explicit is not None:
            return self._model_explicit
        env_model = os.environ.get("RANGER_MODEL")
        if env_model:
            return env_model
        if backend_name == "opencode":
            _warn_default_model()
            return DEFAULT_MODEL
        return None

    def _collect_skills(self, granted) -> tuple:
        """Split the skills allow-list into (prose_grants, skill_files).

        Existing files/dirs become attachment entries (native flag where
        the backend has one, inlined otherwise); anything else is prose —
        an operating grant injected into the prompt. Relative paths
        resolve against the AGENT's cwd, never the process cwd.
        """
        prose_grants: list[str] = []
        skill_files: list[Path] = []
        granted = granted or []
        if isinstance(granted, (str, Path)):
            granted = [granted]
        for entry in granted:
            p = Path(entry)
            if not p.is_absolute():
                # relative skill paths resolve against the AGENT's cwd —
                # the world the harness operates in — never the process cwd
                p = Path(self.cwd or str(Path.cwd())) / p
            if p.is_dir():
                found = sorted(p.glob("*.md"))
                if not found:
                    raise RangerError(f"skill directory has no markdown: {p}")
                skill_files.extend(found)
            elif p.is_file():
                skill_files.append(p)
            else:
                prose_grants.append(str(entry))
        return prose_grants, skill_files

    def _compose_prompt(self, prompt: str, o: dict, label: str,
                        use_memory: bool, prose_grants: "list[str]",
                        effort: str) -> str:
        """Recall block + skill grants + effort directives, in order.

        Context recall first (bounded by memory_budget), prose grants
        prepended AFTER recall so they can never be overwritten, the
        effort directive appended last.
        """
        full_prompt = prompt
        if use_memory and self.context and label not in _PURE_LABELS:
            budget = o.get("memory_budget") or self.memory_budget
            selected, total = [], 0
            for msg in reversed(self.context):
                total += len(msg["content"]) + 16
                if total > budget:
                    break
                selected.append(msg)
            selected.reverse()
            if selected:
                transcript = "\n\n".join(
                    f"[{m['role']}] {m['content']}" for m in selected
                )
                full_prompt = (
                    "## Previous interaction in this session\n"
                    + transcript
                    + "\n\n## Current request\n"
                    + full_prompt
                )
        if prose_grants:
            full_prompt = (
                "## Allowed skills / operating grants for this task\n"
                + "\n".join(f"- {g}" for g in prose_grants)
                + "\n\n"
                + full_prompt
            )
        if effort == "low":
            full_prompt += "\n\n(Effort directive: low — be brief, minimal ceremony.)"
        elif effort == "high":
            full_prompt += (
                "\n\n(Effort directive: high — work carefully and verify "
                "your answer before replying.)"
            )
        return full_prompt

    def _prepare_run(self, prompt: str, label: str, ov: dict) -> dict:
        """Resolve options, recall, prompt contracts and the backend argv.

        The SHARED SEAM: the sync `_run()` and the async `_run_async()`
        execute exactly this preparation, so their argv are byte-identical
        by construction (law 1) — the async twins are a shell over the
        same contract, never a fork of it. The work lives in the named
        single-purpose helpers this method orchestrates.
        """
        opts, o, adapter, backend_name = self._resolve_run_options(label, ov)
        o["model"] = self._effective_model(ov, backend_name)
        effort = (o["effort"] or "medium").lower()
        prose_grants, skill_files = self._collect_skills(o["skills"])
        use_memory = opts["memory"]
        full_prompt = self._compose_prompt(
            prompt, o, label, use_memory, prose_grants, effort)
        cmd, full_prompt = adapter.build_cmd(o, full_prompt, skill_files)
        return {
            "label": label,
            "adapter": adapter,
            "backend": backend_name,
            "cmd": cmd,
            "o": o,
            "prompt": prompt,
            "full_prompt": full_prompt,
            "use_stats": o["stats"],
            "use_memory": use_memory,
            "retries": int(opts.get("retries") or 0),
            "timeout": opts["timeout"],
        }

    def _spawn_sync(self, cmd, o, prep, _finish):
        """One sync harness spawn with honest error attribution.

        Transport failures map to their true cause: a missing agent cwd
        is a caller error (RangerError), a missing CLI / broken spawn is
        a harness error (install hint attached), a timeout is a timeout.
        Identity fields (backend, adapter) come from the prep struct —
        the seam's own contract, never a re-passed copy.
        """
        backend_name, adapter = prep["backend"], prep["adapter"]
        try:
            return subprocess.run(
                cmd,
                cwd=self.cwd,
                # o, not opts: adapters may fold settings into
                # the env overlay inside build_cmd (e.g. the
                # openhands backend maps model= to LLM_MODEL)
                env=self._child_env(o.get("env")),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # own pg → contained blast
                timeout=prep["timeout"],
            )
        except FileNotFoundError:
            if self.cwd and not Path(self.cwd).is_dir():
                _finish("✗", "red", "agent cwd does not exist")
                raise RangerError(
                    f"agent cwd does not exist: {self.cwd}"
                ) from None
            _finish("✗", "red", f"{backend_name} CLI not found")
            raise RangerHarnessError(
                f"{backend_name} CLI not found on PATH — {adapter.install_hint}"
            ) from None
        except subprocess.TimeoutExpired:
            _finish("✗", "red", f"timed out after {prep['timeout']}s")
            raise RangerTimeout(
                f"{backend_name} run timed out after {prep['timeout']}s"
            ) from None
        except OSError as exc:
            _finish("✗", "red", _clip(str(exc), UI_NOTE_CLIP))
            raise RangerHarnessError(
                f"{backend_name} run could not be spawned: {exc}"
            ) from None

    async def _kill_async(self, proc) -> None:
        """Kill one async CLI subprocess's whole process group, wait."""
        # mirrors _kill_tree: start_new_session made the child its own
        # process-group leader, so one killpg reaches its whole tree
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except (OSError, asyncio.TimeoutError):
            # narrow, honest cleanup catch: the kill already happened, only
            # transport-level failures can occur here — and cleanup must
            # never mask the original exit (KeyboardInterrupt and
            # CancelledError are BaseException, so they still propagate)
            pass

    async def _spawn_async(self, cmd, o, prep):
        """One async harness spawn with honest error attribution.

        Same cause-mapping contract as `_spawn_sync`; cancellation and
        timeout kill the subprocess's whole process group. Identity
        fields come from the prep struct, like the sync twin.
        """
        backend_name, adapter = prep["backend"], prep["adapter"]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.cwd,
                # o, not opts: adapters may fold settings into
                # the env overlay inside build_cmd
                env=self._child_env(o.get("env")),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,  # own pg → contained blast
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), prep["timeout"]
            )
        except FileNotFoundError:
            # attribute the failure to its real cause: a missing
            # agent cwd also raises FileNotFoundError from spawn
            if self.cwd and not Path(self.cwd).is_dir():
                raise RangerError(
                    f"agent cwd does not exist: {self.cwd}"
                ) from None
            raise RangerHarnessError(
                f"{backend_name} CLI not found on PATH — {adapter.install_hint}"
            ) from None
        except asyncio.TimeoutError:
            if proc is not None:
                await self._kill_async(proc)
            raise RangerTimeout(
                f"{backend_name} run timed out after {prep['timeout']}s"
            ) from None
        except asyncio.CancelledError:
            # task cancellation kills the CLI subprocess — same
            # semantics as KeyboardInterrupt on the sync path
            if proc is not None:
                await self._kill_async(proc)
            raise
        except OSError as exc:
            raise RangerHarnessError(
                f"{backend_name} run could not be spawned: {exc}"
            ) from None
        return proc, stdout_b, stderr_b

    def _complete_run(self, prep, stdout, t0) -> str:
        """Shared post-transport block: parse, ledger, telemetry, memory.

        One implementation for BOTH seams (law 1): whatever came out of
        the sync or async transport goes through the exact same
        parse_output → _record_costs → last → context pipeline. Every
        field it needs travels inside the prep struct — the seam's own
        contract, never re-passed copies of its fields.
        """
        adapter, label = prep["adapter"], prep["label"]
        use_stats, use_memory = prep["use_stats"], prep["use_memory"]
        answer, info = adapter.parse_output(stdout, use_stats)
        self._record_costs(len(prep["full_prompt"]), len(answer),
                           info, time.time() - t0)
        if use_stats and info is not None:
            self.last = {
                "label": label,
                "wall_s": round(time.time() - t0, 2),
                **info,
            }
        if use_memory:
            self.context.append({"role": "user", "content": prep["prompt"]})
            self.context.append({"role": "assistant", "content": answer})
        return answer

    def _sync_transport(self, cmd, o, prep, _finish):
        """The sync spawn-retry loop: transport failures may re-attempt.

        Returns the successful CompletedProcess (exited 0). Retry
        policy: transport-class failures only — prompt-contract
        failures (plain RangerError) never re-attempt.
        """
        retries = prep["retries"]
        attempt = 0
        while True:
            try:
                proc = self._spawn_sync(cmd, o, prep, _finish)
                if proc.returncode != 0:
                    _finish("✗", "red", _clip(proc.stderr, UI_NOTE_CLIP) or f"exit {proc.returncode}")
                    raise RangerHarnessError(
                        f"{prep['backend']} run failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
                    )
                return proc
            except (RangerTimeout, RangerHarnessError) as exc:
                if attempt < retries:
                    attempt += 1
                    _finish("↻", "yellow", f"retry {attempt}/{retries}: {_clip(str(exc), UI_RETRY_CLIP)}")
                    continue
                raise

    def _run(self, prompt: str, label: str = "run", **ov) -> str:
        prep = self._prepare_run(prompt, label, ov)
        backend_name = prep["backend"]
        cmd, o = prep["cmd"], prep["o"]

        # live progress UI — stderr only; never a TTY in tests/pipes
        use_ui = o["pretty"] and getattr(sys.stderr, "isatty", lambda: False)()
        spinner = None
        t0 = time.time()
        if use_ui:
            spinner = _spinner_cls()(label, prompt)
            spinner.start()

        def _finish(mark: str, color: str, note: str = "") -> None:
            if not use_ui:
                return
            if spinner:
                spinner.stop()
            mm, ss = divmod(int(time.time() - t0), 60)
            note_part = f" {_c('·', 'dim')} {_clip(note, 84)}" if note else ""
            sys.stderr.write(
                f"  {_c(mark, color)} {_c(label, color)}"
                f" {_c('·', 'dim')} {_c(f'{mm:02d}:{ss:02d}', 'dim')}{note_part}\n"
            )
            sys.stderr.flush()

        _LOG.debug("run start · label=%s model=%s backend=%s",
                   label, o["model"], backend_name)

        try:
            proc = self._sync_transport(cmd, o, prep, _finish)
            answer = self._complete_run(prep, proc.stdout, t0)
            first = answer.splitlines()
            _finish("✓", "green", _clip(first[0], UI_NOTE_CLIP) if first else "")
            return answer
        except KeyboardInterrupt:
            # Ctrl+C / kernel interrupt: subprocess.run already killed the
            # child; print an honest ✗ line and propagate — the finally
            # clause below retires the spinner (a leaked spinner thread
            # ticks forever, wedging notebooks' stderr)
            _finish("✗", "red", "interrupted by user")
            raise
        finally:
            # fires on EVERY exit path — success, error, interrupt — so the
            # spinner thread can never outlive the call
            _LOG.debug("run finish · label=%s model=%s duration=%.2fs",
                       label, o["model"], time.time() - t0)
            if spinner is not None:
                spinner.stop()

    async def _async_transport(self, cmd, o, prep):
        """The async spawn-retry loop: transport failures may re-attempt.

        Returns decoded (stdout, stderr) of the successful run (exit
        0). Retry policy mirrors `_sync_transport`: transport-class
        failures only — plain RangerError never re-attempts.
        """
        retries = prep["retries"]
        attempt = 0
        while True:
            try:
                proc, stdout_b, stderr_b = await self._spawn_async(
                    cmd, o, prep)
                stdout = stdout_b.decode("utf-8", errors="replace")
                stderr = stderr_b.decode("utf-8", errors="replace")
                if proc.returncode != 0:
                    raise RangerHarnessError(
                        f"{prep['backend']} run failed (exit {proc.returncode}):\n{stderr.strip()}"
                    )
                return stdout, stderr
            except (RangerTimeout, RangerHarnessError) as exc:
                if attempt < retries:
                    attempt += 1
                    _LOG.info("run_async retry %d/%d · %s",
                              attempt, retries, _clip(str(exc), UI_RETRY_CLIP))
                    continue
                raise

    async def _run_async(self, prompt: str, label: str = "run", **ov) -> str:
        """Async shell over the SAME run contract as `_run()`.

        Same frozen prompt, same resolved options, byte-identical argv —
        the preparation is literally the shared `_prepare_run()` seam;
        only the process spawn/kill is asyncio here (no live spinner:
        stderr progress is a sync-screen concern). Cancellation kills
        the CLI subprocess, mirroring the KeyboardInterrupt semantics
        of the sync path, and record/telemetry state behaves exactly
        the same.
        """
        prep = self._prepare_run(prompt, label, ov)
        backend_name = prep["backend"]
        cmd, o = prep["cmd"], prep["o"]
        t0 = time.time()

        _LOG.debug("run_async start · label=%s model=%s backend=%s",
                   label, o["model"], backend_name)

        try:
            stdout, _stderr = await self._async_transport(cmd, o, prep)
            return self._complete_run(prep, stdout, t0)
        except asyncio.CancelledError:
            _LOG.debug("run_async cancelled · label=%s duration=%.2fs",
                       label, time.time() - t0)
            raise
        finally:
            _LOG.debug("run_async finish · label=%s model=%s duration=%.2fs",
                       label, o["model"], time.time() - t0)
