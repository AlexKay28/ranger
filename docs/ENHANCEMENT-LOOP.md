# Goal: ranger enhancement automation — the self-driving improvement loop

An autonomous AI agent works this loop on the ranger repo, cycle after
cycle. The loop is dogfooding: ranger's own paradigm (plan → act → check
→ repeat) applied to ranger itself. Python owns the control flow; the
agent is a function call.

## The loop (one cycle = one enhancement = one local commit)

```
READ → THINK(web) → PLAN → ENHANCE → CHECK → REVIEW/CRITIC → TEST → READ…
```

1. **READ** — ground in reality before having opinions:
   `agent.test()`, `agent.lint()`, `radon cc/mi`, `pcina scan && pcina check`,
   `git log --oneline -10`, open GitHub issues. List the top concrete
   weaknesses (complexity hotspots, MI, budget violations, doc drift).
   Never enhance what you have not measured.

2. **THINK (with web)** — before designing, verify against the world:
   search official docs of the harnesses (opencode/codex/pi/claude codes/
   openhands CLIs), competitor SDK changelogs (claude-agent-sdk,
   openai-agents, pydantic-ai), Python stdlib changes. Every NEW flag,
   schema or API claim that lands in code must be frozen from a live
   source (URL recorded in the commit message), never guessed. If the
   web contradicts an assumption in the codebase, that's a finding, not
   a bug to paper over.

3. **PLAN** — `agent.plan(goal)` or a written plan first: what change,
   which files, expected test delta (new N tests), docs gates to touch,
   paradigm-law check. Smallest safe enhancement that survives review.
   No plan, no enhancement.

4. **ENHANCE** — implement, `Ranger(snapshots=True)`, rails on:
   `allow=["src/**","tests/**","docs/**"]`, `deny=["**/.env",
   "**/secrets*", "**/.git/**"]`. One enhancement per commit; mocked
   tests only (`ranger.subprocess` seam); `python3 -m pytest -q`.

5. **CHECK** — mechanical verdict, not vibes: full suite green ≤60s,
   `<!-- tests:N -->` marker == collected count, docs gates green,
   `pcina check` no NEW violations vs baseline, `radon` average not
   worse, README/API/commands/SKILL synced. A red gate stops the cycle —
   never claim success past a red.

6. **REVIEW/CRITIC** — adversarial pass by a second agent (cheap model
   fine): `debate`/`refine_with`/`second_opinion` against the diff.
   Required questions: law violations? hidden state? prompt-laundered
   safety? sympathy passes? honesty gaps (claimed-but-absent)? Every
   finding is either fixed or explicitly rejected with a reason in the
   commit message.

7. **TEST** — the loop's own gate on itself: suite green, budget honest
   (`agent.costs` before/after), plus one NEW test pinning whatever the
   enhancement changed. If a behavior can't be pinned by a mocked test,
   it isn't done.

8. **READ** — close the cycle by re-reading the changed repo (goto 1):
   update `docs/growth-log.md` cycle entry, then re-measure. The next
   cycle plans from the new numbers, not the old ones.

## Non-negotiables (inherited from SKILL.md / PARADIGM.md)

-.Mocked tests only; one-minute suite budget; no live harness calls in CI.
- Docs gates stay green after every cycle (marker == collected).
- One cycle = one focused commit; never push without explicit ask.
- Stop conditions: red gate, budget (time/tokens via `agent.costs`) or
  ambiguity only a human can resolve — report honestly and stop, never
  claim success after a stop.

## Seed backlog (first cycles — from measured evidence)

1. Split `_prepare_run` (cc=34, span 132, nesting 4) into 3–4 named
   helpers → clears pcina's worst violations; behavior pinned by 353 tests.
2. Extract the shared retry/kill transport loop out of `_run`/`_run_async`.
3. Parse-output helper for `_CodexBackend` (cognitive 19–20, nesting 4).
4. Decide `pcina baseline` vs full budget-compliance; then either
   refactor legacy blocks (`debate`, codex adapter) or pin them.
5. The file problem radon flagged: 2809-LOC single-file package —
   evaluate a split (backends/commands/safety) with tests untouched.

## Completion criterion

The loop retires itself when: `pcina scan` ≥ 9.0 **and** `pcina check`
exits 0 (or a reviewed baseline pins the remainder), radon MI ≥ B, the
backlog is empty, and every cycle in growth-log has green evidence.
