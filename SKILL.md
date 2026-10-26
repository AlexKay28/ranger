---
name: ranger
description: Use the ranger Python library to drive headless coding agents from ordinary Python. Load BEFORE writing a Ranger loop, agent-backed repair or review workflow, multi-agent composition, custom backend, or tests around ranger. Triggers - ranger, rangers, Ranger(), agent-as-a-library, headless coding agent in Python, ask/do/check/until/refine_with, coding-agent loop, агент как библиотека, цикл агента на Python, ранжер. Do NOT use for a hosted agent runtime, background task queue, or streaming chat server - ranger intentionally has none; Python owns the loop.
---

# ranger — agent-as-a-library

`rangers` is the PyPI distribution; the import is `ranger`:

```python
# shell: pip install rangers
import ranger

agent = ranger.Ranger(cwd="/path/to/project", timeout=180)
answer = agent.ask("Find the smallest safe fix for the failing parser test.")
```

Every live Ranger call starts one headless harness CLI process and blocks until
it returns. Python, not an agent runtime, owns the control flow.

## Non-negotiable rules

| Need | Use | Do not substitute |
|---|---|---|
| Open-ended answer or one small plan | `ask(prompt)` | A custom chat loop |
| Make a filesystem change | `do(goal)` | A claim that a change happened |
| Change one existing file only | `edit(file, instruction)` | `do()` free rein |
| Produce one document | `write(task, path=...)` | Parsing prose for a filename |
| Read-only codebase findings | `search(goal)` / `summarize(file)` / `read(file, question)` / `test()` / `lint()` / `diagnose(error)` / `critique(file_or_diff)` | `do()` |
| Agent-verified fact | `check(condition)` | Truthy prose; it must parse YES/NO |
| Deterministic acceptance | `gate(shell_command)` | An agent's opinion |
| Bounded repair loop | `until(..., gate_cmd=..., max_iter=N)` | An unbounded `while` loop |
| Independent review | `critic.review(subject, author=claims)` | Trusting the author report |

**Use a mechanical gate whenever one exists.** For a repair, the shell test
command decides success:

```python
result = agent.until(
    "Make the parser tests pass; reproduce first and make the smallest fix.",
    gate_cmd="python -m pytest -q tests/test_parser.py",
    max_iter=2,
)
if not result["achieved"]:
    raise RuntimeError(result["report"])
```

`until` never invents success after its budget runs out. `gate()` returns only
an exit-code boolean and does not call a model.

## Costs, cancellation, and state

- Set an explicit `timeout=` for real work and a small `max_iter`/`rounds`
  budget for every loop. A loop costs one or more full CLI calls per iteration.
- Ctrl+C / notebook interrupt raises `KeyboardInterrupt`, stops the CLI client,
  and retires the progress spinner. Long loops put honest partial state in the
  interrupt message; nothing is claimed complete.
- `ask`, `do`, `edit`, and `write` record and recall bounded `agent.context`. Treat it
  as conversational color, never as a fact store.
- `check`, `critique`, `diagnose`, `lint`, `read`, `search`, `summarize`, `test`, `review`, challenge judgments, and debate
  judges are memory- and session-free by contract. Do not try to override that
  purity with `session=`.
- A model answer is not a success signal. `check()` rejects ambiguous,
  contradictory, or uncertain replies with `RangerError`.

## Multi-agent work

Interactions are normal Python compositions, not a scheduler or swarm.
Pass another agent's report as **unverified claims** and let the receiver verify
the repository itself:

```python
builder = ranger.Ranger(cwd=".", timeout=180)
critic = ranger.Ranger(cwd=".", timeout=180)

outcome = builder.refine_with(
    critic,
    "Add a regression test for empty parser input and make it pass.",
    max_iter=2,
)
if not outcome["approved"]:
    print(outcome["reviews"][-1]["changes"])
```

Use the smallest fitting pattern:

- `second_opinion(other, prompt)` — compare two answers; disagreement is the
  signal, not a vote.
- `review(subject, author=...)` — strict `VERDICT`, `FINDINGS`, `CHANGES`.
- `challenge(other, claim=..., rounds=1)` — adversarial evidence check.
- `refine_with(critic, goal, max_iter=2)` — do → review → revise.
- `ranger.debate(a, b, topic, judge=...)` — surface factual disagreements;
  the judge digests evidence and never crowns a winner.

Do not parse model prose yourself. The interaction methods validate their
frozen grammars and raise `RangerError` on malformed or conflicting replies.

## Backends and models

- Use `Ranger(backend="opencode")` (default), `Ranger(backend="codex")`,
  `Ranger(backend="pi")`, or `Ranger(backend="openhands")`.
  The public API stays the same; CLI flags and output parsing do not.
- Use OpenRouter-style public model IDs in repository files. Do **not** add
  internal provider/model names to code, docs, examples, tests, or commits.
