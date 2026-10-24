# ranger

![CI](https://github.com/AlexKay28/ranger/actions/workflows/ci.yml/badge.svg)

Agent-as-a-library. Run the [opencode](https://opencode.ai) coding agent headlessly
from plain Python code — for agentic-loop prototyping. You write code, not chat.

## Install

```bash
pip install -e .
```

Requires the `opencode` CLI on PATH. Runnable applications live in
[examples/](examples/) — quickstart, model discovery, and a full agentic loop.

## Usage

```python
import ranger

agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
agent.summarize("notes.md")          # -> str summary of the file
agent.write("a one-page report on X")  # -> path of the file the agent wrote
agent.do("rename all *.txt files in data/ to *.md")  # -> report of CLI-like work
agent.search("where do we parse config?")            # -> multiline findings report
agent.ask("anything at all")         # -> raw prompt, raw answer
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

## AGI loop, the point of the whole thing

```python
agent = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")

for i in range(10):
    hits = agent.search(f"TODO and unimplemented spots, pass {i}")
    plan = agent.ask(f"Pick ONE thing to fix from:\n{hits}\nReply with a one-line fix plan.")
    report = agent.do(plan)
    print(f"[pass {i}] {report}")
```
