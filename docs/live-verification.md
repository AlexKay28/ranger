# Live verification — ranger 0.8.0 against a real harness

Date: 2026-11-04 · harness: **opencode v2.2.5** (the installed local
CLI; the 388-test suite is fully mocked, so this pass is the
complementary truth) · model: a free flash-class model (a real, non-mocked LLM;
the concrete id is internal — redacted by the hygiene gate) · scratch git repo, non-interactive, all
runs through the repo checkout of `ranger` 0.8.0.

Every contract below was verified against REAL subprocess runs and a
REAL model. Outputs are pasted as measured, lightly clipped.

## ask() + quote() + the ledger

```
quote: 9 est tokens, 35 chars
ask(4.7s): "`calc.py` is a tiny calculator module that currently just
defines an `add(a, b)` function … "
ledger: {'calls': 1, 'chars_in': 35, 'chars_out': 214,
         'tokens_in': None, 'tokens_out': None, 'wall_s': 4.73}
```

Honest ledger, tokens stay `None` when the backend reports none.

## until(): a real loop with a mechanical gate

Goal "add `mul(a, b)` to calc.py", `gate_cmd="python -c …assert
mul(2,3) == 6"`. First run: 3 iterations, **30.6s**, 6 CLI calls,
`achieved: False` — because the gate itself said
`/bin/sh: 1: python: not found` (gate spelled wrong: `python3`). The
loop never fabricated success: `last_gate` carried the gate's own
diagnosis. Second run with the corrected gate:

```
achieved: True  iters: 0  already_green: True  0.0s
ledger: {'calls': 0, 'chars_in': 0, … }   # zero model calls
```

The vacuous-green pre-check is real: the agent HAD added `mul` in the
first run's rounds, the fixed gate saw it green, zero work was claimed
or charged. Side-lesson (already the docs' law, now demonstrated):
the agent also rewrote `add()` despite "keep add() as is" prose —
**prose is not a gate**; compound the gate if you want the contract
pinned.

## token_budget: a live spend stop

Est-tokens budget checked before each round against the real ledger:

```
budget 60:  achieved: False  iters: 1  budget_exhausted: True
            ledger chars_in: 412 => est tokens: 103.0
budget 220: achieved: True   iters: 2  (spent 228.5; round 2 was
            already in flight — a round is never cancelled)
budget 400: achieved: True   iters: 3  (spent 411.25, same rule)
```

Exactly the frozen contract: the budget is a before-the-round check,
stops the NEXT round, and never fabricates a failure that isn't
already red.

## snapshot → live mutation → rollback (real git)

`snapshot(tag="before-chaos")` → `do("delete square() entirely")` →
the real model deleted it (import check went red) →
`rollback("before-chaos")`:

```
rollback restored: ['__pycache__/calc.cpython-312.pyc', 'calc.py']
square back? YES          # git HEAD and branches untouched
```

Even the untracked `.pyc` straggler was restored — by exact path, no
shotgun clean.

## deny rails: refusal with named evidence

`deny=["calc.py", "README.md"]`, then a `do()` asking to edit
`calc.py`:

```
RAILS REFUSED: do() touched paths outside the safety rails: calc.py —
the working tree is LEFT MUTATED; pair rails with snapshots=True /
rollback() to recover
```

Error message matches reality: the tree WAS still mutated after the
refusal (post-run audit, not a magic undo), and the documented
pairing — snapshot + rollback — restored it (`git diff` clean).

## Verdict

No contract deviation found live: mechanical-gate honesty, the
pre-check's zero-cost green, before-round budget stops, exact-path
rollback, and rails with named-path evidence all behaved exactly as
the mocked 388-test suite promises. The suite's seams are truthful.
