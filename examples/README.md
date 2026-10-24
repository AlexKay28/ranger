# ranger examples

Runnable applications over the `ranger` library. Install the package first
(`pip install -e ..` from the repo root) and have the `opencode` CLI on PATH —
examples 2 and 3 issue **real agent runs** and cost time and tokens.

| Example | What it shows | Agent runs |
|---|---|---|
| `quickstart.py` | The five core commands (`search`, `summarize`, `do`, `write`, `ask`) against a target directory | yes, several |
| `model_discovery.py` | `Ranger.models()` discovery, `with_config()` copies, per-call overrides | one, tiny |
| `agentic_loop.py` | A full autonomous loop: search → pick one → do, repeated N passes | yes, 3 per pass |
| `growth_loop.py` | The project-growth loop on any repo: personas wish → pick ONE goal → frozen contract → implement → mechanical acceptance check → append-only log | yes, ~5 per cycle |

```bash
python quickstart.py /path/to/some/project
python model_discovery.py
python agentic_loop.py "clean up this repo" 2
python growth_loop.py /path/to/some/project 3
```

They deliberately use **only shipped API** — anything in
[`docs/commands.md`](../docs/commands.md) marked 🔜 or 🌱 does not appear here.

Importing any example is side-effect-free (agent runs live behind
`if __name__ == "__main__"`), which is how the test suite can import-check
them without spawning opencode.
