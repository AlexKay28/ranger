# Enhancement sprint plan — rangers 0.7 → 1.0

Backlog decided 2026-10-25, after the 0.6.1 PyPI release. Three sprints,
each with mechanically checkable gates — a sprint closes when its gates
pass, not when its tasks feel done. Every item is reviewed against
[PARADIGM.md](PARADIGM.md): the agent stays a function call, booleans stay
mechanical, memory still never colors facts.

Priority legend: **P0** = sprint blocker, **P1** = should land,
**P2** = stretch / documented decision.

---

## Sprint 0.7 — Reliability (harden the transport)

Theme: *a transient harness failure must never kill a 10-iteration loop.*

| # | Task | Pri | Notes |
|---|------|-----|-------|
| 1 | Exception taxonomy: `RangerTimeout(RangerError)`, `RangerHarnessError(RangerError)`, plain `RangerError` for parse/contract failures | P0 | Callers can then retry timeouts only. No removals — `RangerError` stays the catch-all. |
| 2 | `retries=0` run setting (ctor + per-call): retry a failed run up to N times, only on transport-class failures (`RangerTimeout`, nonzero CLI exit), never on contract failures | P0 | Prompt-contract breaches (`check` unparseable) must NOT retry — the agent answered, badly. |
| 3 | `logging.getLogger("ranger")`: one `debug` per run start/finish with model, command label, duration; `info`-level one-liner summarizing each loop iteration (`until`/`refine_with`). No handlers configured by the library (stdlib rule) | P0 |.spinner stays so TTY UX is unchanged; logging is the composable/pipeable channel. |
| 4 | Document the inherited environment: what the child CLI sees (`**os.environ` + `PWD`), and add per-instance `env=None` override merged over the inherited env | P1 | Child sees parent secrets — say so loudly in API.md, don't silently change it. |
| 5 | `__repr__` showing model, backend, memory, cwd | P1 | One line. Loops print agents; today that's junk. |

**Gates (mechanical):**
- `test_exception_taxonomy`: `issubclass(RangerTimeout, RangerError)` passes; a killed CLI raises the documented class.
- `test_retries_survive_transport_failure`: dummy-backend suite with a scripted failing run — `retries=2` succeeds, `retries=0` raises; contract failure does not retry.
- `test_logging_emits_per_run`: `caplog` captures one record per command run at DEBUG and one per `until` iteration at INFO.
- `test_repr_is_informative`: `repr(agent)` contains model and backend strings.
- API.md documents `retries`, `env`, exception taxonomy (extends the existing doc-sync gates).
- No new public verbs — settings and exceptions only.

---

## Sprint 0.8 — Endurance (state that survives the process)

Theme: *the AGI loop should be resumable, and parallel where safe.*

| # | Task | Pri | Notes |
|---|------|-----|-------|
| 6 | `context_save(path)` / `context_load(path)` — JSON round-trip of `self.context`; `load` replaces, refuses mismatched schema | P0 | Fits the existing context trio; enables overnight/growth-loop resumption. |
| 7 | Parallel two-agent runs: `second_opinion` gains `parallel=True` (default False) via `concurrent.futures`; document that `context` recording order is the only nondeterminism | P1 | Stays sync-blocking at the call boundary — async框架 remains a non-goal. |
| 8 | Backends capability matrix in API.md (opencode vs codex vs custom adapter contract: sessions, file skills, models, stats) | P1 | Prose exists scattered; a table absorbs it. Table is generated from `_Backend` capability flags where possible. |
| 9 | `docs/RECIPES.md` — decision tables: `until` vs manual loop; `check` vs `gate`; `review` vs `second_opinion`; `do` vs future `edit` | P2 | Gates: recipes must reference only shipped API (reuse the README gate). |
| 10 | Decision, shipped either way: async/await — declared **non-goal** in commands.md Non-goals, reusable threads documented instead | P2 | A written decision beats an evergreen question. |

**Gates (mechanical):**
- `test_context_roundtrip`: save → load → identical messages; `context_summarize` works after load; corrupt file raises `RangerError`.
- `test_second_opinion_parallel`: dummy backend, two runs observed overlapping (or at least both executed), result dict shape identical to sequential.
- Capability matrix test: every `supports_*` flag on every registered backend appears in API.md.

---

## Sprint 1.0 — Debt payoff (compatibility break window)

Theme: *one deliberate, documented minor-compat cleanup before the stability promise.*

| # | Task | Pri | Notes |
|---|------|-----|-------|
| 11 | Resolve the `session=` vs `context` ambiguity: document exact behavior when both active (who replays what, who owns recall), or make `session=`+`memory` mutually exclusive with a loud `ValueError` | P0 | The single biggest conceptual ambiguity in the API (review 2026-10-25). |
| 12 | Deprecate `agent=` in favor of `mode=` full-time (DeprecationWarning in 1.0, removal no earlier than 2.0) | P1 | End the four-step resolution chain. |
| 13 | Constructor grouping decision: keep flat iff ≤ 18 settings; otherwise introduce `MemoryConfig`/`RunConfig` groups with back-compat | P1 | Trigger condition is objective, per the interface review. |
| 14 | Safety rails: `dry_run=` counterpart to `auto`, and hard guard rails for the eventual `commit` command (refuse non-repos, no force-push) | P1 | Last piece of the 🌱 tier; `auto=True` by default needs an explicit escape hatch to be defensible at 1.0. |
| 15 | CHANGELOG.md, backfilled from growth-log.md, per-release thereafter | P2 | Versions are immutable on PyPI since 0.6.1 — a changelog is now owed to strangers. |
| 16 | Docs: full doc-sync on 1.0 — cheatsheet redraw, README pass, SKILL.md pass | P2 | The existing gates make this cheap. |

**Gates (mechanical):**
- `test_session_memory_precedence`: scripted dummy runs proving the documented precedence (or the loud `ValueError`).
- `test_agent_kwarg_deprecated`: passing `agent=` warns exactly once, still resolves identically.
- `test_changelog_covers_released_versions`: every git tag `v*` has a CHANGELOG entry.
- Full suite green on 3.9–3.13; PyPI publish workflow exercised end-to-end on a 0.7.0/1.0.0 tag (unblocks: add `PYPI_TOKEN` secret when Actions access returns).

---

## Explicit non-goals (decided now, not later)

- **No streaming/chat interface** — blocks, returns strings (existing law).
- **No async/await API** — threads where parallelism pays, sync everywhere else.
- **No structured `do()` return schema** — prose reports are the contract;
  revisit only if callers are caught parsing reports themselves.
- **No new commands in 0.7** — reliability first; the 🔜 tier (plan/edit/
  critique/test/read) waits for demonstrated demand.

## Out-of-band ops (no code)

- `PYPI_TOKEN` repo secret (pending GitHub Actions access).
- Replace account-wide `.env.local` token with project-scoped on pypi.org — **can be done today**.
- Expect the CI badge red until Actions returns; verify green + badge on the next real Actions run.
