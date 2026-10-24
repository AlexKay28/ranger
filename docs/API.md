# ranger API reference

Complete reference for everything `ranger` ships. Every public name on this
page is enforced by `tests/test_docs.py` — if a method or setting is added
to the code but missing here, the suite fails.

Version 0.6.1 · Module: `ranger` · Single class: `ranger.Ranger`

---

## Installation & requirements

```bash
pip install -e .          # or: pip install .
```

Requires a harness CLI on PATH: [opencode](https://opencode.ai) (the
default backend) and/or [codex](https://github.com/openai/codex) — opencode
is only needed if you actually use the default backend. On a distro-pegged
pip (e.g. 22.x) an editable install can fail with "build backend is missing
the build_editable hook" — fix the tool, not the package:
`pip install -U pip`, then retry.

## Environment variables

| Variable | Effect |
|---|---|
| `RANGER_MODEL` | Default model when `Ranger(model=...)` is not given. Priority: explicit `model=` argument → `RANGER_MODEL` → package `DEFAULT_MODEL` (`openrouter/anthropic/claude-sonnet-4.5`). |
| `NO_COLOR` | Disables terminal colors in the live progress UI (UI is on stderr only). |

Operational detail: `opencode run` resolves its working directory from the
`PWD` environment variable, not merely from the process cwd — ranger sets
`PWD` on every run when `cwd` is provided, so files reliably land where you
pointed the agent.

## Module attributes

| Name | Kind | Meaning |
|---|---|---|
| `ranger.Ranger` | class | The agent class (below). |
| `ranger.RangerError` | exception | Subclass of `RuntimeError`; raised for every harness failure. |
| `ranger.DEFAULT_MODEL` | str | Package-default model ID (opencode backend). |
| `ranger.backends()` | function | Sorted names of all registered harness backends. |
| `ranger.register_backend(name, cls)` | function | Register a custom harness adapter — see Backends below. |
| `ranger.__version__` | str | Package version. |

Design backbone: [PARADIGM.md](PARADIGM.md) — the agent is a function call;
Python owns the loop.

---

## Ranger constructor — all settings

```python
ranger.Ranger(
    model=None,            # str | None — opencode model id "provider/model"
    cwd=None,              # str | Path — agent working directory
    timeout=600.0,         # seconds; RangerError on expiry
    auto=True,             # auto-approve tool permissions
    session=None,          # opencode session id to continue/create
    agent=None,            # legacy alias of mode (kept for compatibility)
    mode=None,             # named opencode agent: "build"/"plan"/"general"/custom
    title=None,            # session title for runs
    thinking=False,        # request thinking blocks
    pretty=True,           # live wizard-style UI on stderr
    memory=True,           # record + recall conversation context
    memory_budget=20000,   # recall cap in characters
    skills=None,           # allow-list: md files/dirs via --file, prose grants
    effort="medium",       # "low" | "medium" | "high" depth directive
    stats=False,           # JSON-mode runs; telemetry in agent.last
)
```

### Per-run settings, at a glance

| Setting | Default | Meaning |
|---|---|---|
| `model` | `RANGER_MODEL` env → `DEFAULT_MODEL` | opencode model id, "provider/model" |
| `cwd` | `None` (process cwd) | agent working directory (also drives the `PWD` fix) |
| `timeout` | `600.0` | seconds before `RangerError` |
| `auto` | `True` | auto-approve tool permissions (headless-friendliness) |
| `session` | `None` | opencode session id to continue/create |
| `agent` | `None` | legacy alias of `mode` |
| `mode` | `None` | named opencode agent ("build", "plan", "general", custom) |
| `title` | `None` | session title for runs |
| `thinking` | `False` | request thinking blocks (forced on by `effort="high"`) |
| `pretty` | `True` | live wizard UI on stderr (auto-off outside TTY) |
| `memory` | `True` | record + recall conversation context |
| `memory_budget` | `20000` | recall cap in characters |
| `skills` | `None` | allow-list: files/dirs via `--file`, prose as grants |
| `effort` | `"medium"` | "low"/"medium"/"high" depth directive |
| `stats` | `False` | JSON-mode runs + telemetry in `agent.last` |
| `backend` | `"opencode"` | which harness to drive — see Backends below |

### Per-call overrides

Every command method (`ask`, `summarize`, `write`, `do`, `search`, `check`,
`until`) accepts any of the run settings above as a keyword, applying it to
that single call only — **except `cwd`**, which is agent identity and is
constructor/`with_config`-only. Unknown keywords raise `TypeError`
immediately — typos fail loudly, never silently. Priority rules:

- Per-call value beats constructor value.
- Model: per-call `model=` → constructor `model=` → `RANGER_MODEL` env →
  package default **resolved per effective backend** (a per-call
  `backend=` switch never inherits the other backend's default; codex
  without an explicit model uses its own `config.toml` default and passes
  no `-m` at all).
- Agent selection: per-call `agent=` → per-call `mode=` → constructor
  `mode=` → constructor `agent=`.
- `effort="high"` implies `--thinking` on that run unless nothing stronger
  was requested; `effort` ∈ {low, medium, high} — anything else raises
  (`ValueError` at construction, `TypeError` per-call).
- **Fact commands run pure**: `check`, `search` and `summarize` drop
  `session=` and skip history recall — a verdict is about the repo, not
  the chat.

### `with_config(**overrides) -> Ranger`

Returns a **copy** of the agent with settings overridden (the original is
untouched). Accepts every constructor run-setting plus `cwd` (normalized to
an absolute path; `cwd=None` restores the process-cwd default) and
`memory_budget`. Unknown keys raise `TypeError`. The copy takes a
**snapshot** of `context` and `last` — the two agents' histories diverge
from the copy point on.

    smart = ranger.Ranger(model="…sonnet…")
    fast = smart.with_config(model="…flash…", mode="build")

---

## Commands

### `ask(prompt, **ov) -> str`

Raw prompt in, raw answer out. The escape hatch all other commands build on.

### `summarize(file, **ov) -> str`

Reads a file (path may be absolute or relative) and returns a concise
summary. **Relative paths resolve against the agent's `cwd`, never the
Python process's.**

### `write(task, path=None, **ov) -> str`

The file **is** the answer: the agent writes a complete document and must
reply with the path only. Returns the file path, which ranger has
**verified to exist** — if the agent failed to write it, `RangerError` is
raised instead of returning a lie. `path=` pins the exact target file;
without it a `ranger_<slug>_<timestamp>_<random>.md` name is generated in
the agent cwd — the slug is sanitized to safe filename characters (a task
like `"describe src/parser.py"` cannot smuggle a subdirectory), the random
suffix prevents collisions between repeated tasks, and the postcondition is
`out.is_file()` (an existing *directory* does not satisfy the contract).
Empty tasks fall back to slug `ranger_out`.

### `do(goal, **ov) -> str`

Free-roaming filesystem work: the agent may create/edit/delete files and
run shell commands in its cwd, then reports what it did, which files
changed, and what failed. This is "run it like from the CLI".

### `search(goal, **ov) -> str`

Read-only codebase search (grep/glob over the working directory). Returns a
multiline `file:line` report. The prompt forbids code changes. **Local
files only — the prompt contract steers away from web tools; there is no
technical wall.** For web work, use `ask()` with an explicit web-research
prompt.

### `check(condition, **ov) -> bool`

Boolean verdict on repo state. The agent must actually verify (commands,
file reads) and answer with a **line consisting only of YES or NO** (an
early first-word YES/NO also parses, modulo punctuation). ranger returns
`True`/`False` and **never guesses**: an unparseable reply, a reply whose
first line confesses inability ("cannot verify", "unknown"...), or
**contradictory YES and NO verdict lines** all raise `RangerError`. History
and harness sessions are dropped for the call — it is a pure query.

### `gate(command, timeout=None) -> bool`

The model-free sibling of `check`: runs a shell command in the agent cwd
and returns `exit_code == 0`. Timeout (default: the agent's `timeout`)
returns `False`. Pure `subprocess` — never recorded into context, never
costs tokens.

### `until(goal, max_iter=5, gate_cmd=None, condition=None, **ov) -> dict`

The loop primitive. Each iteration: `ask` for ONE concrete next step toward
the goal → `do` executes it → mechanical verdict. The verdict is `gate_cmd`
(pure exit-code gate) if given, else `condition` (agent-verified YES/NO),
else `check("the goal is fully achieved: {goal}")`.

Returns:

```python
{
  "achieved": bool,     # False if max_iter was exhausted — honestly
  "iterations": int,    # 1..max_iter
  "steps": [str, ...],  # the next-step lines the agent chose
  "report": str,        # the agent's last do() report
}
```

There is no sympathy iteration: an agent claiming "almost done" cannot buy a
fifth round — only the gate can.

---

## Context state (memory)

`agent.context` is a list of classic **OpenAI-format** messages:
`{"role": "user"|"assistant"|"system", "content": str}`.

- Every command automatically records its **raw** request and answer (never
  the context-prefixed prompt, so transcripts cannot nest/explode).
- Subsequent **dialogue** commands (`ask`, `do`, `write`, `context_*`)
  recall the most recent messages that fit inside `memory_budget`
  characters, prepended as a `## Previous interaction` block before the
  `## Current request`.
- **Fact commands run pure**: `check`, `search` and `summarize` never see
  conversation history — a verdict must not be a function of chat
  (paradigm law: context memory colors your dialogues, never your facts).
- `memory=False` (constructor or single call) disables both recording and
  recall. `gate()` and `models()` never touch the transcript.

| Method | Effect | Returns |
|---|---|---|
| `context_summarize()` | Asks the agent for a digest of the recorded history; history left untouched. | `str` (empty if no history) |
| `context_compact()` | Replaces the whole history with one `{"role": "system", "content": digest}` message — future runs recall a bounded summary. | `str` digest |
| `context_clear()` | Wipes the recorded context. | the previous list |

---

## Skills allow-list

`skills` entries resolve by type — **relative paths resolve against the
agent's `cwd`** (the world the harness operates in), and are converted to
absolute paths before the harness sees them, so opencode and codex attach
the same file:

| Entry | Behavior |
|---|---|
| markdown file path | attached with opencode's real `--file` flag; codex inlines the file text into the prompt |
| directory path | every `*.md` inside is attached (sorted); no markdown → `RangerError` |
| plain prose string | injected as a `## Allowed skills / operating grants` bullet — applied after context recall, so it can never be overwritten |

`Ranger(skills=[...])` sets the default; per-call `skills=[...]` replaces it
for that one run; a single entry may be passed bare (`skills="SKILL.md"`).

## Effort

| Effort | Prompt directive | Thinking blocks |
|---|---|---|
| `low` | "be brief, minimal ceremony" | off |
| `medium` | none | as configured |
| `high` | "work carefully, verify before replying" | forced on |

## Stats

`stats=True` switches runs to `--format json` (still returning the plain
string) and records telemetry after each command:

```python
agent.last == {
  "label":   "do",          # which command ran
  "wall_s":  6.83,          # round-trip seconds
  "model_s": 4.27,          # model part time, from opencode timing blocks
  "parts":   1,             # number of text parts
  "chars":   265,           # answer length
  "session": "ses_…",       # opencode session id
}
```

Honesty note: the opencode JSON stream carries timing and session data but
**no token/cost accounting** — ranger reports only what mechanically exists.

## Models discovery

`Ranger.models(match=None, backend="opencode") -> list[str]` (static):
delegates to the backend adapter. opencode runs `opencode models`; codex
cannot enumerate models and raises `RangerError` pointing at
`~/.codex/config.toml` / `model=`. No agent, no tokens, no context recording.

## Multi-agent interactions

Compositions, never a runtime (paradigm law 6): every pattern below is
ordinary typed calls between agents. Three invariants hold across all of
them: **verdicts are grammar** (APPROVE/REJECT/REQUEST_CHANGES,
SUSTAINED/WITHDRAWN — unparseable replies raise, never guess), **budgets
are honest** (exhausted rounds leave `passed: False` / `survived: True`
per contract), and **reviewers, challengers and judges run free of their
own chat history** (`memory`/`session` are dropped for those calls) — a
verdict is about the work, not about anyone's conversation. Cross-agent
material always travels explicitly labeled as *claims to verify*.

With two agents — a `builder` and a `critic` — and a third `skeptic`:

```python
both    = builder.second_opinion(critic, prompt)   # {mine, theirs, differs}
verdict = critic.review(subject, author=builder)   # reviewer verifies facts
outcome = builder.refine_with(critic, goal)         # do -> review -> fix -> repeat
duel    = critic.challenge(builder, rounds=2)       # adversarial claim attack
talk    = ranger.debate(builder, critic, topic,    # symmetric exchange
                        rounds=2, judge=skeptic)
```

### `review(subject, author=None) -> dict` (method on the REVIEWER)

Reviews the `subject` in the agent's cwd. `author` may be another Ranger
(a latest recorded answer is injected as claims to verify — never
truth), a bare string, or `None`. Reply contract is frozen and strictly
validated: exactly ONE `VERDICT: APPROVE|REJECT|REQUEST_CHANGES` line,
plus non-empty `FINDINGS:` and `CHANGES:` sections (both may span
multiple lines). Zero, conflicting, invalid, or incomplete replies raise
`RangerError` — review never guesses. Returns
`{"passed": bool, "verdict": str, "findings": str, "changes": str}` —
`passed` is True only on APPROVE.

### `challenge(other, claim=None, rounds=2) -> dict` (method on the CHALLENGER)

Attacks the defender `other`'s claim (default: its latest recorded
assertion). Each round: `ATTACK: <attack>` → defense ending with a
final `DEFENDED` or `CONCEDED` line → the challenger rules on that
attack alone via `RULING: SUSTAINED|WITHDRAWN`. Every reply is
mechanically validated: a missing `ATTACK:` marker, a defense without
exactly one terminal status, or zero/multiple `RULING:` lines raises
`RangerError`. Attacks and rulings run memory- and session-free (law 4);
the defense keeps the defender's own settings. Any SUSTAINED ruling
(or a CONCEDED defense) ends with `survived: False` immediately; all
withdrawn (or budget exhausted) leaves `survived: True`. Returns
`{"survived": bool, "rounds": [{"attack", "defense", "ruling"}...],
"summary": str}`.

### `second_opinion(other, prompt) -> dict`

Same prompt to two agents. Returns
`{"mine": str, "theirs": str, "differs": bool}` — normalized comparison,
no judgment, no winner.

### `refine_with(critic, goal, max_iter=3) -> dict`

The two-agent `until`: `do` the step → `critic.review(subject=goal,
author=report)` gates the round on the work report from THIS attempt
(as unverified claims — independent of memory settings) →
REQUEST_CHANGES/REJECT feed the requested changes verbatim into the
next attempt. Only a mechanical APPROVE ends the loop early. Returns
`{"approved": bool, "iterations": int, "report": str, "reviews":
[review dicts...]}`. Passing `session=` raises `TypeError` before any
work runs (the gate is session-free by contract).

### `debate(agent_a, agent_b, topic, rounds=2, judge=None) -> dict` (module-level)

Symmetric position exchange; each side sees the opponent's last position
labeled as unverified. The optional `judge` agent (validated before any
speaker runs; runs memory- and session-free) digests where the positions
factually disagree and what evidence would settle it — it never crowns
a winner. Returns
`{"transcript": [{"round", "a", "b"}...], "digest": str | None}`.

Validation: `rounds`/`max_iter` must be non-negative ints (`ValueError`);
wrong-typed `author`/`critic`/agents/judge raise `TypeError` — up front,
never after work has already run.

## Backends (harness adapters)

`Ranger(backend="codex")` drives a different headless harness with the
identical public API. All harness-specific translation — CLI flags, output
schemas, sandbox semantics — lives in one adapter class per backend; the
command contracts, context memory and loops are untouched (paradigm law 7:
the harness is a replaceable data plane).

Capability map:

| Setting | opencode | codex |
|---|---|---|
| `model` | `--model` (package default if unset) | `-m`; unset → codex config.toml default |
| `cwd` | subprocess cwd + `PWD` env fix | native `-C` flag (resume runs use the process cwd) |
| `auto` | `--auto` | `--approve-for-me` (workspace-write); `auto=False` → `-s read-only` (exec cannot be interactive) |
| `session` | `--session <id>` | `codex exec resume <id>` (model and a requested read-only policy still apply on resume) |
| `mode` / `agent` | `--agent <name>` | not supported — `RangerError` if set |
| `title` | `--title` | not supported — `RangerError` if set |
| `thinking` / `effort` | `--thinking`; effort as prompt directive | `-c model_reasoning_effort="low|high"` |
| skills: files/dirs | native `--file` attachment | inlined into the prompt (codex has no attachment flag) |
| `stats` | wall + model seconds, parts, session id | wall, parts, thread id **and real token usage** (`input_tokens`, `cached_input_tokens`, `output_tokens`) |
| `gate()` | harness-free — plain subprocess on every backend | same |

codex runs always capture in JSON (its stream is JSONL; ranger parses
`agent_message` items). opencode captures plain text unless `stats=True`.

### Adding your own harness

```python
import ranger

class MyHarness(ranger._Backend):
    name = "mine"
    install_hint = "install it from https://example.com"

    def build_cmd(self, o, full_prompt, skill_files):
        # o = resolved run options; return (argv, possibly-rewritten prompt)
        return ["mycli", "--run", full_prompt], full_prompt

    def parse_output(self, stdout, want_stats):
        # return (answer_text, telemetry_dict_or_None)
        return stdout.strip(), None

ranger.register_backend("mine", MyHarness)
agent = ranger.Ranger(backend="mine")
```

`build_cmd` decides flags and may inline skills; `parse_output` converts
the harness stream into the answer plus optional telemetry merged into
`agent.last`. Implement `list_models(match)` too if the CLI can enumerate
models. Custom registrations live in-process only.

## Live progress UI

When `stderr` is a TTY and `pretty=True` (default), each command draws one
morphing opencode-wizard-style line — spinner + elapsed clock while running
(`⠹ search · TODO items in this repo · 00:03`), settling as
`✓ search · 00:07 · <first line of the answer>` or `✗ … · <error>` on
failure. Output is **stderr-only**: returned strings and your stdout stay
byte-clean. Auto-off in pipes/tests; `NO_COLOR` strips colors; `pretty=False`
silences.

## Timeouts & cancellation — what is actually guaranteed

When a run exceeds `timeout`, ranger kills the harness CLI process and
raises `RangerError`. Honesty about the boundary:

- The CLI is spawned in its **own process group**, so its immediate
  children can be identified and torn down by the OS.
- `gate()` commands run in their **own process group**: a timeout (returns
  `False`) or an interrupt (re-raises) kills the whole group — no orphaned
  pipeline keeps running.
- The harness CLIs run in their own process group too, but they are not
  always the whole story: opencode executes through a background
  **service**, codex through local subprocesses. A stop cancels the CLI
  client; work already queued inside the harness may still complete on
  its side. ranger cannot cancel what the harness does not expose a
  cancellation handle for.

If you need hard cancellation, run long goals with a small `timeout` in a
sandbox/throwaway directory, or verify outcomes mechanically afterwards
(that is what `check`/`gate`/`until` are for).

### Ctrl+C / kernel interrupt

Interrupting (`KeyboardInterrupt`) stops the Python call immediately; the
CLI client process is killed and the live progress UI prints an honest
`✗ … interrupted by user` line and retires its spinner on **every** exit
path (success, error, interrupt) — a cancelled call never leaves a
ticking progress thread behind (the classic wedged-notebook symptom).
Long loops (`until`/`refine_with`/`challenge`) are honest about
cancellation: nothing is claimed achieved, but the partial progress
already paid for (steps, reviews, rounds) survives inside the
`KeyboardInterrupt` message instead of evaporating. The remote-harness
caveat above still applies: grandchildren already spawned may outlive
the interrupt — `pkill -f "opencode run"` (or `codex exec`) cleans up
strays.

## Errors

| Situation | Raised |
|---|---|
| harness CLI not on PATH | `RangerError("<backend> CLI not found…")` |
| agent `cwd` does not exist | `RangerError` |
| harness process could not be spawned (permissions, ENOEXEC, ...) | `RangerError` with cause |
| run exits non-zero (bad model, harness error) | `RangerError` with stderr |
| run exceeds `timeout` | `RangerError("… timed out …")` |
| `write()` target is missing **or not a regular file** after the run | `RangerError` |
| `check()` unparseable, unconfident or contradictory verdict | `RangerError` |
| unknown per-call keyword | `TypeError` |
| unknown `with_config` key | `TypeError` |
| invalid `effort` | `ValueError` (constructor), `TypeError` (per-call) |
| invalid `backend` | `ValueError` |
| explicit `session=` passed to `review()` / `debate(judge=...)` | `TypeError` (verdicts run session-free) |
| `until(max_iter=...)` not a non-negative int | `ValueError` |
| skills directory with no markdown | `RangerError` |

## Prompt contracts, for the curious

Each command wraps your input in a frozen prompt the agent must honor:

- `summarize`: read `{absolute path}`, reply summary only.
- `write`: write the file at `{path}`, reply with the path only.
- `do`: accomplish `{goal}` with tools, report what changed.
- `search`: grep for `{goal}`, reply `file:line` report, **no code changes**.
- `check`: decide TRUE/FALSE for `{condition}`, must verify, answer a standalone YES/NO line.
- `until`: each iteration, "name ONE concrete next step, one line."

All prompts travel after an option terminator (`--`), so task text can never
be parsed as CLI flags.

These templates are what the unit tests pin — changing a command's prompt
contract is a breaking change, visible in review.
