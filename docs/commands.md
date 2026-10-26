# Ranger command catalog

Every Ranger method is **one headless `opencode run`** wrapped in a prompt
template. Methods only differ in (a) the prompt contract with the agent and
(b) the post-check Python performs on the result (e.g. "file must exist").

Status legend:

- ✅ **shipped** — in `ranger/__init__.py`
- 🔜 **next** — trivial to add, same pattern as shipped ones
- 🌱 **later** — needs more than one prompt template (polling, parsing, safety)

## Discovery & configuration (shipped alongside the commands)

### `Ranger.models(match=None) -> list[str]`
Lists `opencode models` IDs; optional case-insensitive substring filter.
Static method, no agent run needed.

### `agent.with_config(**overrides) -> Ranger`
Immutable-configured copy of the agent — keep a fast one and a smart one side
by side. Accepts any of `model`, `timeout`, `auto`, `session`, `agent`, `title`,
`thinking`, `cwd`.

### Per-call overrides
Every command method takes the same run settings as keywords for that single
call: `model=`, `timeout=`, `auto=`, `session=`, `agent=` (opencode agent name,
e.g. `"build"`, `"plan"`), `title=`, `thinking=`. Unknown keywords raise
`TypeError`.


### `agent.context_summarize() -> str`
Digest of the recorded session history (an ask-powered summary; history
itself is untouched).

### `agent.context_compact() -> str`
Collapse the whole history into a single `system` digest message — future
runs recall the bounded summary instead of the full transcript.

### `agent.context_clear() -> list[dict]`
Wipe recorded context; returns what was cleared.

All commands auto-record their exchange into `agent.context` (OpenAI message
format); dialogue commands (`ask`, `do`, `edit`, `plan`, `write`, `context_*`) also recall
recent history within a character budget, while fact commands (`check`, `critique`,
`read`, `search`, `summarize`, `test`) always run history- and session-independent — context
memory colors your dialogues, never your facts. `memory=False` on the
constructor or any single call disables recording and recall.

### Skills allow-list (shipped)
`Ranger(skills=[...])` or any per-call `skills=[...]` grants the agent
extra skills/tools: markdown files and directories attach via opencode's
`--file` flag (the codex backend inlines them into the prompt); plain-prose
entries are injected into the prompt as
operating grants. `with_config(skills=...)` carries an allow-list on a
configured copy.

