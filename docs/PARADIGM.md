# The ranger paradigm: agent-as-a-function

Every design decision in ranger follows from one sentence:

> **The agent is a function call. Python owns the loop; the harness is just
> the data plane.**

This page is the backbone of the repository. It is the review criterion for
new features: if a proposal moves control flow into the model or hides
state in a transcript, it is rejected — by design, not by debate.

## The touchpoint

The agentic loop that the agent community describes in prose —
**plan → act → check → repeat** — is *literally* ordinary Python here:

| Agentic vocabulary | Python construct | ranger |
|---|---|---|
| plan | expression | `step = agent.ask("what's the next step?")` |
| act  | statement   | `agent.do(step)` |
| check | condition  | `ok = agent.gate("python -m pytest -q")` |
| loop | `while` / bounded `for` | `until()` — iterations stay visible |

A developer who knows Python but not agents reads the four lines above and
already understands the whole model. An agent power user recognizes their
own loop. That overlap is the point: **agentic control flow = ordinary
Python control flow**. No DSL, no graph JSON, no hidden runtime.

## The seven laws

1. **One call = one process = one contract.**
   Every command is a single isolated invocation of a headless harness CLI
   with a frozen prompt template. Changing a template is a breaking change;
   the test suite pins them.

2. **Returns are typed and mechanically verified — never trusted prose.**
   `write()` returns a path that has been checked to be a regular file.
   `gate()` returns the shell exit code boiled down to a bool.
   `check()` accepts only an unambiguous YES/NO verdict — contradictory
   verdicts and confessions of inability raise instead of guessing.
   Where a machine can decide, no model opinion is recorded.

3. **Python owns all control flow.**
   No model-owned retries, no hidden iteration counts. `until()` reports
   `iterations` honestly; an agent claiming "almost done" cannot buy a
   fifth round — only the gate can.

4. **State is explicit and lives Python-side.**
   `agent.context` is a visible list of messages. The harness keeps no
   ambient identity: sessions are opt-in continuation, not hidden state.
   Corollary — **context memory colors your dialogues, never your facts**:
   recall applies only to dialogue commands (`ask`, `do`, `write`,
   `context_*`); `check`, `search` and `summarize` always run
   history-independent, because a verdict must not be a function of chat.

5. **Failure is an exception, not a message.**
   `RangerError` is raised for the surrounding program to handle — missing
   CLI, timeout, unparseable verdict, unwritten file. Errors never travel
   as prose inside answers.

6. **Composability over orchestration.**
   Plain methods compose into any pipeline the caller can write. ranger
   ships no runtime, no scheduler, no framework — it is a rail your code
   runs on.

7. **The harness is a replaceable data plane.**
   Everything harness-specific (CLI flags, output schemas, sandbox
   semantics) lives in one adapter class per backend. Adding a backend is
   translation, never surgery — control flow, contracts and loops are
   untouched. See `register_backend()` and the Backends section of
   [API.md](API.md).

## What this rules out (and why)

- **The chat paradigm.** State in a transcript, implied control flow,
  transcripts nested in transcripts. Agent users start here and hit a wall
  the moment logic gets real; ranger records raw prompts precisely so
  transcripts cannot nest.
- **The graph/DAG paradigm.** Excellent for large pipelines, but it moves
  control flow out of Python into a second language most users cannot read
  at a glance — wrong trade for a library.
- **ReAct-in-one-call.** The loop exists but is invisible to the
  surrounding program. Violates law 3.

A live demonstration of law 4's corollary: during codex bring-up, a
`check("file exists")` answered NO about a file that provably existed —
because a `## Previous interaction` recall block made the model reason
about the conversation instead of the filesystem. The fix was not a
stronger prompt; it was enforcing purity of query and verification calls.
Paradigm violations are fixed with structure, not politeness.
