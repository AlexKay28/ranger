# ranger — architecture

High-level overview of the codebase. For the design *philosophy* see
[PARADIGM.md](PARADIGM.md); for per-method details see [API.md](API.md).

**What ranger is:** an agent-as-a-library. One class (`Ranger`) drives
headless coding-agent harnesses (opencode, codex, claude, pi, openhands — and
any harness you register) from plain Python. You write code, not chat.

## The layers

```
┌────────────────────────────────────────────────────────────┐
│  your python code  (loops, if/else, pipelines)             │  ← control plane
├────────────────────────────────────────────────────────────┤
│  ranger.Ranger            ranger/ (core + mixins)          │
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

Ranger is composed from six single-purpose mixins plus a slim core —
`scripts/split_module.py` is the reproducible record of that split.

| File | Role |
|---|---|
| `ranger/__init__.py` | Slim package core: the `Ranger` class (composed FROM the six mixins below), constructor + model precedence, the package-level mock seams (`ranger.subprocess`, `ranger.os`, `ranger._Spinner`, `ranger._warn_default_model`), and the public re-exports (`debate`, `register_backend`, the exceptions) |
| `ranger/_util.py` | Shared constants, exceptions and small helpers: the spinner, path-match predicates, process-tree kill, message clipping |
| `ranger/_contracts.py` | Frozen prompt/parse contracts (law 2): prompt templates, verdict grammars, mechanical parsers |
| `ranger/_backends.py` | Backend adapters — opencode, codex, pi, openhands, claude — one `build_cmd`/`parse_output` contract per CLI, plus `register_backend()` |
| `ranger/_debate.py` | The module-level composition: the two-agent `debate()` |
| `ranger/_safety.py` | `SafetyMixin`: allow/deny path predicates and pre/post guards around mutating commands (law 4) |
| `ranger/_snapshots.py` | `SnapshotMixin`: git snapshot/rollback/commit rails — hidden-ref snapshots via a temporary index, ref pruning, no destructive verbs |
| `ranger/_loops.py` | `LoopsMixin`: gate evidence and verdicts, `until`/`attempt`/`resolve`/`fix` — bounded, mechanical, never a sympathy pass |
| `ranger/_multi.py` | `MultiMixin`: `verify_claims`, `review`, `challenge`, `second_opinion`, `refine_with` — frozen reply contracts, adversarial by construction |
| `ranger/_commands.py` | `CommandsMixin`: the dialogue/fact commands, async twins, `par_map` — thin frozen prompts over the transport engine |
| `ranger/_engine.py` | `EngineMixin`: the transport engine — run-option resolution, prompt composition, sync+async spawn/kill/complete pipelines, the costs ledger |
| `tests/test_ranger.py` | Contract tests: argv shapes, prompt contracts, error paths, backend flag maps |
| `tests/test_logic.py` | Correctness layer: truth tables — verdict grammar, model precedence, recall budget arithmetic, interaction flow outcomes |
| `tests/test_docs.py` | Doc-drift gates — CI fails if code grows without docs or examples |
| `docs/API.md` | Full reference: every setting, method, error, backend, and the timeout/cancellation contract |
| `docs/PARADIGM.md` | The backbone: agent-is-a-function, seven design laws |
| `docs/commands.md` | Command catalog by maturity tier (shipped / next / needs-bigger-machinery) |
| `docs/growth-log.md` | The growth-loop audit trail |
| `examples/` | Seven runnable folders — `getting-started`, `code-work`, `monitoring`, `agent-reasoning`, `multiagent`, `backends`, `dummy` — quickstart → loops → controls → multi-agent, each main-guarded |

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
     history, while fact commands (`check`, `critique`, `diagnose`, `lint`,
    `read`, `search`, `summarize`, `test`, `review`) and judges run history-
    and session-free — a verdict must
   not be a function of chat. One agent's words reach another only as
   explicitly-labeled *claims to verify*.

## Quality posture

- 513 tests <!-- tests:513 -->, well under the enforced 60-second suite
  budget, including introspection-based docs gates (an undocumented method
  reddens CI; a `<!-- tests:N -->` marker keeps the counted claim honest).
- Every feature is live-verified against real harnesses before
  shipping; the suite itself fully mocks subprocesses, so CI runs on
  any machine with no CLIs and no API keys.
- `main` is the only branch; releases are tagged (current package version:
  `0.9.1`), CI green on every push.

One-liner for a stranger: *ranger turns the headless opencode/codex
CLIs into a Python library — the agent is a function call, and the
loop is yours.*
