# ranger

![CI](https://github.com/AlexKay28/ranger/actions/workflows/ci.yml/badge.svg)

Agent-as-a-library. Run the [opencode](https://opencode.ai) coding agent headlessly
from plain Python code — for agentic-loop prototyping. You write code, not chat.

## Install

```bash
pip install -e .
```

Requires the `opencode` CLI on PATH. On a distro-pegged pip (e.g. 22.x) an
editable install can fail with "build backend is missing the build_editable
hook" — fix the tool, not the package: `pip install -U pip`, then retry. Runnable applications live in
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
import ranger

agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
agent.summarize("notes.md")          # -> str summary of the file
agent.write("a one-page report on X")  # -> path of the file the agent wrote
agent.do("rename all *.txt files in data/ to *.md")  # -> report of CLI-like work
agent.search("where do we parse config?")            # -> multiline findings report
agent.ask("anything at all")         # -> raw prompt, raw answer
agent.check("all tests pass")        # -> YES/NO verdict as a bool
agent.gate("python -m pytest -q")    # -> exit-code booleans, no model
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
what needs bigger machinery (gates, retries, safety rails).

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

## AGI loop, the point of the whole thing

```python
agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")

for i in range(10):
    hits = agent.search(f"TODO and unimplemented spots, pass {i}")
    plan = agent.ask(f"Pick ONE thing to fix from:\n{hits}\nReply with a one-line fix plan.")
    report = agent.do(plan)
    print(f"[pass {i}] {report}")
```
