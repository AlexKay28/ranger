# ranger — system analysis (as-is audit)

Audited at `7f9b954` (loop cycle 18) · 11 modules · 3816 LOC / 1613 LLOC ·
154 functions · 17 classes · max cc 14 · avg cc 4.3 · docstring coverage 80%.

Scope: `ranger` is an **agent-as-a-library** — one Python class, `Ranger`,
that drives headless coding-agent harness CLIs (opencode, codex, pi,
openhands, claude) via subprocess. There is no server, no queue, no
runtime: Python owns every loop. This audit documents the as-is
architecture, the data schemas, the responsibility matrix, and the
structural debt that can be addressed **without altering any public API,
prompt byte, or observable behavior** (repo law: zero functional drift).

---

## 1. High-level architecture

```
                   ┌──────────────────────────────────────────┐
   user code       │  Ranger(SafetyMixin, SnapshotMixin,       │
   agent.ask(...)  │          LoopsMixin, MultiMixin,          │
                   │          CommandsMixin, EngineMixin)      │
                   └───────────────┬──────────────────────────┘
                                   │ one composed method to call
        ┌──────────────┬───────────┼─────────────┬─────────────┐
        ▼              ▼           ▼             ▼             ▼
  SafetyMixin   SnapshotMixin  LoopsMixin   MultiMixin   CommandsMixin
  allow/deny     git snapshot/ until/attempt/ verify/review/ 23 public
  dry_run rails  rollback/     resolve/fix  challenge/      command
  (path predicates) commit     bounded loops refine_with/debate wrappers
        └──────────────┴───────────┴─────────────┴─────────────┘
                                   │  all funnel into the ONE seam:
                                   ▼
                          EngineMixin._run / _run_async
                    (_resolve_run_options → _compose_prompt →
                     _prepare_run → transport → _complete_run)
                                   │ backend adapter (registry)
                                   ▼
                     _backends.py: _OpenCodeBackend, _CodexBackend,
                     _PiBackend, _OpenHandsBackend, _ClaudeBackend
                     (build_cmd / parse_output / list_models)
                                   │ the ONLY I/O in the library
                                   ▼
                     subprocess.Popen (_popen_run, sync transport:
                     contained kill-tree on timeout/interrupt) /
                     asyncio.create_subprocess_exec
                     (the seams every test mocks: `ranger.subprocess`,
                      `ranger._engine._Popen`)
```

### Entry points
- `ranger.Ranger(...)` — the single public class; everything else is
  package-internal. `ranger.debate(a, b, topic)` and
  `ranger.register_backend(name, cls)` are the only other top-level names.
- No CLI, no REST routes, no background workers by design.

### End-to-end lifecycle of one call (e.g. `agent.do(goal)`)
1. **Command wrapper** (`_commands.py`) freezes the prompt contract
   (`_contracts._do_prompt`) and labels the run (`"do"`).
2. **Option resolution** (`EngineMixin._resolve_run_options`, cc 13)
   merges constructor settings + per-call overrides into the run dict `o`,
   validates everything (raises `TypeError`/`RangerError` at the boundary).
3. **Skill collection** (`_collect_skills`) splits file grants from prose
   grants; prose grants are inlined by `_grants_block`, files attached via
   backend capability (`native_file_skills`).
4. **Prompt composition** (`_compose_prompt` = `_grants_block` +
   `_recall_block` + request + `_effort_directive`) — byte-identical
   assembly; `quote()` re-measures the same blocks without spawning.
5. **Transport** (`_run`/`_run_async` → `_spawn_sync`/`_spawn_async`)
   builds the argv via the backend adapter, spawns the harness CLI,
   handles interrupt/retry/timeout, prints progress (+`_Spinner` on log
   level <= INFO). `KeyboardInterrupt` kills the CLI subtree and re-raises.
6. **Completion** (`_complete_run`) parses output through the adapter
   (`parse_output` → `answer, info`), records `context` and `costs`
   (`_record_costs`), post-checks (e.g. `write()` requires the file),
   returns the answer.
