"""The command methods: dialogue, facts, async twins and bounded parallelism — thin frozen prompts over the transport engine, nothing else."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from pathlib import Path

from ._util import (RangerError, RangerTimeout, RangerHarnessError,
                    _RUN_KEYS, APPROX_CHARS_PER_TOKEN,
                    SLUG_CLIP, UUID_HEX_CLIP)
from ._contracts import (_ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt,
                         _extract_prompt, _parse_extract_answer,
                         _parse_check_verdict)

from ._backends import _BACKEND_CLASSES  # noqa: E402 (runs reference it)


class CommandsMixin:
    """Mixin — composed into ranger.Ranger (no bases)."""

    @staticmethod
    def models(match: str | None = None, backend: str = "opencode") -> list[str]:
        """List available model IDs for a harness.

        Delegates to the backend adapter: opencode runs `opencode models`;
        backends whose CLI cannot enumerate models raise RangerError with
        guidance (codex models are set in ~/.codex/config.toml or passed
        as model=).

        Args:
            match: optional substring filter (case-insensitive).
            backend: backend name (default "opencode").
        """
        try:
            adapter = _BACKEND_CLASSES[backend]()
        except KeyError:
            raise ValueError(
                f"unknown backend {backend!r} (registered: "
                f"{', '.join(sorted(_BACKEND_CLASSES))})"
            ) from None
        return adapter.list_models(match)

    @staticmethod
    def capabilities() -> dict:
        """Capability flags of every REGISTERED backend — no agent run.

        Static, like `models()`: capabilities are class-level facts of
        the adapter classes, never of a run or a Ranger instance.
        Returns `{name: {"supports_sessions": bool, "native_file_skills":
        bool}}` for every registered backend — a custom backend shows
        up the moment `ranger.register_backend()` names it.

            caps = ranger.Ranger.capabilities()
            assert caps["codex"]["native_file_skills"] is False
        """
        return {
            name: {"supports_sessions": bool(cls.supports_sessions),
                   "native_file_skills": bool(cls.native_file_skills)}
            for name, cls in _BACKEND_CLASSES.items()
        }

    def with_config(self, **overrides) -> "Ranger":
        """Return a copy of this Ranger with run settings overridden.

        Useful for keeping configured variants side by side:

            smart = Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
            builder = smart.with_config(agent="build", auto=True)
        """
        for key in overrides:
            if key not in _RUN_KEYS and key != "cwd":
                raise TypeError(f"unknown config key: {key!r} (valid: {', '.join(_RUN_KEYS + ('cwd',))})")
        cls = type(self)
        clone = cls.__new__(cls)  # was Ranger.__new__(Ranger): resolve via the instance
        clone.__dict__ = dict(self.__dict__)
        # mutable state must not leak between configured copies (issue #21):
        # histories, the cost ledger, the snapshot registry and the mutable
        # collection settings all get fresh containers from birth
        clone.context = [dict(m) for m in self.context]
        clone.last = dict(self.last)
        clone._costs = dict(self._costs)
        clone.snapshot_log = list(self.snapshot_log)
        for key in ("allow", "deny", "env_deny"):
            setattr(clone, key, list(getattr(self, key)) if getattr(self, key)
                    else getattr(self, key))
        clone.env = dict(self.env) if self.env else self.env
        clone.skills = (list(self.skills)
                        if isinstance(self.skills, (list, tuple)) else self.skills)
        for key, value in overrides.items():
            if key == "cwd" and value is not None:
                value = str(Path(value).resolve())
            setattr(clone, key, value)
        if "model" in overrides:
            # the explicit-choice marker must travel with the override, or
            # per-run default resolution would resurrect the old model
            clone._model_explicit = overrides["model"]
        return clone

    def context_summarize(self) -> str:
        """Ask the agent for a text digest of the recorded context.

        History is left untouched (the transcript-bearing request is never
        recorded back, so repeated summarization cannot nest). Returns ""
        when nothing is recorded.
        """
        if not self.context:
            return ""
        transcript = "\n\n".join(f"[{m['role']}] {m['content']}" for m in self.context)
        digest = self._run(
            "Summarize the following session history into a compact digest: "
            "commands issued, what was learned/decided, files touched, facts "
            "worth keeping. Plain text, bullet points.\n\n"
            + transcript,
            label="summarize",
            memory=False,  # the transcript is embedded explicitly — recording
        )                  # it back would nest history into history
        return digest

    def context_compact(self) -> str:
        """Collapse the whole history into one system summary message.

        The digest replaces self.context, so future runs recall a bounded
        summary instead of the full transcript. Returns the digest.
        """
        digest = self.context_summarize()
        self.context = [{"role": "system", "content": digest}] if digest else []
        return digest

    def context_clear(self) -> list[dict]:
        """Wipe the recorded context; returns what was cleared."""
        old, self.context = self.context, []
        return old

    def _quote_segments(self, prep, prompt: str, label: str,
                        prose_grants) -> dict:
        """Break the composed prompt's size into named parts (quote())."""
        o = prep["o"]
        effort = (o["effort"] or "medium").lower()
        chars_total = len(prep["full_prompt"])
        segments = {
            "request": len(prompt),
            "recall": len(self._recall_block(o, label)) if o["memory"] else 0,
            "grants": len(self._grants_block(prose_grants)),
            "effort": len(self._effort_directive(effort)),
        }
        segments["other"] = chars_total - sum(segments.values())
        return segments

    def quote(self, prompt: str, label: str = "run", **ov) -> dict:
        """Price a run BEFORE paying for it — zero model calls.

        Composes the exact prompt the matching run would send (the same
        `_prepare_run` seam, so the two can never drift — law 1) and
        measures it. No subprocess is spawned: `context` and `costs`
        stay untouched, and a bad spec raises here, before you pay.

        Returns `{"backend", "label", "chars_total", "est_tokens_in",
        "segments", "skill_files"}` where `segments` splits the prompt
        into `{"request", "recall", "grants", "effort", "other"}` —
        `other` is the inline skill-file bodies and their headers on
        backends without native attachment. `est_tokens_in` divides the
        chars by APPROX_CHARS_PER_TOKEN (≈4): a rough estimate, not a
        bill. Output tokens cannot be quoted honestly — they depend on
        the model's answer.

        Only side effect: the once-per-process stale-DEFAULT_MODEL
        warning, exactly like the real call would emit it.

            q = agent.quote("refactor parse()", label="do")
            if q["est_tokens_in"] > 2000:
                agent.context_clear()          # shed recall and re-quote
        """
        prep = self._prepare_run(prompt, label, ov)
        o = prep["o"]
        prose_grants, skill_files = self._collect_skills(o["skills"])
        segments = self._quote_segments(prep, prompt, label, prose_grants)
        return {
            "backend": prep["backend"],
            "label": label,
            "chars_total": len(prep["full_prompt"]),
            "est_tokens_in": round(len(prep["full_prompt"]) / APPROX_CHARS_PER_TOKEN),
            "segments": segments,
            "skill_files": [str(f) for f in skill_files],
        }

    def ask(self, prompt: str, **ov) -> str:
        """Send an arbitrary prompt to the agent and return its answer."""
        return self._run(prompt, label="ask", **ov)

    def summarize(self, file: str | Path, **ov) -> str:
        """Read a file and return a concise text summary of its contents.

        Relative paths resolve against the agent's cwd, not the Python
        process's.
        """
        path = Path(file)
        if not path.is_absolute():
            path = Path(self.cwd or Path.cwd()) / path
        prompt = (
            f"Read the file at {path.resolve()}. "
            "Then reply with a concise summary of what it contains. "
            "Reply with the summary text only, no preamble."
        )
        return self._run(prompt, label="summarize", **ov)

    def read(self, file: str | Path, question: str, **ov) -> str:
        """Answer a specific question about one file without modifying it.

        Relative paths resolve against the agent's cwd, not the Python
        process's. This command is history- and session-independent.
        """
        path = Path(file)
        if not path.is_absolute():
            path = Path(self.cwd or Path.cwd()) / path
        prompt = (
            f"Read only the file at {path.resolve()}.\n\n"
            f"Question: {question}\n\n"
            "Reading and analysis only — do NOT modify, create, delete, or "
            "rename any file. Answer the question directly using evidence from "
            "that file."
        )
        return self._run(prompt, label="read", **ov)

    def _write_spec(self, task: str, path: "str | Path | None", ov: dict) -> dict:
        """Pure decision helper shared by write() and write_async().

        Resolves EVERYTHING the body needs — target path (generated
        slug file when `path is None`, cwd-relative otherwise), the
        frozen prompt, the rails verdicts — and enforces the path rails
        + pre-write auto-snapshot in exactly the order write() always
        had. Sync and async twins can never drift past this seam.
        """
        self._validate_ov_keys(ov)  # unknown keys fail BEFORE the snapshot
        if path is None:
            slug = re.sub(r"[^a-z0-9_-]+", "_", task.strip().lower())[:SLUG_CLIP]
            slug = slug.strip("_-") or "ranger_out"
            out = Path(self.cwd or Path.cwd()) / (
                f"ranger_{slug}_{int(time.time())}_{uuid.uuid4().hex[:UUID_HEX_CLIP]}.md"
            )
        else:
            out = Path(path)
            if not out.is_absolute():
                out = Path(self.cwd or Path.cwd()) / out
        prompt = _write_prompt(task, out)
        allow, deny, dry = self._resolve_safety(ov)
        # root enables the cwd-relative glob form — the same rails that
        # protect do() must hold for the named targets too (audit fix:
        # without root, a relative deny like "secrets/**" never matched
        # this now-absolute target and edit() bypassed the rail)
        self._assert_path_allowed(out, allow, deny,
                                  root=Path(self.cwd or Path.cwd()))
        self._auto_snapshot("pre-write")
        # instance-blind dry_run was the divergence: the postcheck saw
        # False while with_config(dry_run=True) made the run read-only —
        # the same resolution as _resolve_safety keeps them in sync
        return {"prompt": prompt, "out": out, "dry_run": dry}

    @staticmethod
    def _write_after(spec: dict) -> None:
        """Shared post-run check: the expected file must exist on disk.

        dry_run is exempt — a read-only plan run writes nothing.
        """
        if not spec["out"].is_file() and not spec["dry_run"]:
            raise RangerError(
                f"agent did not write the expected file: {spec['out']}")

    def write(self, task: str, path: str | Path | None = None, **ov) -> str:
        """Have the agent produce a written document/answer as a file.

        Returns the path of the file that was written.
        """
        spec = self._write_spec(task, path, ov)
        self._run(spec["prompt"], label="write", **ov)
        self._write_after(spec)
        return str(spec["out"])

    def _transform_spec(self, pattern, instruction, max_files):
        """Validate a transform() spec up front; normalize the pattern.

        A bad spec raises TypeError/ValueError BEFORE any spawn —
        zero harness calls (pinned by test_spec_validation).
        """
        if isinstance(pattern, Path):
            pattern = str(pattern)
        if not isinstance(pattern, str) or not pattern:
            raise TypeError(f"pattern must be a non-empty glob, got {pattern!r}")
        if not isinstance(instruction, str) or not instruction.strip():
            raise TypeError(
                f"instruction must be a non-empty string, got {instruction!r}")
        if (not isinstance(max_files, int) or isinstance(max_files, bool)
                or max_files < 1):
            raise ValueError(
                f"max_files must be a positive int, got {max_files!r}")
        return pattern

    def transform(self, pattern: "str | Path", instruction: str,
                  max_files: int = 10, **ov) -> "list[dict]":
        """Apply ONE bounded edit() to every file matching a glob.

        Batch `edit()` with per-file honesty: each result entry is
        `{"file", "report"}` on success or `{"file", "error"}` on
        failure — a sibling's failure never stops the batch. Runs at
        most `max_files` matched files (sorted); safety rails
        (allow/deny) and `dry_run` apply to every file exactly as in
        `edit()`.

            agent.transform("src/**/*.py", "add the module docstring",
                            max_files=20)
        """
        pattern = self._transform_spec(pattern, instruction, max_files)
        root = Path(self.cwd or Path.cwd())
        try:
            # Path.glob leaks native errors on some patterns: an absolute
            # glob raises NotImplementedError, an unparsable one a
            # ValueError on newer pathlib — both are caller input, so
            # they cross the trust boundary as RangerError (law 5)
            files = sorted(p for p in root.glob(pattern)
                           if p.is_file())[:max_files]
        except NotImplementedError:
            raise RangerError(
                f"transform(): pattern must be RELATIVE to the agent cwd "
                f"({root}); got absolute pattern {pattern!r}") from None
        except ValueError as exc:
            raise RangerError(
                f"transform(): invalid glob pattern {pattern!r} ({exc})") from None
        if not files:
            raise RangerError(
                f"transform(): no files match {pattern!r} under {root}")
        results: list[dict] = []
        for f in files:
            try:
                results.append(
                    {"file": str(f), "report": self.edit(f, instruction, **ov)})
            except (RangerError, RangerHarnessError, RangerTimeout) as exc:
                results.append({"file": str(f), "error": str(exc)})
        return results

    def do(self, goal: str, **ov) -> str:
        """Execute a goal against the filesystem like a CLI agent run.

        The agent may create, edit and delete files and run shell commands
        in the working directory. Returns its final report. With
        `Ranger(snapshots=True)` a best-effort git snapshot is taken
        first, making the round recoverable via `rollback()`.
        """
        self._validate_ov_keys(ov)  # unknown keys fail BEFORE probe/snapshot
        allow, deny, dry, root, baseline = self._guard_do(ov)
        self._auto_snapshot("pre-do")
        report = self._run(_do_prompt(goal), label="do", **ov)
        self._check_do_after(allow, deny, dry, root, baseline)
        return report

    def _edit_spec(self, file: "str | Path", instruction: str, ov: dict) -> dict:
        """Pure decision helper shared by edit() and edit_async().

        Resolves the target (cwd-relative then resolved), refuses a
        missing file BEFORE anything runs, enforces the path rails and
        takes the pre-edit auto-snapshot — the exact order edit()
        always had. Returns the prompt, the pre-run mtime and the
        dry_run flag so the shared postcheck sees one spec.
        """
        self._validate_ov_keys(ov)  # unknown keys fail BEFORE the snapshot
        target = Path(file)
        if not target.is_absolute():
            target = Path(self.cwd or Path.cwd()) / target
        target = target.resolve()
        try:
            before = target.stat().st_mtime_ns
        except FileNotFoundError:
            raise RangerError(f"edit() target does not exist: {target}") from None
        allow, deny, dry = self._resolve_safety(ov)
        # root enables the cwd-relative glob form — see _write_spec
        self._assert_path_allowed(target, allow, deny,
                                  root=Path(self.cwd or Path.cwd()))
        self._auto_snapshot("pre-edit")
        # same fix as write(): dry_run resolves instance-first via
        # _resolve_safety — per-call still wins, the postcheck agrees
        return {"prompt": _edit_prompt(target, instruction),
                "target": target, "before": before, "dry_run": dry}

    @staticmethod
    def _edit_after(spec: dict, report: str) -> str:
        """Shared post-run check: the target must have been modified.

        dry_run is exempt — a read-only plan run mutates nothing, so
        the report passes through unchanged.
        """
        if spec["dry_run"]:
            return report   # read-only plan run: no mutation is expected
        try:
            after = spec["target"].stat().st_mtime_ns
        except FileNotFoundError:
            raise RangerError(
                f"agent removed the edit() target: {spec['target']}") from None
        if after == spec["before"]:
            raise RangerError(
                f"agent did not modify the edit() target: {spec['target']}")
        return report

    def edit(self, file: str | Path, instruction: str, **ov) -> str:
        """Make one requested change to exactly one existing file.

        Relative paths resolve against the agent's cwd. Raises RangerError if
        the target was not modified during the agent run.
        """
        spec = self._edit_spec(file, instruction, ov)
        report = self._run(spec["prompt"], label="edit", **ov)
        return self._edit_after(spec, report)

    def plan(self, goal: str, **ov) -> str:
        """Produce a numbered implementation plan for a goal.

        Think without touching: the agent may read and analyze the working
        directory, but the prompt contract forbids any file modification.
        The plan is a numbered list of concrete steps (referencing real
        files and commands) ending with the single riskiest assumption.
        A dialogue command — the exchange is recorded into `agent.context`.
        """
        prompt = (
            f"Produce an implementation plan for this goal in the current "
            f"directory: {goal}\n"
            "Contract: reading and analysis only — do NOT modify, create, "
            "or delete any file. First inspect the relevant code and "
            "configuration. Reply with a numbered plan (1., 2., 3., ...) "
            "where every step references the concrete files to touch and "
            "the commands to run. No preamble before the first numbered "
            "step. End the reply with exactly one line starting "
            "'Riskiest assumption:' stating the single riskiest assumption "
            "the plan makes."
        )
        return self._run(prompt, label="plan", **ov)

    def search(self, goal: str, **ov) -> str:
        """Search the working directory and report where/what matches.

        Returns a multiline report: file paths, line numbers and snippets.
        """
        return self._run(_search_prompt(goal), label="search", **ov)

    def trace(self, symbol: str, **ov) -> str:
        """Trace a symbol's definition, callers, and data flow without mutation.

        This repository-wide analysis is history- and session-independent.
        """
        prompt = (
            f"Trace this symbol across the current repository: {symbol}\n\n"
            "Inspect the codebase and report the symbol's definition, callers, and "
            "relevant data-flow relationships. Cite every finding with `file:line` "
            "evidence. Reading and analysis only — do NOT modify, create, delete, "
            "or rename any file."
        )
        return self._run(prompt, label="trace", **ov)

    def test(self, **ov) -> str:
        """Run the project's test suite and diagnose failures without mutation."""
        prompt = (
            "Run this project's existing test suite in the current directory. "
            "Reading and analysis only — do NOT modify, create, delete, or rename "
            "any file. Diagnose any failures concisely: identify likely root cause(s), "
            "include relevant failing test or error evidence, and propose the minimal "
            "fix direction. If tests pass, report that outcome and the command run."
        )
        return self._run(prompt, label="test", **ov)

    def lint(self, **ov) -> str:
        """Run configured lint and format checks and diagnose failures without mutation."""
        prompt = (
            "Run this project's existing lint and format checks in the current directory. "
            "Reading and analysis only — do NOT modify, create, delete, or rename "
            "any file. Diagnose any failures concisely: identify the relevant check and "
            "error evidence, then propose the minimal remediation. If checks pass, report "
            "that outcome and the command(s) run."
        )
        return self._run(prompt, label="lint", **ov)

    def diagnose(self, error: str, **ov) -> str:
        """Diagnose pasted traceback or error-log text without modifying files.

        The agent may inspect relevant local code, but this command is
        history- and session-independent and never permits filesystem changes.
        """
        prompt = (
            "Diagnose this pasted traceback or error log from the current project:\n\n"
            f"{error}\n\n"
            "You may inspect relevant local code to establish the cause. Reading and "
            "analysis only — do NOT modify, create, delete, or rename any file. Give "
            "an evidence-backed likely root cause, cite the relevant error or code "
            "evidence, and propose the minimal fix direction."
        )
        return self._run(prompt, label="diagnose", **ov)

    def critique(self, file_or_diff: str, **ov) -> str:
        """Review a file path or diff for risks without modifying anything.

        The target is passed through as prompt data; ranger does not parse or
        validate whether it is a path or a diff. This command is history- and
        session-independent.
        """
        prompt = (
            "Review this file path or diff for bugs, risks, security issues, and "
            f"missing tests:\n\n{file_or_diff}\n\n"
            "Reading and analysis only — do NOT modify, create, delete, or rename "
            "any file. If the target is a file path, read it and relevant local code. "
            "If it is a diff, review its contents and relevant local code. Report "
            "findings directly, prioritizing concrete issues with evidence."
        )
        return self._run(prompt, label="critique", **ov)

    def check(self, condition: str, **ov):
        """Verify a claim about repo state; return True or False.

        The agent may run whatever it needs (commands, file reads) to
        establish the truth, but its answer contract is strict: the first
        word of the reply must be YES or NO. Anything else raises
        RangerError rather than guessing.

        Opt-in run option ``evidence=True`` returns instead the dict
        ``{"ok": bool, "evidence": str}`` — the one short line of
        evidence the frozen prompt allows after the verdict ("" when
        the reply carried none), the same last_gate philosophy as
        gate(). Default is off: a bare bool is returned, exactly today.
        Keep a policy with `with_config(evidence=True)`.

            agent.check("all tests pass")        # -> bool
            agent.check("README mentions the license")
            agent.check("server binds 8080", evidence=True)
                # -> {"ok": True, "evidence": "config.yaml binds 8080"}
        """
        prompt = _check_prompt(condition)
        answer = self._run(prompt, label="check", **ov)
        return self._check_result(answer, ov)

    def _check_result(self, answer: str, ov: dict):
        """check() return shaping: bool today, evidence dict opted in.

        Shared by check() and its async twin; `evidence=` rides the run
        options (validated once at the seam), so the twin needs no fork.
        """
        if not bool(ov.get("evidence", self.evidence)):
            return _parse_check_verdict(answer)
        ok, ev = _parse_check_verdict(answer, evidence=True)
        return {"ok": ok, "evidence": ev}

    def extract(self, request: str, keys: "list[str] | tuple[str, ...]",
                many: bool = True, **ov) -> "list[dict] | dict":
        """Extract structured data: JSON grammar beyond the YES/NO verdict.

        The agent verifies facts in the working directory and must reply
        with exactly one JSON object (``many=False``) or one JSON array of
        objects (``many=True``, the default) carrying the named ``keys``.
        The reply is parsed mechanically (law 2): malformed JSON, trailing
        prose, non-object rows or missing keys raise `RangerError` carrying
        the raw agent reply — never a guess. An empty array/object is a
        legitimate "no matches".

        History- and session-independent (a fact command), read-only.

            rows = agent.extract("failing tests in tests/",
                                 keys=["test_id", "reason"])
            one  = agent.extract("project metadata", keys=["name", "version"],
                                 many=False)

        Deliberate non-goals: no pydantic models, no schema registry, no
        nested schemas — flat keys, grammar + parser.
        """
        if isinstance(keys, str) or not isinstance(keys, (list, tuple)):
            raise TypeError(f"keys must be a list of strings, got {keys!r}")
        keys = [str(k) for k in keys]
        if not keys:
            raise ValueError("keys must not be empty")
        for k in keys:
            if not k:
                raise ValueError("keys must be non-empty strings")
        prompt = _extract_prompt(request, keys, many)
        answer = self._run(prompt, label="extract", **ov)
        return _parse_extract_answer(answer, keys, many)

    async def ask_async(self, prompt: str, **ov) -> str:
        """Async twin of ask(): same contract, same frozen prompt.

        Runs one headless harness CLI through `asyncio`; see par_map()
        for running many independent calls concurrently.
        """
        return await self._run_async(prompt, label="ask", **ov)

    async def do_async(self, goal: str, **ov) -> str:
        """Async twin of do(): same contract, same frozen prompt."""
        self._validate_ov_keys(ov)  # unknown keys fail BEFORE probe/snapshot
        allow, deny, dry, root, baseline = self._guard_do(ov)
        self._auto_snapshot("pre-do")
        report = await self._run_async(_do_prompt(goal), label="do", **ov)
        self._check_do_after(allow, deny, dry, root, baseline)
        return report

    async def search_async(self, goal: str, **ov) -> str:
        """Async twin of search(): same contract, same frozen prompt."""
        return await self._run_async(_search_prompt(goal),
                                     label="search", **ov)

    async def write_async(self, task: str, path: str | Path | None = None,
                          **ov) -> str:
        """Async twin of write(): same contract, same frozen prompt.

        Returns the path of the file that was written, and raises
        RangerError if the agent did not write it — same as write().
        """
        spec = self._write_spec(task, path, ov)
        await self._run_async(spec["prompt"], label="write", **ov)
        self._write_after(spec)
        return str(spec["out"])

    async def edit_async(self, file: str | Path, instruction: str,
                         **ov) -> str:
        """Async twin of edit(): same contract, same frozen prompt.

        Raises RangerError if the single target file was not modified
        during the agent run — same mechanical check as edit().
        """
        spec = self._edit_spec(file, instruction, ov)
        report = await self._run_async(spec["prompt"], label="edit", **ov)
        return self._edit_after(spec, report)

    async def check_async(self, condition: str, **ov):
        """Async twin of check(): same strict YES/NO verdict grammar.

        Same evidence= run option and shaped return as check() — the
        return shaping is one helper, not a fork of the contract.
        """
        answer = await self._run_async(_check_prompt(condition),
                                        label="check", **ov)
        return self._check_result(answer, ov)

    @staticmethod
    def _par_spec_error(i: int, call: dict, default_agent) -> "tuple | None":
        """(ExceptionClass, message) for one bad call spec; None if good.

        Pure validation lookup — it never raises; `par_map` owns the
        raising, so validation stays at the trust boundary (law 5).
        """
        method = call.get("method", "ask")
        twin = f"{method}_async"
        if method not in _ASYNC_TWIN_METHODS:
            return (ValueError,
                    f"calls[{i}]: method must be one of "
                    f"{sorted(_ASYNC_TWIN_METHODS)}, got {method!r}")
        args = call.get("args", [])
        kwargs = call.get("kwargs", {})
        agent = call.get("agent", default_agent)
        if not isinstance(args, (list, tuple)):
            return (TypeError, f"calls[{i}]: args must be a list, got {args!r}")
        if not isinstance(kwargs, dict):
            return (TypeError, f"calls[{i}]: kwargs must be a dict, got {kwargs!r}")
        if not hasattr(agent, twin):
            return (TypeError,
                    f"calls[{i}]: agent has no {twin} — a Ranger is required")
        return None

    @staticmethod
    async def _par_execute(specs: "list[tuple]",
                           max_concurrency: int) -> "list":
        """Run validated (agent, twin, args, kwargs) specs concurrently.

        Pure assembly: bounded semaphore + gather with per-item honest
        exceptions. No validation happens here.
        """
        if not specs:
            return []
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _one(agent, twin, args, kwargs):
            async with semaphore:
                return await getattr(agent, twin)(*args, **kwargs)

        # return_exceptions=True: a sibling failure must not cancel the
        # others, and per-item errors are reported in place — never hidden
        return await asyncio.gather(
            *(_one(*spec) for spec in specs), return_exceptions=True)

    async def par_map(self, calls: "list[dict]",
                      max_concurrency: int = 8) -> "list":
        """Run independent calls concurrently; one result per input.

        Each call is a dict. Keys:
          - ``method``: an async-twin name — ``ask`` (default), ``do``,
            ``write``, ``edit``, ``search`` or ``check``;
          - ``args`` / ``kwargs``: passed to that twin (default: none);
          - ``agent``: optional OTHER Ranger — defaults to this one.

        Returns a list aligned with ``calls``: the answer on success,
        or the exception instance that call raised (honest per-item
        failures — nothing is swallowed; nothing but transport is
        retried beyond each call's own ``retries``).

        Bounded concurrency: at most ``max_concurrency`` CLI subprocesses
        run at once. This is a helper, not a scheduler (law 6): there is
        no runtime, no queue object — plain ``asyncio.gather`` under a
        semaphore, and the control flow stays yours.

            results = asyncio.run(agent.par_map([
                {"method": "search", "args": ["parseSQL defined"]},
                {"method": "ask", "args": ["list failing checks"]},
                {"method": "check", "args": ["readme mentions license"]},
            ]))
        """
        if isinstance(calls, (str, bytes)) or not isinstance(calls, list):
            raise TypeError(f"calls must be a list of dicts, got {calls!r}")
        if (not isinstance(max_concurrency, int)
                or isinstance(max_concurrency, bool) or max_concurrency < 1):
            raise ValueError(
                f"max_concurrency must be a positive int, got {max_concurrency!r}")
        # validate EVERYTHING up front — a bad spec must not waste a
        # single harness call on the calls that were fine
        seen: list[tuple] = []
        for i, call in enumerate(calls):
            if not isinstance(call, dict):
                raise TypeError(f"calls[{i}] must be a dict, got {call!r}")
            err = self._par_spec_error(i, call, self)
            if err is not None:
                raise err[0](err[1])
            method = call.get("method", "ask")
            seen.append((call.get("agent", self), f"{method}_async",
                         list(call.get("args", [])), dict(call.get("kwargs", {}))))
        return await self._par_execute(seen, max_concurrency)

    def gate(self, command: str, timeout: float | None = None) -> bool:
        """Mechanical boolean gate: run a shell command, return exit==0.

        No model involved — pure subprocess. Use for checkable success
        conditions in your loops. The command runs in its own process
        group: a timeout (returns False) or an interrupt (re-raises)
        kills the whole group — no orphaned pipeline keeps running.
        The output tail of the last gate is kept in `self._gate_last`
        (or None) for until()'s evidence dict.

            if agent.gate("python -m pytest -q"):
                ...
        """
        ok, out = self._gate_ev(command, timeout)
        self._gate_last = (ok, out)
        return ok
