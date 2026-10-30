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
`TypeError`. Safety rail overrides: `allow=[globs]`, `deny=[globs]` (deny wins;
each list fully replaces the constructor's) and `dry_run=True` (harness
read-only/plan mode; mutating commands skip their mutation post-checks).
Targeted edits are checked before any subprocess spawns; `do()` probes
git-verifiability up front and audits `git status` against the rails after.
See the Safety rails section of docs/API.md.


### `agent.context_summarize() -> str`
Digest of the recorded session history (an ask-powered summary; history
itself is untouched).

### `agent.context_compact() -> str`
Collapse the whole history into a single `system` digest message — future
runs recall the bounded summary instead of the full transcript.

### `agent.context_clear() -> list[dict]`
Wipe recorded context; returns what was cleared.

### `agent.quote(prompt, label="run", **ov) -> dict`
Price a run BEFORE paying for it — zero model calls, zero side effects.
Composes the exact prompt the matching run would send (the same seam)
and returns `{"backend", "label", "chars_total", "est_tokens_in",
"segments", "skill_files"}`; `segments` splits the bill into `request`,
`recall`, `grants`, `effort` and `other` (inline skill-file bodies and
headers). `est_tokens_in` rounds chars/4 — an estimate, not a bill.
Raise-quoted like the real call: a bad spec fails here, for free.

### `agent.costs -> dict` *(property)*
Cumulative ledger over all completed runs — `{"calls", "chars_in",
"chars_out", "tokens_in", "tokens_out", "wall_s"}`; tokens stay `None`
until a backend reports them. Always recorded, `stats=` not required. In a
`debate`/`refine_with` each agent's ledger is its own.

### `agent.costs_reset() -> dict`
Returns the current ledger and zeroes it — wrap a loop between
`costs_reset()` and `agent.costs` for bounded per-loop accounting:

```python
agent.costs_reset()
result = agent.until("make tests green", gate_cmd="python -m pytest -q")
print(result["iterations"], agent.costs)   # what THIS loop cost
```

All commands auto-record their exchange into `agent.context` (OpenAI message
format); dialogue commands (`ask`, `do`, `edit`, `plan`, `write`, `context_*`) also recall
recent history within a character budget, while fact commands (`check`, `critique`,
`diagnose`, `lint`, `read`, `search`, `summarize`, `test`, `trace`) always run history- and session-independent — context
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

### `until(goal, max_iter=5, gate_cmd=None, condition=None, rollback_on_fail=False) -> dict`
The loop primitive. Each iteration: `ask` for ONE next step, `do` it, then a
mechanical verdict — `gate_cmd` (pure exit code) or `condition` (agent YES/NO).
Returns `{"achieved", "iterations", "steps", "report"}`; exhausted budget means
`achieved: False`, honestly, never a sympathy iteration. The gate is also
evaluated **before** any work: a green-up-front gate returns
`already_green: True` with zero iterations — a vacuous gate can never
masquerade as an agent achievement. With `rollback_on_fail=True` a git snapshot
is taken before round 1 and a red budget restores the working tree
(`rolled_back: True` + `rollback: {"tag", "restored"}` in the result); without
a git repo nothing is claimed — the keys are simply absent.

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

### `trace(symbol) -> str`
Read-only repository-wide call-path analysis. Reports a symbol's definition,
callers, and relevant data-flow relationships with `file:line` evidence; it
runs without recalled history or a harness session.

```python
agent.trace("parse_config")
```

### `test() -> str`
Run the project's existing test suite and return a concise, read-only failure
diagnosis: relevant evidence, likely root causes, and minimal fix direction.
It never modifies files and runs without recalled history or a harness session.

```python
agent.test()
```

### `lint() -> str`
Run the project's configured lint and format checks and return a concise,
read-only diagnosis: the failing check and error evidence plus minimal
remediation. It never modifies files and runs without recalled history or a
harness session.