7. **Loops** (`until`, `resolve`, `fix`, `refine_with`, `challenge`) are
   plain Python iteration over that seam, terminated by mechanical gates
   or frozen grammars — never by an agent's self-report.

## 2. Data schemas (in-process contracts — there is no database)

| Schema | Shape | Where produced / consumed |
|---|---|---|
| Run options `o` (dict) | 20-key frozen set `_RUN_KEYS`: model, timeout, auto, session, agent, mode, title, thinking, pretty, memory, skills, effort, stats, backend, memory_budget, retries, env, allow, deny, dry_run | `_resolve_run_options`; every transport/adapter reads it |
| Composed prompt string | grants block + recall block + request + effort directive | `_compose_prompt`; measured verbatim by `quote()` |
| Context history | `list[{"role": str, "content": str}]` | recorded by memory-carrying commands, recalled bounded by `memory_budget` (chars) |
| Costs ledger | `{"calls", "chars_in", "chars_out", "tokens_in", "tokens_out", "wall_s"}` (tokens `None` until backend reports) | `_record_costs`; `agent.costs` / `costs_reset()` |
| Telemetry `info` | `{"model_s", "parts", "chars", "session", ...backend extras}` | adapter `parse_output`; surfaces via `agent.last` |
| until/attempt/resolve result | `{"achieved", "iterations", "last_gate", "report", ...}` (+ `"rollback"` when chained) | LoopsMixin |
| verify_claims / review / challenge / refine_with results | PASS/FAIL/UNCERTAIN table; VERDICT/FINDINGS/CHANGES; attack/defense transcript; approved+reviews | MultiMixin (frozen grammars in `_contracts.py`) |
| Snapshot log | `list[{"tag", "sha", "tree", "time"}]` on the instance; git index files under `.git/ranger-index-*` | `_snapshots.py` (git plumbing only: HEAD/branches untouched) |
| Backend registry | `dict[name -> adapter class]` over `_Backend` (name, install_hint, native_file_skills, build_cmd, parse_output, list_models) | `_backends.py` / `ranger.register_backend` |

## 3. Communication boundaries
- **Ranger → harness CLIs:** argv (build_cmd) / stdout parsing
  (parse_output) per backend; the ONLY network/IO surface. JSONL for
  opencode, JSON object for claude, plain text for pi/openhands, JSONL
  event stream for codex.
- **Ranger → git:** `_snapshots.py` + `commit()` shell out to git
  porcelain/plumbing (`read-tree --reset -u`, `status --porcelain`,
  `clean -fd -- <paths>`). Safety rails (`allow/deny` globs) are
  pure-Python path predicates — no shell string magic.
- **Mixins → engine:** mixin methods call `self._run(...)`; state lives
  on the instance (`self.context`, `self._costs`, `self.snapshot_log`).
  Mixins are stateless-by-convention: all mutation flows through
  EngineMixin helpers.
- **Tests → library:** the mock seams — `ranger._engine._Popen`
  (sync transport, contained kill-tree), `ranger.subprocess.run`
  (git plumbing, models listing), `ranger.subprocess.Popen` (gate)
  and `asyncio.create_subprocess_exec` (async twin). 425 fully mocked
  tests pin prompts and outputs byte-for-byte; suite budget 60s.

## 4. Module responsibility matrix

