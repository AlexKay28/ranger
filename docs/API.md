# ranger API reference

Complete reference for everything `ranger` ships. Every public name on this
page is enforced by `tests/test_docs.py` — if a method or setting is added
to the code but missing here, the suite fails.

Version 0.4.0 · Module: `ranger` · Single class: `ranger.Ranger`

---

## Installation & requirements

```bash
pip install -e .          # or: pip install .
```

Requires the `opencode` CLI on PATH (https://opencode.ai). Old-distro-pip
users: `pip install -U pip` fixes missing-`build_editable` editable installs.

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
| `ranger.DEFAULT_MODEL` | str | Package-default model ID. |
| `ranger.__version__` | str | Package version. |

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

### Per-call overrides

Every command method (`ask`, `summarize`, `write`, `do`, `search`, `check`,
`until`) accepts any of the run settings above as a keyword, applying it to
that single call only. Unknown keywords raise `TypeError` immediately —
typos fail loudly, never silently. Priority rules:

- Per-call value beats constructor value.
- Model: `model=` argument → `RANGER_MODEL` env → package default.
- Agent selection: per-call `agent=` → per-call `mode=` → constructor
  `mode=` → constructor `agent=`.
- `effort="high"` implies `--thinking` on that run unless nothing stronger
  was requested; `effort` ∈ {low, medium, high} — anything else raises
  (`ValueError` at construction, `TypeError` per-call).

### `with_config(**overrides) -> Ranger`

Returns a **copy** of the agent with settings overridden (the original is
untouched). Accepts every constructor run-setting plus `cwd` (normalized to
an absolute path). Unknown keys raise `TypeError`.

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
without it a `ranger_<slug>_<timestamp>.md` name is generated in the
agent cwd (empty tasks fall back to slug `ranger_out`).

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
file reads) and answer with **YES or NO as the first word**; ranger parses
it (punctuation-tolerant: "Yes," / "no," pass) and returns `True`/`False`.
An unparseable reply raises `RangerError` — check never guesses.

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
- Subsequent runs recall the most recent messages that fit inside
  `memory_budget` characters, prepended as a `## Previous interaction`
  block before the `## Current request`.
- `memory=False` (constructor or single call) disables both recording and
  recall. `gate()` and `models()` never touch the transcript.

| Method | Effect | Returns |
|---|---|---|
| `context_summarize()` | Asks the agent for a digest of the recorded history; history left untouched. | `str` (empty if no history) |
| `context_compact()` | Replaces the whole history with one `{"role": "system", "content": digest}` message — future runs recall a bounded summary. | `str` digest |
| `context_clear()` | Wipes the recorded context. | the previous list |

---

## Skills allow-list

`skills` entries resolve by type:

| Entry | Behavior |
|---|---|
| markdown file path | attached with opencode's real `--file` flag |
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

`Ranger.models(match=None) -> list[str]` (static): runs `opencode models`,
returns the model IDs, optionally filtered by case-insensitive substring.
No agent, no tokens, no context recording.

## Live progress UI

When `stderr` is a TTY and `pretty=True` (default), each command draws one
morphing opencode-wizard-style line — spinner + elapsed clock while running
(`⠹ search · TODO items in this repo · 00:03`), settling as
`✓ search · 00:07 · <first line of the answer>` or `✗ … · <error>` on
failure. Output is **stderr-only**: returned strings and your stdout stay
byte-clean. Auto-off in pipes/tests; `NO_COLOR` strips colors; `pretty=False`
silences.

## Errors

| Situation | Raised |
|---|---|
| `opencode` not on PATH | `RangerError("opencode CLI not found…")` |
| run exits non-zero (bad model, harness error) | `RangerError` with stderr |
| run exceeds `timeout` | `RangerError("… timed out …")` |
| `write()` file missing after the run | `RangerError` |
| `check()` unparseable verdict | `RangerError` |
| unknown per-call keyword | `TypeError` |
| unknown `with_config` key | `TypeError` |
| invalid `effort` | `ValueError` (constructor), `TypeError` (per-call) |
| skills directory with no markdown | `RangerError` |

## Prompt contracts, for the curious

Each command wraps your input in a frozen prompt the agent must honor:

- `summarize`: read `{absolute path}`, reply summary only.
- `write`: write the file at `{path}`, reply with the path only.
- `do`: accomplish `{goal}` with tools, report what changed.
- `search`: grep for `{goal}`, reply `file:line` report, **no code changes**.
- `check`: decide TRUE/FALSE for `{condition}`, must verify, first word YES/NO.
- `until`: each iteration, "name ONE concrete next step, one line."

These templates are what the unit tests pin — changing a command's prompt
contract is a breaking change, visible in review.