```python
agent.lint()
```

### `diagnose(error) -> str`
Diagnose a pasted traceback or error log without rerunning a command. The agent
may inspect relevant local code, then returns an evidence-backed likely root
cause and minimal fix direction. It never modifies files and runs without
recalled history or a harness session.

```python
agent.diagnose("ValueError: invalid token")
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

### `extract(request, keys, many=True) -> list[dict] | dict`
Structured-data grammar beyond YES/NO (law 2): the agent verifies facts
read-only and must reply with exactly one JSON array of objects (`many=True`,
default) or one JSON object (`many=False`), every object carrying the named
keys. Malformed JSON, trailing prose, non-object rows or missing keys raise
`RangerError` carrying the raw reply — parsed mechanically, never guessed.
Empty array/object is a legitimate "no matches". History- and
session-independent. Deliberate non-goals: no pydantic dependency, no model
registry, no nested schemas — flat `keys` only.

## ✅ Shipped — async twins & par_map (issue #9)

Additive async twins for the call-family commands — same contracts, same
frozen prompts, byte-identical argv (one shared `_prepare_run()` seam; the
sync methods stay the primary API). Cancellation kills the CLI subprocess,
like `KeyboardInterrupt` on the sync path. No chat, no streaming — complete
strings, exactly like today. Concurrency stays yours: plain awaitables and
one helper, no runtime or scheduler object (law 6).

### `ask_async(prompt, **ov) -> str`
Awaitable twin of `ask` — asyncio-spawned CLI process, identical prompt and
result contract.

### `do_async(goal, **ov) -> str`
Awaitable twin of `do` — same "actually do the work" contract, same report.

### `search_async(goal, **ov) -> str`
Awaitable twin of `search` — read-only codebase lookup, same output shape.

### `write_async(task, path=None, **ov) -> str` *(returns file path)*
Async twin of `write`; raises `RangerError` if the file was not written,
same mechanical post-check.

### `edit_async(file, instruction, **ov) -> str`
Async twin of `edit`; raises `RangerError` if the single target file was
not modified during the run, same mtime post-check.

### `check_async(condition, **ov) -> bool`
Async twin of `check`; the strict YES/NO verdict grammar is shared with the
sync command — one parser, not two.

### `par_map(calls, max_concurrency=8) -> list`
Bounded-concurrency map over independent calls. Each call is a dict with
`method` (`ask` default, `do`, `write`, `edit`, `search`, `check`), optional
`args`/`kwargs`, and an optional `agent` (another `Ranger`, defaults to the
caller). Returns one slot per input, aligned in order: the answer on
success, or the exception instance that call raised — nothing is swallowed.
Every spec is validated **before** any harness is spawned; at most
`max_concurrency` CLI subprocesses run at once. Cancelling the `par_map`
awaitable kills all child processes.

```python
results = asyncio.run(agent.par_map([
    {"method": "search", "args": ["parseSQL defined"]},
    {"method": "ask",   "args": ["list failing checks"]},
    {"method": "check", "args": ["readme mentions license"]},
], max_concurrency=3))
```

### `gate(command) -> bool`
Fully mechanical sibling of `check` — no model at all: a shell command whose
exit code decides. `agent.gate("python -m pytest -q")`. In `until`, `attempt`
and `resolve`, `gate_cmd` also accepts a **list** of commands — run in order,
short-circuiting on the first red, with a per-part breakdown in `last_gate`
so a failure names the exact sub-check that tripped.

## ✅ Shipped — snapshots & rollback (issue #7)

Recoverability for mutating commands and loops, via one git mechanism —
no container sandbox. Snapshots go to the hidden ref
`refs/ranger/snapshots/<tag>` through a temporary index: the real index,
staged state and working tree are never touched. All git plumbing rides the
same mocked `ranger.subprocess` seam as the harness runs.

### `snapshot(tag=None) -> dict`
Commit tracked + untracked-but-not-ignored state to the hidden ref;
`tag=None` auto-names `snap-1`, `snap-2`, …; explicit tags must be unique
and shell-safe (`ValueError` otherwise). Also appends to the Python-side
registry `agent.snapshot_log`. Non-git cwd → honest `RangerError`, never a
phantom snapshot. With `Ranger(snapshots=True)`, `do`/`edit`/`write` take a
best-effort snapshot first (skips are logged, not claimed; default off
keeps their subprocess accounting at exactly one harness run).

### `rollback(tag=None) -> dict`
Restore the working tree to a snapshot (tag, or the last one taken).
`git read-tree --reset -u <tree>` rewinds index+worktree; post-snapshot
untracked leftovers are cleaned **by exact path**, never a shotgun.
HEAD, branches and commit history stay untouched. Returns
`{"tag", "sha", "restored": [...]}` — the paths that actually differed.
Nothing recorded / unknown tag / non-git cwd → `RangerError`.

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

### `resolve(goal, max_iter=3, gate_cmd=None, condition=None, rollback_on_fail=False) -> dict`
The resolver distilled into one call: pre-flight gate check (already green →
`status: "ALREADY_GREEN"`, zero model runs), then ONE `plan()` (think before
touching), then a bounded loop of plan-guided `do()` rounds with a mechanical
verdict each — no sympathy pass when the budget ends. Returns
`{"status": "ALREADY_GREEN"|"PASS"|"FAILED", "goal", "plan", "iterations",
"report", "last_gate"}`. Gates must assert contracts, not prose.
`rollback_on_fail=True` snapshots before round 1 and restores the tree when
the budget ends red (`rolled_back: True` + `rollback: {"tag", "restored"}`);
absent keys mean no snapshot existed — never a claimed restore.

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

## ✅ Shipped — the repair tier (issue #4)

Bounded repair built OUT of the existing primitives (law 6) atop the #3
rails: mechanical pre-verdicts, honest budgets, per-file isolation,
no destructive git verbs anywhere.

### `fix(problem, gate_cmd=None, condition=None, max_iter=3) -> dict`
Diagnose once (read-only), repair in bounded `do()` rounds with a
mechanical verdict each — no sympathy pass. Returns
`{"status": "ALREADY_GREEN"|"FIXED"|"FAILED", "problem", "diagnosis",
"iterations", "last_gate"}`; a green pre-verdict means zero work, and
the diagnosis travels inside every repair prompt.

### `transform(pattern, instruction, max_files=10) -> list[dict]`
Batch `edit()` over the glob's matches (sorted, first `max_files`):
`{"file", "report"}` on success, `{"file", "error"}` on failure — a
sibling's failure never stops the batch. Rails and `dry_run` apply per
file exactly as in `edit()`. No matches → honest `RangerError`.

### `commit(message=None, allow=None, deny=None) -> str`
Stage and commit the agent's work in cwd; returns the commit sha.
Only ever `git add -A --` + `git commit -m` — never push, reset,
clean, checkout or a force anything. Refuses honestly (`RangerError`)
on a non-repo cwd, a clean tree, or a changeset path hitting the
rails (instance `allow`/`deny` defaults apply; per-call lists replace).
`message=None` uses a marked default ("ranger: agent work (…)").

## 🔜 Next batch (planned, same pattern) (1)

## 🌱 Later (0)

The former planned entries (`fix`, `transform`, `commit`) shipped —
see the repair tier above. No unshipped commands remain.

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

Shipped surface today includes targeted `critique()` and `trace()` alongside bounded `edit()` and free-roaming `do()`,
plus the multi-agent interactions, the
context/memory trio (`context_summarize`/`context_compact`/`context_clear`)
and the run-time knobs (`mode`, `effort`, `stats`, `skills`). The 🌱 tier
that remains (fix/transform/commit) composes on top of it.