- For a new harness, register a small adapter with
  `ranger.register_backend(name, adapter_cls)`; do not fork command logic.
- Resolve a model only when needed: explicit per-call model beats constructor,
  then `RANGER_MODEL`, then the effective backend's default.

## Contributing to this repository

- Read [docs/PARADIGM.md](docs/PARADIGM.md) before changing public behavior.
  The core laws are grammar over vibes, explicit Python state, and a
  replaceable harness data plane.
- Keep normal tests fully mocked. Agent calls use the
  `ranger.subprocess.run` seam; `gate()` uses `ranger.subprocess.Popen`.
  Do not put live opencode/codex calls in the test suite.
- Add truth-table tests for parsers, verdicts, option precedence, and loop
  outcomes. The suite has a strict one-minute budget.
- Update `docs/API.md`, README, examples, and docs gates whenever public API
  changes. Examples must be main-guarded and import-safe.
- Run `python -m pytest -q`; for releases also run `python -m build` and
  `python -m twine check --strict dist/*`. See [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Tips — hard-won, from real agent-driven projects

These come from ranger resolving its own sprint (issue #1, three runs,
two false-greens caught). Follow them when a ranger loop does real work.

- **The caller owns the verdict.** An agent's `do()` report is narration:
  it can be true, stale, or empty — and string-identical in all three cases.
  Never branch on the report; branch on a mechanical gate.
- **Compound your gates.** `gate_cmd="python -m pytest -q"` is vacuously
  green if no failing test demands the feature. Demand the feature:
  `pytest -q && pytest -q tests/test_X.py -k feature && python -c "assert …"`
  (`pytest -k` exits 5 when nothing matches — the gate stays red until the
  feature's own tests exist).
- **Read `last_gate`, not `report`, on failure.** `until()`'s result carries
  `last_gate: {"kind", "ok", "output"}` — the gate's clipped output is the
  diagnosis; the agent's prose about its own work is not.
- **One task, one context.** `context` recall turns consecutive tasks into
  one blurry dialogue: task N+1's planning answer can be piped straight from
  task N's completed report ("already done"), wasting iterations on
  self-doubt. Isolate: `agent.ask(..., memory=False)`, a fresh `Ranger()`,
  or (0.8) snapshot/restore per task.
- **Verify even PASSes.** After a loop claims `achieved`, re-check the
  feature mechanically yourself. Trust, then verify — in that order only
  when the stampede of a deadline demands it; ideally verify, then trust.
- **Budget `retries` for blips, not config.** Auth/token failures are
  transport-class too: `retries` will re-attempt a permanently failing
  model and burn tokens. Fix expired credentials; don't retry them.
- **Don't bake model ids into committed scripts.** They expire, leak
  internals, and rot — pass the id per run (argv/env). (Tested by this
  very repo's hygiene gate.)

## Execution-bug feedback for maintainers

If a user asks you to use ranger and you encounter a reproducible library or
harness-execution bug, help the maintainers learn from it: create an issue at
[`AlexKay28/ranger`](https://github.com/AlexKay28/ranger/issues) when GitHub
authentication and issue-creation permission are available. If they are not,
give the user the complete ready-to-paste issue instead. Do this after a
minimal reproduction attempt — not for a malformed prompt, a missing CLI, an
expired model quota, or an expected `RangerError` caused by invalid input.

**Never include secrets.** Redact API tokens, credentials, private prompts,
absolute private paths, and proprietary source. Link to public output only.

Use this issue format:

````markdown
## ranger execution bug

**ranger version:** `ranger.__version__`
**Python / OS:** `python --version`; operating system
**Backend / model:** `opencode|codex`; public model ID or `redacted`
**Command or minimal code:**
```python
# smallest self-contained reproduction
```
**Expected behavior:** what should have happened
**Actual behavior:** exact exception, exit code, or unexpected result
**Reproduction:** always / intermittent; smallest known steps
**Relevant non-secret context:** timeout, session/memory setting, and whether
the problem remains with `memory=False` and a fresh session
````

Title issues as: `bug: <short observable failure>`. Before filing, search
existing open issues for the same error and add reproduction details there
instead of creating a duplicate. The report is feedback, not a substitute for
the user's immediate workaround: state the workaround or honest blocker too.

## Choose an example before inventing a workflow

See [examples/README.md](examples/README.md) for runnable recipes:

- `examples/code-work/fix_failing_tests.py` — bounded repair with a real test
  command as the gate.
- `examples/code-work/simple_code_review.py` — one file, one strict verdict.
- `examples/monitoring/project_health.py` — read-only health snapshot.
- `examples/multiagent/multi_agent.py` — all collaboration patterns.
- `examples/dummy/mechanical_gates.py` — no model or login required.
