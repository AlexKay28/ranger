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
