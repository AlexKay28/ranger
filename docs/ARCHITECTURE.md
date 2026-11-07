# ranger — architecture

High-level overview of the codebase. For the design *philosophy* see
[PARADIGM.md](PARADIGM.md); for per-method details see [API.md](API.md);
for the full as-is audit with diagrams (component, call-sequence, loop
flowchart, snapshot lifecycle) see
[system-analysis.md](system-analysis.md).

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

## Repository map

Full layout of the repository at `0.9.2` (annotated; the `ranger/*.py`
module roles live in the file map above, the interactive diagrams in
[system-analysis.md](system-analysis.md)):

```
ranger/
├── .github/workflows/          CI (pytest + pcina gates) and tag-driven PyPI publish
├── docs/
│   ├── PARADIGM.md             the backbone: agent-is-a-function, the seven design laws
│   ├── ARCHITECTURE.md         this file — layer tour, file map, quality posture
│   ├── system-analysis.md      as-is audit: component/sequence/flow diagrams, data
│   │                           schemas, module matrix, debt resolution record
│   ├── API.md                  complete per-setting/per-method reference (gated)
│   ├── commands.md             command catalog by maturity tier (gated)
│   ├── ENHANCEMENT-LOOP.md     the self-driving growth loop's ground rules
│   ├── growth-log.md           append-only audit trail of every cycle
│   ├── live-verification.md    how features are verified against real harnesses
│   ├── PUBLISHING.md           the release checklist (maintainers)
│   └── cheatsheet.png          generated by scripts/cheatsheet.py (never hand-drawn)
├── examples/                   seven runnable folders — quickstart → loops →
│   ├── getting-started/        model discovery, first call
│   ├── code-work/              agentic loop, release notes, test repair, reviews
│   ├── monitoring/             cost control, project health, controls
│   ├── agent-reasoning/        micro-task, research+plan, claim verification
│   ├── multiagent/             two-agent interaction patterns
│   ├── backends/               harness adapters, parallel search
│   └── README.md               the organized index (every file is main-guarded)
├── ranger/                     the package — 11 modules:
│   ├── __init__.py             slim core: class assembly, ctor, mock seams, exports
│   ├── _contracts.py           frozen prompts + verdict grammars (law 2)
│   ├── _backends.py            5 CLI adapters + register_backend() (labeled seam)
│   ├── _engine.py              transport engine: validate → compose → spawn → complete
│   ├── _commands.py            23 command wrappers, async twins, par_map, with_config
│   ├── _loops.py               until/attempt/resolve/fix on one bounded skeleton
│   ├── _multi.py               review/challenge/second_opinion/refine_with/verify_claims
│   ├── _debate.py              module-level two-agent debate()
│   ├── _safety.py              allow/deny/dry_run rails + delta post-check
│   ├── _snapshots.py           git snapshot/rollback/commit rails (no destructive verbs)
│   ├── _util.py                constants, exceptions, porcelain -z parser, kill-tree
│   └── py.typed                PEP 561 marker
├── scripts/                    cheatsheet generator, module-split record,
│                               import report, refactor-issue catalog (historical)
├── tests/                      15 files, 515 tests — fully mocked, ~3.5 s
├── pyproject.toml / MANIFEST.in / LICENSE / SKILL.md / README.md
├── pcina.toml                  review-gated quality budgets (measured maxima)
└── AGENTS_NOTE.txt             "reviewed by rangers" provenance note
```

## Quality posture

- 515 tests <!-- tests:515 -->, well under the enforced 60-second suite
  budget, including introspection-based docs gates (an undocumented method
  reddens CI; a `<!-- tests:N -->` marker keeps the counted claim honest).
- Every feature is live-verified against real harnesses before
  shipping; the suite itself fully mocks subprocesses, so CI runs on
  any machine with no CLIs and no API keys.
- `main` is the only branch; releases are tagged (current package version:
  `0.9.2`), CI green on every push.

One-liner for a stranger: *ranger turns the headless opencode/codex
CLIs into a Python library — the agent is a function call, and the
loop is yours.*
