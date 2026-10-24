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
| Produce one document | `write(task, path=...)` | Parsing prose for a filename |
| Read-only codebase findings | `search(goal)` / `summarize(file)` | `do()` |
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
- `ask`, `do`, and `write` record and recall bounded `agent.context`. Treat it
  as conversational color, never as a fact store.
- `check`, `search`, `summarize`, `review`, challenge judgments, and debate
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

- Use `Ranger(backend="opencode")` (default) or `Ranger(backend="codex")`.
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

## Choose an example before inventing a workflow

See [examples/README.md](examples/README.md) for runnable recipes:

- `examples/code-work/fix_failing_tests.py` — bounded repair with a real test
  command as the gate.
- `examples/code-work/simple_code_review.py` — one file, one strict verdict.
- `examples/monitoring/project_health.py` — read-only health snapshot.
- `examples/multiagent/multi_agent.py` — all collaboration patterns.
- `examples/dummy/mechanical_gates.py` — no model or login required.
