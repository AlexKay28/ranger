# ranger growth log

Append-only cycle log of the agentic project-growth loop (3-cycle pilot, focus:
documentation + tests). This is the loop's only cross-cycle memory.

## Cycle 1 — examples folder (2026-10-24)

- **Goal:** examples/ with >=3 runnable applications + catalog README.
- **Evidence:** real user report ("add folder with application examples") —
  highest-priority class; 4 persona hypotheses below it stayed in backlog.
- **Contract:** A1 py_compile all examples; A2 import side-effect-free;
  A3 shipped-API-only usage; A4 docs consistency. Non-goals: no new library
  methods, no CI, no test suite.
- **Outcome:** `pass_merged` @ 4f9d97d.
- **Verification:** A1-A4 rerun mechanically, all PASS. Independent reviewer:
  ACCEPTED (4 minor findings, none blocking).
- **Amendment (user-authorized, applied pre-merge):** scrubbed internal
  provider IDs from all public code/docs; replaced with public openrouter
  IDs. `DEFAULT_MODEL` changed accordingly. On the maintainer's own machine,
  `Ranger()` now needs explicit `model=`.
- **Reviewer findings carried to backlog:** (1) agentic_loop.py `cwd="."`
  framing vs docstring; (2) examples/README "pip install -e .." wording;
  (3) quickstart `do()` mutates target dir (warned).
- **Backlog (unselected):** test suite (cycle 2), CI workflow (cycle 3),
  docs compile-check as permanent regression gate, fix reviewer cosmetic
  findings.

## Cycle 2 — unit test suite (2026-10-24)

- **Goal:** tests/test_ranger.py pinning shipped behavior; fully mocked
  subprocess; CI-safe anywhere.
- **Evidence:** observed (repo shipped zero tests for a public API) + persona
  hypotheses (contributor trust, evaluator trust); test infrastructure also
  unblocks cycle 3.
- **Contract:** A1 pytest exit 0 >=12 tests; A2 coverage list (flags, PWD env,
  per-call overrides, error paths, models(), with_config, write() existence
  gate, prompt contents); A3 examples compile gate; A4 `.[dev]` extras work.
  Non-goals: no library changes, no CI, no live agent runs.
- **Outcome:** `pass_merged` @ 2e9bea2.
- **Verification:** 15/15 pass; suite also passes with `PATH=/nonexistent`
  (proof: zero real subprocess spawns). `git diff ranger/` empty.
