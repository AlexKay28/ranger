"""Harness backend adapters: opencode, codex, pi, openhands, claude.

One build_cmd/parse_output contract per CLI; the public API is identical across them (law 1).

External flag and schema behavior is frozen from official docs of each CLI (landing commits cite the URLs)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from ._util import (RangerError, RangerTimeout, RangerHarnessError, _c, _clip)

# ====================================================================== #
# Harness backends (adapters)
#
# A backend translates ranger's normalized run options into ONE CLI
# invocation for some headless agent harness, and parses its output back
# into plain answer text (+ optional telemetry dict). Everything else in
# ranger — prompt contracts, context memory, check/gate/until, effort
# directives, the UI — is harness-agnostic and lives above this layer.
#
# To support a new harness: subclass `_Backend`, implement `build_cmd`
# and `parse_output` (and `list_models` if the CLI can enumerate models),
# then `ranger.register_backend("name", YourBackend)`.
# ====================================================================== #

_BACKEND_CLASSES: dict[str, type] = {}  # filled after the base + impls


def register_backend(name: str, adapter_cls: type) -> None:
    """Register a harness adapter class under `name`.

    `Ranger(backend=name)` becomes valid immediately after. Custom
    backends live in-process only (they are not persisted by
    `with_config` across program runs unless re-registered).
    """
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid backend name: {name!r}")
    _BACKEND_CLASSES[name] = adapter_cls


def backends() -> list[str]:
    """Names of all registered harness backends, sorted."""
    return sorted(_BACKEND_CLASSES)


class _Backend:
    """Base class for harness adapters. See the module docstring above."""

    name = "?"
    install_hint = "install the harness CLI and put it on PATH"
    #: True when `session=` continuing is natively expressible.
    supports_sessions = True
    #: True when file-based skills ride along natively (else inlined).
    native_file_skills = True

    def unavailable(self, option: str) -> RangerError:
        return RangerError(
            f"{self.name!r} harness does not support {option!r} — "
            "remove it for this backend (see docs/API.md, Backends)"
        )

    def _inline_skills(self, full_prompt: str, skill_files: list) -> str:
        """Attach markdown skill files by inlining them into the prompt.

        Shared shape for backends without a native file-attachment
        flag (codex, claude, openhands): one header, the file blocks,
        then the task — the exact frozen composition.
        """
        if not skill_files:
            return full_prompt
        blocks = [
            f"### Attached skill file: {f}\n" + Path(f).read_text(encoding="utf-8")
            for f in skill_files
        ]
        return (
            "## Attached operating instructions (skill files)\n\n"
            + "\n\n".join(blocks)
            + "\n\n## Task\n"
            + full_prompt
        )

    def build_cmd(self, o: dict, full_prompt: str, skill_files: list):
        """Return (cmd_argv, final_prompt).

        `o` holds resolved run options (model, cwd, timeout, auto, session,
        agent, mode, title, thinking, effort, stats, backend...).
        `skill_files` are attached markdown files/dirs; either wire them to
        a native flag or inline them into the returned prompt.
        """
        raise NotImplementedError

    def parse_output(self, stdout: str, want_stats: bool):
        """Return (answer_text, info_dict_or_None).

        `info` may carry telemetry fields merged into `agent.last` when
        `want_stats` (session, model_s, input_tokens, ...). Return None
        when stats were not requested or unavailable.
        """
        raise NotImplementedError

    def list_models(self, match: str | None) -> list[str]:
        raise RangerError(
            f"model enumeration is not available for {self.name!r}: "
            "set the model in its config file or pass model= explicitly"
        )


class _OpenCodeBackend(_Backend):
    name = "opencode"
    install_hint = "install it from https://opencode.ai"

    def build_cmd(self, o, full_prompt, skill_files):
        cmd = ["opencode", "run", "--model", o["model"]]
        agent_name = o.get("agent") or o.get("mode")
        # dry_run maps to opencode's read-only plan agent (law 4: a
        # permission mode, never prompt politeness)
        if o.get("dry_run"):
            if agent_name:
                raise RangerError(
                    "dry_run maps to opencode's read-only plan agent — "
                    "clear agent/mode for this call"
                )
            agent_name = "plan"
        if agent_name:
            cmd += ["--agent", agent_name]
        if o["auto"]:
            cmd.append("--auto")
        if o["session"]:
            cmd += ["--session", o["session"]]
        if o["title"]:
            cmd += ["--title", o["title"]]
        if o["thinking"]:
            cmd.append("--thinking")
        if o["stats"]:
            cmd += ["--format", "json"]
        for f in skill_files:
            cmd += ["--file", str(f)]
        cmd.append("--")      # nothing after this can be parsed as a flag —
        cmd.append(full_prompt)  # the prompt is data, never options
        return cmd, full_prompt

    def parse_output(self, stdout, want_stats):
        if not want_stats:
            return stdout.strip(), None
        parts_text, session, starts, ends = [], None, [], []
        for line in stdout.splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            session = obj.get("sessionID") or session
            part = obj.get("part") or {}
            if part.get("type") == "text" and "text" in part:
                parts_text.append(part["text"])
                t = part.get("time") or {}
                if t.get("start"):
                    starts.append(t["start"])
                if t.get("end"):
                    ends.append(t["end"])
        answer = "\n".join(parts_text).strip()
        model_ms = (max(ends) - min(starts)) / 1000 if starts and ends else None
        info = {
            "model_s": round(model_ms, 2) if model_ms is not None else None,
            "parts": len(parts_text),
            "chars": len(answer),
            "session": session,
        }
        return answer, info

    def list_models(self, match):
        try:
            proc = subprocess.run(
                ["opencode", "models"],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            raise RangerHarnessError(
                f"opencode CLI not found on PATH — {self.install_hint}"
            ) from None
        except subprocess.TimeoutExpired:
            raise RangerTimeout("opencode models timed out after 60s") from None
        if proc.returncode != 0:
            raise RangerHarnessError(f"opencode models failed:\n{proc.stderr.strip()}")
        ids = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if match:
            needle = match.lower()
            ids = [i for i in ids if needle in i.lower()]
        return ids


class _CodexBackend(_Backend):
    """OpenAI codex CLI adapter: exec subcommand with JSONL events."""
    name = "codex"
    install_hint = "install it from https://github.com/openai/codex"
    native_file_skills = False  # markdown skills are inlined into prompts

    def _sandbox_argv(self, o):
        """Per-run sandbox/approval argv: session resume vs fresh exec."""
        if o["session"]:
            # resume shares -m/-c/--json but takes neither -C nor -s
            # flags; requested model and a read-only policy are still
            # honored via -c/-m (auto=True keeps the session's existing
            # policy)
            cmd = ["codex", "exec", "resume", "--skip-git-repo-check",
                   o["session"]]
            # read-only when requested: explicit auto=False, or dry_run
            # (a permission mode — resume shares -c, not -s)
            if not o["auto"] or o.get("dry_run"):
                cmd += ["-c", 'sandbox_mode="read-only"']
            return cmd
        cmd = ["codex", "exec", "--skip-git-repo-check"]
        if o["cwd"]:
            cmd += ["-C", o["cwd"]]
        # agent autonomy: --approve-for-me routes approvals through
        # automatic review with its own workspace-write sandbox (it
        # conflicts with -s); auto=False — or dry_run — pins a
        # read-only sandbox (exec cannot be interactive)
        if o["auto"] and not o.get("dry_run"):
            cmd.append("--approve-for-me")
        else:
            cmd += ["-s", "read-only"]
        return cmd

    def _reasoning_argv(self, o):
        """Effort/thinking map onto codex reasoning config flags."""
        if o["thinking"]:
            return ["-c", 'model_reasoning_effort="high"']
        if o["effort"] == "low":
            return ["-c", 'model_reasoning_effort="low"']
        if o["effort"] == "high":
            return ["-c", 'model_reasoning_effort="high"']
        return []

    def build_cmd(self, o, full_prompt, skill_files):
        for k in ("agent", "mode", "title"):
            if o.get(k):
                raise self.unavailable(k)
        full_prompt = self._inline_skills(full_prompt, skill_files)
        cmd = self._sandbox_argv(o)
        if o["model"]:
            cmd += ["-m", o["model"]]
        cmd += self._reasoning_argv(o)
        cmd += ["--json"]
        cmd.append("--")        # prompt is data, never options
        cmd.append(full_prompt)
        return cmd, full_prompt

    def _json_line(self, line: str):
        """Parse one stream line into a JSON object, or None."""
        line = line.strip()
        if not line.startswith("{"):
            return None
        try:
            return json.loads(line)
        except ValueError:
            return None

    def _jsonl_events(self, stdout):
        """Yield each parsed JSON object from the event stream.

        codex emits a JSONL of typed events; non-JSON noise (banners,
        progress lines) is skipped, never fatal.
        """
        for line in stdout.splitlines():
            obj = self._json_line(line)
            if obj is not None:
                yield obj

    def _collect_item_text(self, item, texts) -> None:
        """Append an item.completed agent message, when there is one."""
        if item.get("type") == "agent_message" and item.get("text"):
            texts.append(item["text"])

    def _apply_event(self, obj, texts, thread, usage) -> tuple:
        """Fold one codex event into the running scan state."""
        kind = obj.get("type")
        if kind == "thread.started":
            thread = obj.get("thread_id") or thread
        elif kind == "item.completed":
            self._collect_item_text(obj.get("item") or {}, texts)
        elif kind == "turn.completed":
            usage = obj.get("usage") or usage
        return thread, usage

    def _collect_events(self, stdout):
        """Scan codex's JSONL event stream: texts, thread id, usage."""
        texts, thread, usage = [], None, None
        for obj in self._jsonl_events(stdout):
            thread, usage = self._apply_event(obj, texts, thread, usage)
        return texts, thread, usage

    def parse_output(self, stdout, want_stats):
        texts, thread, usage = self._collect_events(stdout)
        answer = "\n".join(texts).strip()
        if not want_stats:
            return answer, None
        info = {
            "model_s": None,  # codex reports token usage, not model seconds
            "parts": len(texts),
            "chars": len(answer),
            "session": thread,
        }
        if usage:
            info.update({
                "input_tokens": usage.get("input_tokens"),
                "cached_input_tokens": usage.get("cached_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            })
        return answer, info


class _PiBackend(_Backend):
    name = "pi"
    install_hint = "install it from https://pi.dev (curl -fsSL https://pi.dev/install.sh | sh)"
    supports_sessions = True
    native_file_skills = True   # --skill takes files AND directories

    def build_cmd(self, o, full_prompt, skill_files):
        cmd = ["pi", "--print"]
        # pi has no permission system at all — dry_run/read-only cannot
        # be mapped to it, so it refuses loudly instead of pretending
        if o.get("dry_run"):
            raise self.unavailable("dry_run")
        if o["model"]:
            cmd += ["--model", o["model"]]
        if o["session"]:
            # opens the exact session id or creates it if absent
            cmd += ["--session-id", o["session"]]
        if o["title"]:
            cmd += ["--name", o["title"]]
        if o["thinking"]:
            cmd += ["--thinking", "high"]
        elif o["effort"] == "high":
            cmd += ["--thinking", "high"]
        elif o["effort"] == "low":
            cmd += ["--thinking", "low"]
        for f in skill_files:
            cmd += ["--skill", str(f)]
        # agent/mode/pi has no concept of either; pi has no permission
        # system at all, so o["auto"] maps to nothing — never emit
        # flags pi does not know (it rejects unknown short options).
        if o.get("agent") or o.get("mode"):
            raise self.unavailable(o.get("agent") or o.get("mode"))
        cmd.append("--")        # prompt is data, never options
        cmd.append(full_prompt)
        return cmd, full_prompt

    def parse_output(self, stdout, want_stats):
        # --print writes the final assistant text to stdout; no
        # structured telemetry without --mode json (deferred).
        return stdout.strip(), None

    def list_models(self, match):
        try:
            proc = subprocess.run(
                ["pi", "--list-models"],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            raise RangerHarnessError(
                f"pi CLI not found on PATH — {self.install_hint}"
            ) from None
        except subprocess.TimeoutExpired:
            raise RangerTimeout("pi --list-models timed out after 60s") from None
        if proc.returncode != 0:
            raise RangerHarnessError(
                f"pi --list-models failed:\n{proc.stderr.strip()}"
            )
        ids = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if match:
            needle = match.lower()
            ids = [i for i in ids if needle in i.lower()]
        return ids


class _OpenHandsBackend(_Backend):
    name = "openhands"
    install_hint = "install the OpenHands CLI from https://docs.openhands.dev"
    supports_sessions = True
    native_file_skills = False  # markdown skills are inlined into prompts

    def build_cmd(self, o, full_prompt, skill_files):
        # headless has no approval flow and no agent/title/thinking/mode
        # flags; the model is selected via LLM_MODEL env (never as a
        # CLI flag) together with --override-with-envs.
        for k in ("agent", "mode", "title", "thinking"):
            if o.get(k):
                raise self.unavailable(k)
        # headless ALWAYS runs always-approve and that cannot be changed,
        # so a read-only dry run cannot be guaranteed — refuse it loudly
        if o.get("dry_run"):
            raise self.unavailable("dry_run")
        full_prompt = self._inline_skills(full_prompt, skill_files)
        cmd = ["openhands", "--headless"]
        if o["session"]:
            cmd += ["--resume", o["session"]]
        # model= never becomes a CLI flag: headless honors LLM_MODEL
        # only via --override-with-envs, and user settings are never
        # persisted. Fold it into the env overlay (computed after
        # build_cmd, so mutating o here reaches the child process).
        if o.get("model"):
            o["env"] = {**(o.get("env") or {}), "LLM_MODEL": o["model"]}
            cmd.append("--override-with-envs")
        cmd += ["--task", full_prompt]
        return cmd, full_prompt

    def parse_output(self, stdout, want_stats):
        # plain headless prints the agent transcript; the JSONL
        # (--json) event schema is not stable enough to parse yet.
        return stdout.strip(), None


class _ClaudeBackend(_Backend):
    name = "claude"
    install_hint = "install the Claude Code CLI (https://code.claude.com/docs)"
    supports_sessions = True  # new session ids are READ from json output
    native_file_skills = False  # markdown skills are inlined into prompts

    def build_cmd(self, o, full_prompt, skill_files):
        # Claude Code headless: `claude -p "<prompt>"` is one
        # non-interactive turn. Agent/mode/title/thinking have no frozen
        # headless flag, and effort has no CLI translation — both raise
        # loudly instead of silently degrading.
        for k in ("agent", "mode", "title", "thinking"):
            if o.get(k):
                raise self.unavailable(k)
        if o.get("effort") in ("low", "high"):
            raise self.unavailable("effort")
        if o.get("dry_run"):
            # claude's headless read-only shape: no permission grants at
            # all — with --permission-prompts none, anything that would
            # prompt (every edit/write) is denied instead
            if o["auto"]:
                o = dict(o, auto=False)
        full_prompt = self._inline_skills(full_prompt, skill_files)
        cmd = ["claude"]
        if o["model"]:
            cmd += ["--model", o["model"]]
        if o["auto"]:
            # acceptEdits auto-approves file edits; Bash rides along in
            # the allowedTools allowlist (permission rule syntax)
            cmd += ["--permission-mode", "acceptEdits",
                    "--allowedTools", "Read,Edit,Bash"]
        # always unattended: anything that would prompt is denied
        # instead (requires CLI >= 2.1.259; in a -p run with no host
        # these requests are denied either way, so it is safe headless)
        cmd += ["--permission-prompts", "none"]
        if o["session"]:
            cmd += ["--resume", o["session"]]
        cmd += ["--output-format", "json", "-p", full_prompt]
        return cmd, full_prompt

    def parse_output(self, stdout, want_stats):
        # --output-format json: one JSON object on stdout with at
        # minimum result, session_id, total_cost_usd and usage fields.
        obj = None
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                cand = json.loads(line)
            except ValueError:
                continue
            if isinstance(cand, dict) and "result" in cand:
                obj = cand
                break
        if obj is None:
            # not JSON (CLI failure text lands on stdout) — pass through
            return stdout.strip(), None
        answer = (obj.get("result") or "").strip()
        if not want_stats:
            return answer, None
        info = {
            "model_s": None,  # claude reports cost and tokens, not seconds
            "parts": 1 if answer else 0,
            "chars": len(answer),
            "session": obj.get("session_id"),
            "cost_usd": obj.get("total_cost_usd"),
        }
        usage = obj.get("usage") or {}
        if usage:
            info.update({
                "input_tokens": usage.get("input_tokens"),
                "cached_input_tokens": usage.get("cache_read_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            })
        return answer, info


register_backend("opencode", _OpenCodeBackend)
register_backend("codex", _CodexBackend)
register_backend("pi", _PiBackend)
register_backend("openhands", _OpenHandsBackend)
register_backend("claude", _ClaudeBackend)

# Commands whose answers must be pure facts about the world, never colored
# by conversation history (paradigm law: context memory colors dialogues,
# never facts). Recall is skipped for these; recording still happens.
