# ranger

![CI](https://github.com/AlexKay28/ranger/actions/workflows/ci.yml/badge.svg)

Agent-as-a-library. Run the [opencode](https://opencode.ai) or
[codex](https://github.com/openai/codex) coding agents headlessly from plain
Python code — for agentic-loop prototyping. You write code, not chat.

The whole design follows one paradigm: **the agent is a function call —
Python owns the loop, the harness is just the data plane.** Plan → act →
check → repeat maps 1:1 onto expression, statement and condition. See
[docs/PARADIGM.md](docs/PARADIGM.md) for the seven laws every feature is
reviewed against.

## Install

```bash
pip install -e .
```

Requires a harness CLI on PATH: [opencode](https://opencode.ai) (default
backend) and/or [codex](https://github.com/openai/codex). On a distro-pegged
pip (e.g. 22.x) an editable install can fail with "build backend is missing
the build_editable hook" — fix the tool, not the package:
`pip install -U pip`, then retry.

## Quick start (no clone needed)

Straight from GitHub, then a one-line sanity check in your terminal:

```bash
pip install git+https://github.com/AlexKay28/ranger

python -c "import ranger; print(ranger.Ranger.models(match='claude'))"
```

The check needs no model or API budget — it just lists what your local
opencode CLI offers. Got model ids back? You're ready:

```python
import ranger
agent = ranger.Ranger(model="<one of the ids above>")
print(agent.ask("say ok"))
``` Runnable applications live in
[examples/](examples/) — quickstart, model discovery, a full agentic loop, and
a self-hosted project-growth loop.

Live progress: each command draws a morphing line on stderr while it runs
(`⠹ search · TODO items in this repo · 00:03`) and settles as
`✓ search · 00:07 · <first line of answer>` — opencode-wizard style, colors
included. It auto-disables in pipes/tests and honors `NO_COLOR`;
turn it off with `pretty=False`.

Model priority: explicit `Ranger(model=...)` → `$RANGER_MODEL` env var →
package default.

## Usage

```python
agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
agent.summarize("notes.md")          # -> str summary of the file
agent.write("a one-page report on X")  # -> path of the file the agent wrote
agent.do("rename all *.txt files in data/ to *.md")  # -> report of CLI-like work
agent.search("where do we parse config?")            # -> multiline findings report
agent.ask("anything at all")         # -> raw prompt, raw answer
agent.check("all tests pass")        # -> YES/NO verdict as a bool
agent.gate("python -m pytest -q")    # -> exit-code booleans, no model
agent.until("make the tests green", gate_cmd="python -m pytest -q")
                                    # -> loop: plan/do/verify until green
```

Each call is one fresh headless `opencode run` in the agent's working directory
(`cwd=`), with permissions auto-approved so it can actually touch the filesystem.
Pass `session="..."` to share context between calls, `model=` to pick any
`provider/model` ID from `opencode models`.

## Model discovery & configuration

```python
import ranger

ranger.Ranger.models()                      # -> all model IDs
ranger.Ranger.models(match="claude")           # -> substring filter

smart = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
fast  = smart.with_config(model="openrouter/google/gemini-2.5-flash", agent="build")
```

Every command method also accepts per-call overrides:

```python
fast.search("todo items", title="quick scan")
smart.do("refactor auth", timeout=1800)
```

Overridable: `model`, `timeout`, `auto`, `session`, `agent` (opencode agent
name like "build"/"plan"), `title`, `thinking`. Unknown keywords raise
`TypeError` so typos fail loudly.

See [docs/commands.md](docs/commands.md) for the full command catalog —
15 methods at three maturity tiers: what's shipped, what's next, and
what needs bigger machinery (gates, retries, safety rails) —
[docs/API.md](docs/API.md) for the complete, per-setting API reference
(kept mechanically in sync with the code by the test suite), and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a high-level tour of
the codebase and its three architectural decisions.

## Context state (memory)

The agent remembers. Every command exchange is recorded to
`agent.context` in classic OpenAI message format
(`{"role": "user"|"assistant"|"system", "content": ...}`) and recent
history (within a character budget) is recalled into later runs — so
follow-ups like "now do the same for tests/" just work.

```python
agent.context         # the message list
agent.context_summarize()   # -> digest of what happened so far
agent.context_compact()     # collapse history to one system digest
agent.context_clear()       # wipe; returns what was cleared
agent.ask("...", memory=False)  # one stateless run
ranger.Ranger(memory=False)      # or a fully stateless agent
```

Context memory colors your dialogues, never your facts: `ask`/`do`/`write`
recall the recent conversation; `check`/`search`/`summarize` always run
history-independent, so a verdict is about the repo, not the chat
([PARADIGM.md](docs/PARADIGM.md), law 4).

## Backends (harness adapters)

The same API drives different harnesses; the setting is one constructor
argument, per-call overridable:

```python
import ranger

agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")  # opencode (default)
gpt   = ranger.Ranger(backend="codex")            # model from ~/.codex/config.toml
gpt   = ranger.Ranger(backend="codex", model="gpt-5.1-codex")

ranger.register_backend("mine", MyHarnessAdapter)  # your own — one small class
```

Harness differences (flags, sessions, sandboxes, output schemas) are
absorbed by one adapter class per backend — see the Backends section of
[docs/API.md](docs/API.md) for the full capability map and the recipe for
adding your own harness.

## Multi-agent interactions

Two (or three) agents, and the expected patterns as ready-made methods —
verdicts are grammar, budgets are honest, reviewers run free of their own
chat history:

```python
both    = builder.second_opinion(critic, prompt)    # {mine, theirs, differs}
verdict = critic.review(subject, author=builder)    # APPROVE/REJECT/REQUEST_CHANGES
outcome = builder.refine_with(critic, goal)          # the two-agent until()
duel    = critic.challenge(builder)                  # adversarial claim attack
talk    = ranger.debate(builder, critic, topic, judge=skeptic)
```

See the Multi-agent interactions section of [docs/API.md](docs/API.md)
and `examples/multi_agent.py`.

## Skills allow-list

Grant the agent specific skills or operating rules per run — a markdown
file or directory rides along via opencode's `--file` attachment; plain
prose entries are injected as prompt grants.

```python
agent = ranger.Ranger(skills=[
    "skills/haiku/SKILL.md",        # file -> --file attachment
    "skills/pack",                  # dir -> all its *.md attached
    'Always answer in British spelling',  # prose -> prompt grant
])
agent.do("write the changelog", skills=["docs/changelog_style.md"])  # per call
```

## AGI loop, the point of the whole thing

```python
agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")

for i in range(10):
    hits = agent.search(f"TODO and unimplemented spots, pass {i}")
    plan = agent.ask(f"Pick ONE thing to fix from:\n{hits}\nReply with a one-line fix plan.")
    report = agent.do(plan)
    print(f"[pass {i}] {report}")
```