| Module | Lines | Actual responsibility | Verdict |
|---|---:|---|---|
| `__init__.py` | 259 | class assembly (7 mixins), ctor option validation, stale-model warning, `__repr__` | clean; ctor validation is at the right boundary |
| `_engine.py` | 589 | run pipeline: options → skills → compose → spawn (sync+async) → complete; costs ledger; context recall | heaviest module: transport + accounting + UI (progress marks) live together |
| `_commands.py` | 648 | 23 public command wrappers + `quote()` + `gate()` + `models()`/`with_config()` | sizeable but homogeneous: thin wrappers over prompts frozen in `_contracts.py`; `extract()`/`par_map` carry parsing + validation (~cc 14) |
| `_backends.py` | 526 | 5 CLI adapters over the `_Backend` contract + registry | clean seam; adapters differ only in argv/parse; codex sandbox argv is the densest spot |
| `_contracts.py` | 200 | frozen prompt texts, grammar validators, effort/purity tables | the de-facto spec; excellent isolation |
| `_loops.py` | 443 | until/attempt/resolve/fix + `_gate_sequence` | until(11) and resolve(11) share sequence logic with slight variants |
| `_multi.py` | 453 | verify_claims/review/challenge/second_opinion/refine_with | 5 grammar-driven interactions; `refine_with` cc 12 |
| `_safety.py` | 105 | allow/deny rail checks + rails-error wording | clean |
| `_snapshots.py` | 247 | snapshot/rollback/commit over git plumbing | clean; tag validation honest |
| `_debate.py` | 118 | debate() + prompt builders + judge digest | clean |
| `_util.py` | 228 | exception taxonomy, named constants, clips, spinner, kill, patterns | grab-bag by definition; constants section is the good part |

No circular imports (mixins import only `_util`/`_contracts`/`_backends`);
adapter registry is the only inversion point, by design.

## 5. Bottlenecks & smells remaining (all from the pinned-prevalence scan, weighted by pcina)

God-object tension: **`Ranger` is intentionally one class** (paradigm:
"the agent is a function call"). The mixin split already separates the
seven axes of responsibility; further splitting would be fighting the
public API on purpose — rejected as functional drift (law 1).

Honest internal debt, ranked by weighted penalty (scan at 9.05):

1. **`par_map` cc 14 + 7 raise-guards** (`_commands.py:562`, footprint
   10.0 penalty pts). Validation at the boundary is deliberate, but the
   per-call *assembly* (build the inner run, thread the slot) can be
   extracted without moving a single raise (cycle 17 pattern).
2. **`_resolve_run_options` cc 13** (`_engine.py:133`). Same shape:
   option merge + validation; the precedence merge (callBeat ctor beat
   env) can become a pure `_merge_opts` helper; the raises stay put.
3. **`until`/`resolve` cc 11 twins** (`_loops.py:173/320`): the shared
   gate-sequence/iteration skeleton can be one internal `_bounded_runs`
   iterator; until/resolve keep only their own stop conditions.
4. **`refine_with` cc 12** (`_multi.py:401`): the do→review→revise round
   body is extractable as a prompt-independent pure partie.
5. **Backend adapter docstrings + OpenCode `build_cmd` cc 11**: classes
   documenting their flags/parse shape are pure documentation (0 risk).
6. **`_Spinner` dead-code flag**: false positive — it is resolved through
   the package and kept as the mock seam; do NOT delete (documented).
7. **Nesting infos (9× depth 3)**: mechanical guard inversions, byte-
   identical outputs, low risk.
8. **43 pinned warns** (`pcina.toml` budgets at measured maxima): by
   reviewed baseline decision (cycle 12) — aggravation fails, reduction is
   welcome, the numbers are not themselves debt to chase.

None of 1–7 touches a public signature, a prompt byte, or an error
message; all are pinned by the 358-test suite and the doc/api gates.

## 6. Proposed refactoring issues (Phase 3 — see `scripts/refactor-issues.sh`)

Each issue is atomic, behavior-frozen, and independently verifiable:
suite stays 358 green, `pcina check` exit 0, scan does not regress,
byte-identical output where applicable.

1. `Refactor: extract par_map run-assembly from boundary validation`
2. `Refactor: split _resolve_run_options precedence merge from raises`
3. `Refactor: unify bounded-loop skeleton shared by until/resolve`
4. `Refactor: extract refine_with round body`
5. `Docs: document backend adapter classes (parse/build contracts)`
6. `Refactor: invert depth-3 guards to guard clauses (9 sites)`

Issue bodies (problem / proposed solution / acceptance criteria) are
kept in `scripts/refactor-issues.sh` as ready-to-run `gh issue create`
commands, because the current fine-grained PAT lacks Issues-write scope
(verified twice: 403 Resource not accessible on REST + GraphQL). That
is the one human-only step in this plan.