- **Independent review:** first round **REJECTED** — the new hygiene gate was
  false-green (scanned root *.md only, missed docs/*.md which itself carried
  an internal id). Fixed: gate now rglobs all .py+.md, self-excludes only the
  test file; growth log reworded; loose assertion tightened. Second round:
  accepted conditions met.
- **Backlog additions (reviewer advisory):** gate does not scan non-py/md
  file types; docs compile-check could become a permanent pytest gate.

## Cycle 3 — CI workflow + badge (2026-10-24)

- **Goal:** GitHub Actions running the unit suite on push/PR (py 3.9–3.13)
  plus README badge.
- **Evidence:** observed (tests existed, no runner); persona rotation (E9) —
  fresh archetypes: outside cold-clone contributor, release manager.
- **Contract:** A1 YAML valid; A2 exact locally-green commands; A3 no
  opencode CLI / no network beyond pip; A4 badge URL correct. Non-goals:
  no publish/deploy jobs.
- **Outcome:** `pass_merged` @ 107985b (log bookkeeping @ 992e7af).
- **Verification:** A1–A4 mechanically re-verified (pyyaml structural parse,
  matrix string types, badge URL). Local suite 15/15 unchanged.
- **Independent review:** ACCEPTED (advisory: cycle-2 log record was
  uncommitted at review time — committed separately).
- **Delivery stages (distinct, honest):** verified_local ✅, integrated_local
  ✅ (commit on main), delivered_main ✅ CONFIRMED — pushed by maintainer
  (84fa19e..15c9070); Actions run 40116968801 green in 17s on the full
  3.9–3.13 matrix (2026-10-24). Badge claim "CI passing" is now real.

## 3-cycle pilot summary

- 3/3 goals merged, one review rejection overcame (cycle 2, false-green
  hygiene gate) — the reviewer earned its keep exactly once, which is the
  cheapest possible proof the loop is not self-graded theater.
- Backlog remaining (candidates for the next run, not auto-worked):
  permanent docs compile-check pytest gate; commands.md 🔜 batch
  (plan/edit/review/test/read); non-py/md hygiene surface; reviewer
  cosmetic findings from cycle 1; PyPI publish prep.
- Iteration ceiling was treated as a maximum, not a quota; loop stops here.

## Cycle 4 — first PyPI release + automated publishing (2026-10-25)

- **What:** `rangers 0.6.1` (import `ranger`) published to PyPI — the
  package's first public release: <https://pypi.org/project/rangers/>
- **How:** full docs/PUBLISHING.md checklist from a clean main checkout —
  134 tests green, `python -m build`, `twine check --strict`, wheel
  smoke-tested in a fresh venv, uploaded, verified by installing from
  pypi.org/simple in a second fresh venv. Tag `v0.6.1` pushed.
- **Automation:** `.github/workflows/publish.yml` added — any `v*` tag now
  runs the test matrix, rebuilds, validates, asserts tag==pyproject version,
  and uploads to PyPI via the `PYPI_TOKEN` secret (`--skip-existing`).
  ci.yml's wheel smoke-test no longer hardcodes the version.
- **Hygiene:** `.env.local` (release token storage) excluded via
  `.gitignore`; token never committed or printed.
- **Docs:** commands.md ✅ tier re-synced with the real 17-method surface
  (multi-agent five moved into shipped; planned code-review command renamed
  `critique` to avoid collision with shipped `review`); README gained PyPI
  version+downloads badges; new doc gates in tests/test_docs.py lock all of
  it (catalog↔code set equality, README code blocks, install-command↔dist
  name, badge presence).
- **Verification:** full local suite green (134 + 4 new gates) before push.

## Cycle 5 — sprint 0.7 resolved by ranger itself + four backends (2026-10-25)

- **What:** `rangers 0.7.0` — reliability core (exception taxonomy,
  transport-only retries, stdlib logging, env overlay, __repr__),
  the vacuous-green pre-check and gate-evidence (`last_gate`) in
  `until()`, SKILL.md tips, and two new harness backends: `pi`
  and `openhands` (issues #1, #2). Suite: 196 mocked tests, green
  in under 2s.
- **How:** issues #1/#2 resolved by an agent-driven resolver script
  (untracked by design) under the hardened protocol — compound
  per-task gates, independent post-loop verification, honest
  tri-state reporting. Two false-greens were caught across three
  runs; both lessons became library features. One post-merge bug
  (per-call env replacing instance env) was caught by human
  spot-check after agent-verified PASS.
- **Release:** version bumped to 0.7.0, built, twine-checked,
  smoke-tested, uploaded and verified from pypi.org/simple.


## Cycle 6 — dogfooding recursion and the honesty triad completed (2026-10-25)

- **What:** code → examples → dogfood → library features. The session's
  arc: (1) three temporal agent-reasoning examples; (2) the same patterns
  as shipped commands — `plan()`, `attempt()`, `verify_claims()` —
  implemented BY a ranger agent driven by a temporal resolver script;
  (3) the run exposed a **false-red** (the gate grepped prose instead of
  contract — the agent had done the work, the FAIL was the caller's);
  (4) both lessons went back into the library: `resolve()` (the
  hand-rolled resolver protocol as one call) and gate sequences
  (`gate_cmd` lists, short-circuit + per-part `last_gate` breakdown so a
  red names the exact sub-check that failed).
- **Learned:** the honesty triad is complete — false-greens (compound
  gates + `already_green`), false-reds (parts evidence), caller-side
  check bugs (gates must assert contracts, not prose).
- **API:** core commands 8 → 12 (`plan`, `attempt`, `verify_claims`,
  `resolve`; `gate_cmd` widened to `str | list` in the loop family). The
  four copy-pasted verdict blocks collapsed into `_gate_evidence` +
  `_verdict` — net code simpler, public seams untouched, all prior
  gate tests pass unchanged.
- **Verification:** 219 tests green (~1.6s); live contract checks on the
  new methods; fresh-venv wheel verification before upload.
- **Release:** `rangers 0.7.1` on PyPI (maintainer-picked patch number),
  verified from pypi.org/simple. Commits: `13274e6`, `07e1532`.


## Cycle 7 — claude backend: the fifth harness (2026-10-30)

- **What:** issue #10 — a `claude` backend adapter, so
  `Ranger(backend="claude")` drives the Claude Code CLI headlessly.
  Translation only (paradigm law 7): `claude -p "<prompt>"` with
  `--model`, `--permission-mode acceptEdits` + `--allowedTools
  "Read,Edit,Bash"` for `auto=True`, `--permission-prompts none`
  (unattended: anything that would prompt is denied; CLI >= 2.1.259,
  safe headless), `--resume <id>` for sessions and always
  `--output-format json`, parsed into answer + telemetry
  (`result`, `session_id`, `total_cost_usd`, usage → `agent.last`
  gains `cost_usd`). No file-attachment flag exists, so skills inline
  into the prompt exactly as the codex backend already does;
  `--bare` is deliberately never emitted (it breaks subscription
  auth). Unsupported options (`agent`, `mode`, `title`, `thinking`,
  non-default `effort`) raise loudly via the shared `unavailable()`
  contract.
- **How:** research was frozen up front from the official headless
  docs (2026-10-30) — the adapter contains only verified flags, and
  the test suite pins the argv shapes and parser behavior so CLI
  drift is caught mocked, not in a user's terminal.
- **Verification:** 245 mocked tests green in under 2s, including a
  seam-level end-to-end test (`ranger.subprocess.run` mocked) proving
  zero control-flow change; docs gates updated (API.md capability
  map, SKILL.md, README, ARCHITECTURE.md, examples/README.md,
  `<!-- tests:245 -->` marker).
- **Issue #9 (same cycle):** async twins — `ask_async`, `do_async`,
  `write_async`, `edit_async`, `search_async`, `check_async` — plus
  `par_map`. The prep layer moved out of `_run()` into a shared
  `_prepare_run()` seam, so sync and async argv are byte-identical BY
  CONSTRUCTION (pinned by a literal argv-equality test); frozen prompts
  left the method bodies for single-source builders (`_do_prompt` etc.)
  so a twin can never drift. Cancellation kills the CLI subtree
  (asyncio analogue of KeyboardInterrupt semantics); `par_map` validates
  every spec before a single spawn, bounds concurrency with a semaphore
  and returns per-slot answers or exception instances — nothing
  swallowed, no scheduler object (law 6). Suite: 272 mocked tests
  green in ~2.5s; new file `tests/test_async.py` (27 tests), example
  `examples/backends/parallel_search.py`, API.md/commands.md/SKILL.md/
  README synced.
- **Issue #8 (same cycle):** `extract(request, keys, many=True)` — the
  JSON grammar beyond YES/NO (laws 2 and 5): frozen prompt demanding
  exactly one JSON array-of-objects / object with the named keys;
  mechanical parse-or-raise carrying the raw reply (malformed JSON,
  prose, fences, wrong shape, missing keys all raise; empty array/object
  is a legitimate "no matches"). A pure fact command (added to
  `_PURE_LABELS`; session/recall ignored). Deliberate non-goals
  documented: no pydantic, no schema registry, no nesting — flat keys,
  grammar + parser. Suite: 287 mocked tests green in ~2.5s; prompt
  template and full failure truth table pinned in `tests/test_logic.py`;
  example `examples/code-work/extract_failing_tests.py`.
- **Issue #7 (same cycle):** git-snapshot rollback — every `do()` made
  recoverable. `snapshot(tag)` commits tracked+untracked state to a hidden
  ref `refs/ranger/snapshots/<tag>` through a TEMPORARY index
  (`GIT_INDEX_FILE` under `.git/` — the real index/staging/worktree are
  never touched); `rollback(tag)` rewinds via
  `read-tree --reset -u <tree>` plus path-exact `clean -fd --` (never a
  shotgun), returning the honest `restored` path list; HEAD and history
  untouched. `until()`/`resolve()` gained `rollback_on_fail=True`: snapshot
  before round 1, restore on a red budget — `rolled_back`/`rollback` keys
  appear ONLY when a snapshot was actually taken (absent = honest, nothing
  claimed). Pre-round auto-snapshots are opt-in
  (`Ranger(snapshots=True)`) so existing tests pinning exact
  `subprocess.run` call counts stay exact. 15 mocked tests in
  `tests/test_snapshots.py` (git vs harness dispatched on one fake seam);
  `examples/code-work/fix_failing_tests.py` shows `rollback_on_fail`.
  Suite: 302 mocked tests green in ~2.6s; API.md ctor map +
  Snapshots & rollback section, commands.md tier, ARCHITECTURE.md
  (tests:302) synced.
- **Issue #6 (same cycle):** the cumulative cost ledger. `agent.costs`
  (property, returns a copy) accumulates `{"calls", "chars_in",
  "chars_out", "tokens_in", "tokens_out", "wall_s"}` over every completed
  run of both seams (sync `_run` and `_run_async`) — always recorded,
  `stats=True` not required (it only switches run-mode for `last`);
  tokens stay `None` until a backend actually reports them, never a
  guess. `costs_reset()` returns-and-zeroes for bounded per-loop
  accounting. Failed and interrupted runs record nothing; multi-agent
  compositions keep per-agent ledgers. Feeds from the existing
  telemetry seam plus prompt/answer sizes and wall time — zero extra
  harness calls. Suite: 313 mocked tests green in ~2.6s; truth-table
  tests in tests/test_logic.py §13 + async-ledger tests; README, API.md
  Costs section, commands.md catalog, ARCHITECTURE.md (tests:313),
  fix_failing_tests.py loop-cost note synced.
- **Issue #3 (same cycle):** P0 safety rails — `allow`/`deny` path globs
  (ctor + per-call, deny wins, per-call lists fully replace) and
  `dry_run=True` mapping to each harness's real read-only mode
  (opencode `--agent plan`, codex `-s read-only` / resume
  `-c sandbox_mode="read-only"`, claude headless with permission
  grants stripped; pi and openhands REFUSE — no read-only mode
  exists, never pretend). Law 4 pinned: pure-Python fnmatch
  predicates on paths, never prompt politeness. edit/write targets
  are checked BEFORE the spawn (refused targets cost zero calls);
  `do()` with rails probes git-verifiability up front (non-repo →
  refusal before the harness runs) and audits
  `git status --porcelain` against the rails after the round —
  violations raise naming the paths, tree left mutated honestly
  (pair with snapshots/rollback). dry_run skips mutation
  post-checks. Default (no rails) adds zero subprocess calls —
  suites unchanged. 24 mocked tests in tests/test_safety.py;
  README safety section, API.md Safety rails + ctor rows,
  commands.md overrides, SKILL.md row. Suite: 337 mocked tests
  green in ~2.7s (ARCHITECTURE.md tests:337).
- **Issue #4 (same cycle):** the repair tier, shipped honestly on the
  #3 rails. `fix(problem, gate_cmd, condition, max_iter=3)`: mechanical
  pre-verdict (green → ALREADY_GREEN, zero work), one read-only
  diagnose() pass whose result travels inside every repair prompt,
  bounded do() rounds each ending in a mechanical verdict — status
  FIXED/FAILED with no sympathy pass, evidence in last_gate.
  `transform(pattern, instruction, max_files=10)`: batch edit() over
  the sorted glob matches — per-file isolation ({"file", "report"} /
  {"file", "error"}), rails + dry_run per file, no-matches is an
  honest RangerError, specs validated pre-spawn.
  `commit(message=None, allow=None, deny=None)`: stage and commit the
  agent's work — the method's whole git vocabulary is rev-parse /
  status --porcelain / add -A -- / commit -m / rev-parse HEAD;
  no push/reset/clean/checkout exists in it. Refuses non-repos,
  clean trees and rail violations in the changeset (denied paths
  are never staged). 16 mocked tests in tests/test_workflows.py;
  example examples/code-work/ship_fix.py; commands.md planned tier
  promoted to ✅ shipped. Suite: 353 mocked tests green in ~2.8s
  (ARCHITECTURE.md tests:353). Issue queue drained: #10, #9, #8, #7,
  #6, #3, #4 — all committed locally, unpushed.

## Cycle 8 — the self-driving enhancement loop begins

The goal is now `docs/ENHANCEMENT-LOOP.md`: the loop
READ → THINK(web) → PLAN → ENHANCE → CHECK → REVIEW/CRITIC → TEST →
READ, one cycle = one enhancement = one local commit, until
pcina check clean/baselined, radon MI ≥ B and the backlog is empty.

- **Loop cycle 1 — split `_prepare_run` (the cc=38 block).** The worst
  complexity hotspot in the package (radon E, cognitive 38, span 132,
  pcina's top two check violations) is now a ~20-line orchestrator
  over four single-purpose helpers: `_resolve_run_options` (merge +
  validate, returns opts/o/adapter/backend), `_effective_model`
  (per-call > explicit ctor > RANGER_MODEL > backend default),
  `_collect_skills` (files/dirs vs prose grants), `_compose_prompt`
  (recall → grants → effort directive). Behavior byte-identical by
  construction — the argv-equality/prompt-pin/model-precedence tests
  are the evidence — and a NEW test pins the refactor itself:
  test_prepare_run_equals_helper_composition asserts the
  orchestrator's dict equals the helpers' direct composition
  (cmd and full_prompt included). Internal refactor → the web step is
  trivially satisfied (no external API claims). Result: zero pcina
  violations on the seam, no radon E blocks left in the file; worst
  remaining is `challenge` C(20) — the next cycles' meat (shared
  retry/kill transport loop out of _run/_run_async, codex parse
  helper, _parse_extract_answer, pcina baseline decision, the
  2809-LOC file split). Suite: 354 mocked tests green in ~2.9s
  (ARCHITECTURE.md tests:354).

- **Loop cycle 2 — extract the shared transport retry/kill loop.**
  `_run` (cc 19, span 117) and `_run_async` (cc 17, span 116) each
  carried their own spawn → error-attribution → retry →
  parse/ledger/memory pipeline. Now three seams, one law-1
  contract: `_spawn_sync` / `_spawn_async` (one spawn with honest
  cause mapping: missing cwd → RangerError, missing CLI →
  RangerHarnessError + install hint, timeout → RangerTimeout;
  async kill/cancel paths live in `_kill_async`), and ONE shared
  `_complete_run` (parse_output → _record_costs → last → context
  append) used by both transports — the post-run pipeline can no
  longer drift between sync and async. Retry counters stay
  in-place; `_run` drops to cc 11 (pcina info), `_run_async`
  leaves the violation list entirely. Also stabilized a test
  flake the cycle's CHECK caught: the transform isolation test
  faked mutation via file writes whose mtime could collapse
  into the same timestamp under FS granularity — the fake now
  sets mtime explicitly (os.utime with distinct ns). Suite: 354
  mocked tests green, 8 consecutive full runs.

- **Loop cycle 3 — the codex adapter loses its cognitive load.**
  `_CodexBackend.build_cmd` (cc 15, cognitive ~19) and
  `parse_output` (cognitive ~20, nesting 4) — pcina's other two
  headline violations — split into named single-purpose helpers:
  `_sandbox_argv` (resume vs fresh exec + read-only/approve policy),
  `_reasoning_argv` (effort/thinking → model_reasoning_effort flags),
  `_jsonl_events` (stream iterator skipping non-JSON noise),
  `_collect_item_text`, `_collect_events` (texts/thread/usage), and a
  now-tiny `parse_output`. BONUS de-duplication, same law-1 shape:
  the skill-file inlining block — duplicated verbatim in codex,
  claude and openhands — moved up into `_Backend._inline_skills`,
  so the frozen composition can no longer drift between adapters.
  pcina: zero codex violations (was cognitive 19-20 build/parse);
  radon: the whole `_CodexBackend` class leaves the C list (16 →
  max 12 per helper). Behavior byte-identical — argv scaffolding and
  JSONL event handling pinned by existing backend tests. Suite: 354
  mocked tests green.

- **Loop cycle 4 — _parse_extract_answer de-composed (cc 17 → clean).**
  The extract() reply parser (fresh code from issue #8, pcina cc=17)
  splits into `_parse_extract_json` (JSON-or-RangerError, law 5),
  `_extract_rows` (shape normalization: array-of-objects vs one
  object; null rows stay honest empty rows) and a small
  `_parse_extract_answer` verifier — same truths, same error texts,
  same vacuous-keys semantics, byte-identical contract pinned by the
  #8 truth-table tests. radon C list: the cc-17 block is gone. pcina
  boundary after four cycles: complexity warns remain only on
  transform (cc 15), until (cc 15), rollback (cc 18) and legacy
  challenge (cc 20), plus span/params findings; the fresh-vs-legacy
  baseline decision (backlog item 4) is the next gate and needs its
  human call. Suite: 354 green.

- **Loop cycle 5 — rollback/commit/snapshot share their git rails.**
  `Ranger.rollback` (cc 18, fresh from #7) decomposed into
  `_rollback_target` (tag resolution: None = latest, unknown tag
  names what IS recorded), `_paths_changed_since` (the honest
  changed+extras path diff — exact paths, never a shotgun) and the
  orchestrator; the duplicated "cwd is not a git repository"
  refusal across snapshot()/rollback()/commit() is now one
  `_repo_root(who)` with per-method wording preserved byte-for-byte.
  Behavior identical (git argv sequences pinned by
  tests/test_snapshots.py truth tables). pcina: rollback's cc 18
  gone; remaining complexity warns: transform 15, until 15, legacy
  challenge 20/cognitive 18, debate 22 params. User decided this
  cycle: REFATOR-everything policy (no baseline) + push granted
  (12 commits pushed, d237971..d3d464d; issue closing blocked by
  the PAT's missing issue-write scope — manual step left open).
  Suite: 354 mocked tests green.

- **Loop cycle 6 — transform + until/resolve budgets and dedup.**
  `Ranger.transform` (cc 15) gains `_transform_spec` (validation up
  front, zero spawns on a bad spec), the glob-or-refuse body reduced;
  the DUPLICATED rollback_on_fail machinery in `until()` and
  `resolve()` — snapshot-taking and the red-budget tail block, both
  verbatim twins — became `_pre_loop_snapshot(who)` and
  `_rollback_on_red(result, tag)`, shared. `until` cc 15 → 13,
  `transform` off the warn list; snapshot tag names and log lines
  byte-identical (pinned by the red/green truth tables).
  pcina complexity warns remaining: only legacy `challenge` (cc 20,
  cognitive 18) plus one nesting warn at line 385. Suite: 354
  mocked tests green.

- **Loop cycle 7 — legacy challenge de-composed; par_zero complexity
  category reached.** `Ranger.challenge` — the legacy cc-20 /
  cognitive-18 block, pre-dating this loop — now orchestrates three
  per-phase helpers with the frozen prompts and strict line contracts
  verbatim: `_challenge_attack` (single ATTACK: line, ambiguous
  replies are RangerError), `_challenge_defense` (exactly one
  terminal DEFENDED/CONCEDED, concession ends without a ruling
  call), `_challenge_ruling` (RULING: SUSTAINED|WITHDRAWN from
  evidence alone). Plus codex `_json_line`/`_jsonl_events`/
  `_apply_event` restructuring that silenced the last pcina nesting
  warn (elif-in-for depth 4). pcina's complexity AND nesting
  categories now score 10.0/10 with zero warns left. Behavior
  byte-identical — pinned by the challenge truth tables. Remaining
  pcina findings are size/params/clever class (debate 22 params,
  long spans) — next backlog tier. Suite: 354 mocked tests green.

- **Loop cycle 8 — the file split (backlog item 5): MI C → all A.**
  The 3299-LOC `ranger/__init__.py` (radon MI C/0.00) split into 11
  modules via `scripts/split_module.py` (ast-driven, recorded as the
  reproducible layout map; historical, not re-runnable):
  `_util` (constants/exceptions/helpers), `_contracts` (frozen
  prompt/parse laws), `_backends` (the five CLI adapters),
  `_safety`/`_snapshots`/`_loops`/`_multi`/`_commands`/`_engine`
  (six mixins) + `_debate`, with a 260-LOC package root composing
  `Ranger(SafetyMixin, SnapshotMixin, LoopsMixin, MultiMixin,
  CommandsMixin, EngineMixin)`. Tests UNTOUCHED and green because the
  seams were preserved by construction: stdlib module identity
  (tests patch `ranger.subprocess`/`ranger.os`/
  `asyncio.create_subprocess_exec` — submodule `import subprocess`
  binds the same module object), `_BACKEND_CLASSES`/
  `_ASYNC_TWIN_METHODS`/exceptions/`debate` re-exported by
  reference, and the two patchable attributes (`_Spinner`,
  `_warn_default_model`+`_DEFAULT_MODEL_WARNED`) live on the
  package, resolved per call via `import ranger` shims
  (`_spinner_cls()`, forwarder) and `type(self)` for `with_config`.
  Results: every file MI rank A (worst `_backends` 31.91, package
  root 73.61); pcina scan 9.74/10, dead_candidates 15→1 after
  trimming the superset preamble imports. Remaining pcina check
  findings: size/params class only (debate 22 params, long spans,
  one 4-operand chain, 2 bare excepts, raises 9.2 intentional per
  law 5, magic values info). Suite: 354 mocked tests green in ~2.8s.

- **Loop cycle 9 — mechanical warn classes cleared.** The two
  broad `except Exception: pass` cleanup blocks (sync `_kill_tree`
  in `_util`, async `_kill_async` in `_engine`) narrowed to honest
  transport-level tuples — `(subprocess.TimeoutExpired, OSError)` /
  `(OSError, asyncio.TimeoutError)` — so KeyboardInterrupt and
  CancelledError (BaseException) still propagate and the cleanup
  can only swallow what it honestly owns. The 4-operand agent
  precedence chain became two named locals (`per_call_agent`,
  `ctor_agent`). Every evidence/clip magic number (300/150/90/70/
  60/10/8, porcelain 4/3) is now a named module constant in `_util`
  (ANSWER_EXCERPT, ROW_EXCERPT, UI_NOTE_CLIP, UI_RETRY_CLIP,
  LOG_SHA_CLIP, LOG_MSG_CLIP, RAISED_PATHS_LISTED, PORCELAIN_MIN,
  PORCELAIN_PATH_AT) — one place per frozen number. pcina: warns
  41 → 34, scan 9.74 → 9.78; hardcode/bare_except/clever-chain
  categories clear. Remaining warns: long spans (41–94 lines,
  next cycles), 6–8-param internal helpers, the 22-param public
  ctor (API-frozen), and paranoia raises-by-design (law 5's
  parse-or-raise contract). Suite: 354 mocked tests green.

- **Loop cycle 10 — the prep struct IS the transport contract.** The
  internal transport helpers re-passed fields the prep struct already
  carries; now they read `prep["backend"]`/`prep["adapter"]`/
  `prep["label"]`/`prep["use_stats"]`/`prep["use_memory"]` from the
  seam's own dict: `_spawn_sync(cmd, o, prep, _finish)`,
  `_spawn_async(cmd, o, prep)`, `_complete_run(prep, stdout, t0)`
  (7→3 params), with `_prepare_run` gaining the `"label"` key and
  `_run`/`_run_async` dropping their dead unpacks. Law-1 tight: the
  shared seam is now literally the only thing that crosses the
  transport boundary — no re-passed copies can diverge from it.
  pcina: engine transport params 6–8 → under limit (warns 34 → 31,
  scan 9.78 → 9.79). Every remaining params warn is public API or
  test-pinned (ctor 22, debate/until/resolve/fix/challenge,
  `_compose_prompt` called positionally by a frozen test) —
  irreducible without an API break, a human-only call. Suite: 354
  mocked tests green (the prep-struct composition test untouched).
