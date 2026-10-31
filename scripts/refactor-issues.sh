#!/usr/bin/env bash
# Refactoring issues for the structural debt documented in
# docs/system-analysis.md section 6. Ready to run once the PAT has
# Issues: Read and write permission:
#   bash scripts/refactor-issues.sh --dry-run   # print, don't create
#   bash scripts/refactor-issues.sh             # create via gh
# Every issue is atomic and behavior-frozen: acceptance = 358 tests
# green, pcina check exit 0, scan >= 9.05, byte-identical outputs.

set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

create() {  # create <title> <body>
    local title="$1" body="$2"
    if [ "$DRY" = 1 ]; then
        printf 'ISSUE: %s\n%s\n---\n' "$title" "$body"
    else
        gh issue create --title "$title" --body "$body"
    fi
}

create "Refactor: extract par_map run-assembly from boundary validation" \
"**Problem:** \`CommandsMixin.par_map\` (ranger/_commands.py:562) carries cc 14 and 7 raise-guards; run-assembly (building each inner run, threading the per-item slot, semaphore) is mixed with legitimate trust-boundary validation.

**Proposed solution:** Extract the pure per-call assembly into a helper (cycle-17 pattern: \`_scan_jsonl\`, \`_find_result_object\`); move ZERO raises — all validation stays in \`par_map\` at the boundary. Frozen prompts and per-item exception instances must be byte-identical.

**Acceptance criteria:** suite 358 passed untouched; \`pcina check\` exit 0; scan rating does not fall below 9.05; complexity aspect improves (cc of par_map <= 10); no new paranoia findings (compare pcina-baseline.json by file+message key, ignoring line numbers)."

create "Refactor: split _resolve_run_options precedence merge from raises" \
"**Problem:** \`EngineMixin._resolve_run_options\` (ranger/_engine.py:133) is cc 13: the option-precedence merge (per-call beats ctor beats RANGER_MODEL) is tangled with validation raises.

**Proposed solution:** Extract a pure \`_merge_opts\`-style helper that only merges (no decisions, no raises); keep every raise in the boundary method. No public API, prompt, or error message byte may change; \`quote()\` shares this seam and must stay byte-identical (\`tests/test_quoting.py\` pins it).

**Acceptance criteria:** suite 358 passed untouched; \`pcina check\` exit 0; cc of _resolve_run_options <= 10; \`test_quoting.py\` byte-identity pin still green; no new paranoia findings."

create "Refactor: unify bounded-loop skeleton shared by until/resolve" \
"**Problem:** \`LoopsMixin.until\` (ranger/_loops.py:173) and \`LoopsMixin.resolve\` (:320) are cc 11 twins duplicating the run -> gate -> decide -> exhausted-honestly iteration skeleton.

**Proposed solution:** One internal skeleton helper (or generator) that owns iteration + mechanical gate execution + honest exhaustion; until/resolve keep only their distinct stop conditions and result dicts. Public signatures frozen (22-param ctor and method params are API).

**Acceptance criteria:** suite 358 passed untouched (loop truth-table tests are the spec); \`pcina check\` exit 0; cc of both <= 10; result-dict shapes byte-identical; rollback_on_fail behavior unchanged."

create "Refactor: extract refine_with round body" \
"**Problem:** \`MultiMixin.refine_with\` (ranger/_multi.py:401) is cc 12: the do -> review -> revise round (prompt assembly + grammar parse) is intertwined with loop control.

**Proposed solution:** Extract the round body (submission + strict VERDICT/FINDINGS/CHANGES parse) as a helper; keep loop control in refine_with. Frozen interaction grammar in ranger/_contracts.py untouched.

**Acceptance criteria:** suite 358 passed untouched; \`pcina check\` exit 0; cc <= 10; outcome dict (\`approved\`, \`reviews\`) shape identical; refine_with loop economics (calls per round) unchanged."

create "Docs: document backend adapter classes (parse/build contracts)" \
"**Problem:** The five adapter classes in ranger/_backends.py carry few class-level docstrings; the flags/parse/output contract per CLI is implicit in code, and shipped size findings mark 10 docstring-less public functions.

**Proposed solution:** One-to-three-line class docstrings per adapter documenting: CLI it drives, argv shape build_cmd emits, output format parse_output consumes, session/model caveats. Documentation only — zero code change.

**Acceptance criteria:** suite 358 passed untouched (docs gates enumerate public surface); docstring coverage rises (pcina reports it); no behavioral artifacts; scan size-aspect score improves."

create "Refactor: invert depth-3 guards to guard clauses (9 sites)" \
"**Problem:** Nine nesting-depth-3 infos (pcina scan, 13.5 weighted penalty pts) force readers to track 3-level indent in control flow.

**Proposed solution:** Mechanical guard inversions at the flagged sites (continue/early-return), each locally reviewed; purely structural, byte-identical outputs. Do NOT invert law-5 paranoia validation chains — those warns are pinned by design.

**Acceptance criteria:** suite 358 passed untouched; \`pcina check\` exit 0; nesting aspect score improves; no guard inversion may eliminate a raise, a retry, or an interrupt path."
