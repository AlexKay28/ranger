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
format) and recall recent history within a character budget. `memory=False`
on the constructor or any single call disables recording and recall.

## ✅ Shipped (7)

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

### `search(goal) -> str`
Read-only codebase search. Returns a `file:line` multiline report. Never edits.

```python
agent.search("where do we parse config files?")
```

### `check(condition) -> bool`
Boolean verdict on repo state. The agent must actually verify (commands, file
reads) and answer with YES/NO as the first word; unparseable answers raise
`RangerError` instead of guessing. The loop-grade primitive for gates.

### `gate(command) -> bool`
Fully mechanical sibling of `check` — no model at all: a shell command whose
exit code decides. `agent.gate("python -m pytest -q")`.

## 🔜 Next batch (planned, same pattern) (5)

### `plan(goal) -> str`
Think without touching. Produces a step-by-step plan, no filesystem changes.

### `edit(file, instruction) -> str`
Targeted fine-grained change to one file only (vs. `do`, which is free-roaming).
Prompt pins the file; returns what changed and why. Post-check: file mtime.

### `review(file_or_diff) -> str`
Code review: bugs, smells, security, missing tests. Read-only.

### `test() -> str`
Run the project's tests, report failures with root-cause guesses, and propose
minimal fixes. Pairs with `fix` for the repair loop.

### `read(file, question) -> str`
Pointed Q&A about one file ("what inputs can crash this?"), vs `summarize`'s
general digest.

## 🌱 Later (4)

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

### `until(goal, max_iter=5, feedback=None) -> str`
The loop primitive: run `plan → do → check` iterations until the gate returns
`True` or `max_iter` is exhausted. This is the end goal of the whole package.

## Non-goals

- No streaming/chat style interface — blocks until the run finishes, returns a
  string. That's what makes it composable.
- No remote-agent management: one agent, one machine, real time.

## The point

With `until` on top of these primitives, the README's manual loop becomes:

```python
agent.until("parser.py: implement the TODO, all tests green")
```