### Mode / effort / stats (shipped)
- `mode="build"` — run as a named opencode agent (build/plan/general or a
  custom one from the project's opencode config). Per-call override wins;
  legacy `agent=` still accepted.
- `effort="low|medium|high"` — depth directive on every run: low = brevity
  bias, high = forces thinking blocks + verify-before-answering.
- `stats=True` — JSON-mode runs; after each command `agent.last` holds
  `wall_s`, `model_s`, `parts`, `chars`, `session`.

## ✅ Shipped — core commands

### `until(goal, max_iter=5, gate_cmd=None, condition=None) -> dict`
The loop primitive. Each iteration: `ask` for ONE next step, `do` it, then a
mechanical verdict — `gate_cmd` (pure exit code) or `condition` (agent YES/NO).
Returns `{"achieved", "iterations", "steps", "report"}`; exhausted budget means
`achieved: False`, honestly, never a sympathy iteration. The gate is also
evaluated **before** any work: a green-up-front gate returns
`already_green: True` with zero iterations — a vacuous gate can never
masquerade as an agent achievement.

### `ask(prompt) -> str`
Raw prompt, raw answer. The escape hatch every other method is built on.

```python
agent.ask("what design pattern is used in parser.py?")
```

### `summarize(file) -> str`
Read a file, return a concise summary. Great for context-building before a
bigger call.

```python
agent.summarize("notes.md")
```

### `read(file, question) -> str`
Ask a precise, read-only question about one file instead of receiving a general
summary. The path resolves against the agent cwd; the call is history- and
session-independent and its prompt forbids filesystem changes.

```python
agent.read("src/parser.py", "What input shapes can raise ValueError?")
```

### `write(task, path=None) -> str` *(returns file path)*
Freeform document generation. The file **is** the answer; Python verifies it
exists before returning the path. `path=` pins the exact target file.

```python
agent.write("a one-page report on the auth flow", path="docs/auth.md")
```

### `do(goal) -> str`
The CLI-work-horse: mutate the filesystem (create/edit/delete files, run
commands) like a human with a shell, return a report of what changed.

```python
agent.do("rename all *.txt in data/ to *.md")
```

### `edit(file, instruction) -> str`
Make one bounded change to one existing file. The prompt pins its absolute
path and forbids other filesystem changes; ranger also verifies that target's
mtime changed before returning the agent report. Use `do()` for free-roaming
work across files.

```python
agent.edit("src/parser.py", "Handle empty input with a clear error")
```

### `plan(goal) -> str`
Think without touching. Produces a numbered implementation plan for a goal —
reading and analysis only, no filesystem changes. Each step references
concrete files and commands, and the reply ends with the single riskiest
assumption. A dialogue command: the exchange is recorded into `agent.context`.

```python
agent.plan("migrate the config loader to TOML")
```

### `search(goal) -> str`
Read-only codebase search. Returns a `file:line` multiline report. Never edits.

```python
agent.search("where do we parse config files?")
```

### `test() -> str`
Run the project's existing test suite and return a concise, read-only failure
diagnosis: relevant evidence, likely root causes, and minimal fix direction.
It never modifies files and runs without recalled history or a harness session.

```python
agent.test()
```

### `critique(file_or_diff) -> str`
Read-only, focused code review of a file path or diff. It reports concrete bugs,
risks, security issues, and missing tests without editing files; it is history-
and session-independent. Unlike multi-agent `review()`, it returns prose rather
than a structured verdict.

```python
agent.critique("src/parser.py")
```

### `check(condition) -> bool`
Boolean verdict on repo state. The agent must actually verify (commands, file
reads) and answer with YES/NO as the first word; unparseable answers raise
`RangerError` instead of guessing. The loop-grade primitive for gates.

### `gate(command) -> bool`
Fully mechanical sibling of `check` — no model at all: a shell command whose
exit code decides. `agent.gate("python -m pytest -q")`. In `until`, `attempt`
and `resolve`, `gate_cmd` also accepts a **list** of commands — run in order,
short-circuiting on the first red, with a per-part breakdown in `last_gate`
so a failure names the exact sub-check that tripped.

### `attempt(goal, gate_cmd=None, condition=None) -> dict`
The single-shot honest sibling of `until`: ONE `do()` of the goal, then a
mechanical verdict — `gate_cmd` (pure exit code), else `condition` (agent
YES/NO), else `check("the goal is fully achieved: {goal}")`. Like `until`,
the gate is evaluated **before** any work: an already-green gate returns
`passed: True, already_green: True` with zero agent runs. Returns
`{"passed", "already_green", "goal", "report", "last_gate"}` — `last_gate`
carries the gate's own evidence, so a red outcome is a diagnosis.

```python
agent.attempt("add __repr__ to Parser",
              gate_cmd="python -m pytest -q tests/test_parser.py")
```

### `resolve(goal, max_iter=3, gate_cmd=None, condition=None) -> dict`
The resolver distilled into one call: pre-flight gate check (already green →
`status: "ALREADY_GREEN"`, zero model runs), then ONE `plan()` (think before
touching), then a bounded loop of plan-guided `do()` rounds with a mechanical
verdict each — no sympathy pass when the budget ends. Returns
`{"status": "ALREADY_GREEN"|"PASS"|"FAILED", "goal", "plan", "iterations",
"report", "last_gate"}`. Gates must assert contracts, not prose.

```python
agent.resolve("add coverage for parse()",
              gate_cmd=["python -m pytest -q",
                        "python -m pytest -q -k parse"])
```

### `verify_claims(topic, max_claims=5) -> list[dict]`
Deep-research reasoning command: one `ask()` extracts up to `max_claims`
verifiable claims about the topic (one per line, each prefixed `CLAIM:`),
then EVERY claim is verified mechanically with a fresh, memory-free
`check()`. Returns `[{"claim", "verdict": "PASS"|"FAIL"|"UNCERTAIN",
"ok": True|False|None}]` — a `check()` that raises `RangerError` becomes
`UNCERTAIN`, never a guess. No parseable `CLAIM:` lines raises
`RangerError`.

```python
agent.verify_claims("the retry logic in ranger's _run()")
```

## ✅ Shipped — multi-agent interactions (5)

Verdicts are grammar, budgets are honest, reviewers run free of their own
chat history. Full contracts in [API.md](API.md#multi-agent-interactions).

### `second_opinion(other, prompt) -> dict`
Same prompt, two agents: `{"mine", "theirs", "differs"}`.

### `review(subject, author=None) -> dict` *(method on the REVIEWER)*
APPROVE/REJECT/REQUEST_CHANGES verdict with findings; unparseable answers
raise `RangerError` — review never guesses. The reviewer sees the subject,
not the author's chat history.

### `refine_with(critic, goal, max_iter=3) -> dict`
The two-agent `until`: do → review → fix → repeat, until the critic approves
or the budget runs out.

### `challenge(other, claim=None, rounds=2) -> dict` *(method on the CHALLENGER)*
Adversarial attack on another agent's claim or last answer.

### `debate(agent_a, agent_b, topic, rounds=2, judge=None) -> dict` *(module-level)*
Symmetric exchange, optionally refereed by a third agent.

## 🔜 Next batch (planned, same pattern) (1)

## 🌱 Later (3)

Bigger contracts — multi-step verification, retries, or safety rails.

### `fix(goal_or_error) -> str`
Diagnose and repair. The valuable primitive for agentic loops: pairs with
`test` to validate the fix before returning. Requires result-parsing +
retry-on-failure shell around `do`.

### `transform(paths_pattern, instruction) -> str`
Batch edit across many files ("add type hints to every function in src/*.py").
Requires multiple `edit` runs with progress tracking.

### `commit(message=None) -> str`
Ask the agent to stage and commit its own work with a sensible generated
message. Needs safety rails (refuse if cwd isn't a repo, no force-pushes).

## Non-goals

- No streaming/chat style interface — blocks until the run finishes, returns a
  string. That's what makes it composable.
- No remote-agent management: one agent, one machine, real time.

## The point

`until` shipped — the README's manual loop is now one call:

```python
agent.until("parser.py: implement the TODO, all tests green",
            gate_cmd="python -m pytest -q")
```

Shipped surface today includes targeted `critique()` and bounded `edit()` alongside free-roaming `do()`,
plus the multi-agent interactions, the
context/memory trio (`context_summarize`/`context_compact`/`context_clear`)
and the run-time knobs (`mode`, `effort`, `stats`, `skills`). The 🌱 tier
that remains (fix/transform/commit) composes on top of it.
