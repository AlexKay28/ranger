# ranger — architecture

High-level overview of the codebase. For the design *philosophy* see
[PARADIGM.md](PARADIGM.md); for per-method details see [API.md](API.md).

**What ranger is:** an agent-as-a-library. One class (`Ranger`) drives
headless coding-agent harnesses (opencode, codex — and any harness you
register) from plain Python. You write code, not chat.

## The layers

```
┌────────────────────────────────────────────────────────────┐
│  your python code  (loops, if/else, pipelines)             │  ← control plane
├────────────────────────────────────────────────────────────┤
│  ranger.Ranger            ranger/__init__.py               │
│  ┌──────────────┐ ┌───────────┐ ┌───────────────────────┐   │
│  │ commands      │ │ memory   │ │ interactions          │   │
│  │ ask/do/write/ │ │ recall+ │ │ review/challenge/      │   │
│  │ search/check/ │ │ record, │ │ second_opinion/       │   │
│  │ gate/until    │ │ purity  │ │ refine_with, debate   │   │
│  └──────┬───────┘ └────┬──────┘ └──────────┬────────────┘   │
│         └───────┬──────┴───────────────────┘                │
│           _run(): frozen prompts, recall budgets, grants,   │
│           verdict grammars, stats, live UI — ONE seam        │
│                 ┌───────────────────────┐                   │
│                 │ backend adapters      │ register_backend │  ← data plane
│                 │ _OpenCodeBackend       │ _CodexBackend    │
│                 └───────────┬───────────┘                   │
├─────────────────────────────┼──────────────────────────────┤
│  `opencode run` / `codex exec` subprocess, one per call     │
└────────────────────────────────────────────────────────────┘
```

## File map

| File | Role |
|---|---|
| `ranger/__init__.py` | The whole library: harness adapters, the `Ranger` class, `debate()`, the live progress UI, helpers |
| `tests/test_ranger.py` | Contract tests: argv shapes, prompt contracts, error paths, backend flag maps |
| `tests/test_logic.py` | Correctness layer: truth tables — verdict grammar, model precedence, recall budget arithmetic, interaction flow outcomes |
| `tests/test_docs.py` | Doc-drift gates — CI fails if code grows without docs or examples |
| `docs/API.md` | Full reference: every setting, method, error, backend, and the timeout/cancellation contract |
| `docs/PARADIGM.md` | The backbone: agent-is-a-function, seven design laws |
| `docs/commands.md` | Command catalog by maturity tier (shipped / next / needs-bigger-machinery) |
| `docs/growth-log.md` | The growth-loop audit trail |
| `examples/` | Seven runnable apps, quickstart → discovery → loops → controls → backends → multi_agent → growth_loop |

## The three architectural decisions everything follows

1. **Python owns the loop.** Plan → act → check maps to expression →
   statement → condition; no DSL, no hidden runtime. Every verdict is
   grammar (`YES/NO`, `VERDICT: APPROVE`, `RULING: SUSTAINED`),
   mechanically parsed, raise-on-ambiguity — never trusted prose.
2. **One seam.** Every command converges on `_run()` → a backend
   adapter → one subprocess. That is why codex was added as a ~90-line
   translator with zero control-flow change, and why
   `ranger.register_backend()` makes any harness one small class:
   implement `build_cmd()` (options → CLI argv) and `parse_output()`
   (stream → answer + optional telemetry).
3. **State is explicit and pure where it matters.** `agent.context` is
   a visible message list; dialogue commands recall bounded recent
   history, while fact commands (`check`, `search`, `summarize`,
   `review`) and judges run history- and session-free — a verdict must
   not be a function of chat. One agent's words reach another only as
   explicitly-labeled *claims to verify*.

## Quality posture

- 118 tests, ~0.6s, including an *enforced* 60-second suite budget and
  introspection-based docs gates (an undocumented method reddens CI).
- Every feature is live-verified against real harnesses before
  shipping; the suite itself fully mocks subprocesses, so CI runs on
  any machine with no CLIs and no API keys.
- `main` is the only branch; releases are tagged (current package version:
  `0.7.0`), CI green on every push.

One-liner for a stranger: *ranger turns the headless opencode/codex
CLIs into a Python library — the agent is a function call, and the
loop is yours.*
