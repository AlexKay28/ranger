# ranger examples

Runnable applications over `ranger`, organized by the job you want to do.
Install the package first (`pip install rangers`, or `pip install -e .[dev]`
from a clone). Every script is main-guarded, so importing it has no side
effects. All folders except `dummy/` need an authenticated harness CLI
(opencode, codex, pi, claude or openhands) and make real agent calls.

| Folder | Example | Use case | Calls |
|---|---|---|---:|
| [`getting-started/`](getting-started/) | `quickstart.py` | Core `search`, `summarize`, `do`, `write`, `ask` on a target project | several |
| | `model_discovery.py` | Discover models and make configured agent copies | 1 |
| [`code-work/`](code-work/) | `fix_failing_tests.py` | Repair a known test command; the command is a hard gate | <= 2 repair attempts |
| | `edit_one_file.py` | Make one bounded change to an existing file | 1 |
| | `simple_code_review.py` | One file -> focused read-only critique | 1 |
| | `review_before_merge.py` | Evidence report + independent critic for a local diff | 2 |
| | `draft_release_notes.py` | Git history -> exact Markdown release-note draft | 2 |
| | `agentic_loop.py` | Search -> choose one work order -> do, for N passes | 3/pass |
| | `growth_loop.py` | Persona wish -> one goal -> acceptance gate -> log | ~5/cycle |
| [`monitoring/`](monitoring/) | `project_health.py` | Read-only test status, actionable risks, telemetry | 1 + gate |
| | `controls.py` | Gates, checks, bounded loops, stats, modes, skills, context | ~6 |
| [`agent-reasoning/`](agent-reasoning/) | `research_and_plan.py` | Evidence-gathering agent scripts an AI writes for one task: research (search), plan(), red-teamed by second_opinion+challenge | ~5 |
| | `verify_claims.py` | Deep-research pass thin-wrapping agent.verify_claims(): verdict table, honest exit code | 1 + k checks |
| | `micro_task.py` | Micro-task resolver with the honest protocol: pre-flight, compound gate, tri-state report; `--attempt` switches until() to single-shot attempt() | 1-7 (attempt mode: 1-3) |
| [`multiagent/`](multiagent/) | `multi_agent.py` | Second opinion, review, refinement, challenge, debate | ~10 |
| [`backends/`](backends/) | `backends.py` | Same API over opencode/codex; backend registration | 1 |
| [`dummy/`](dummy/) | `mechanical_gates.py` | Deterministic `gate()` demo in a temporary project | **0** |

## Smallest useful recipes

```bash
# no model or login required
python examples/dummy/mechanical_gates.py

# one-file review; exits nonzero unless the critic approves
python examples/code-work/simple_code_review.py /path/to/project src/parser.py

# at most two repair attempts; the shell test command is the truth
python examples/code-work/fix_failing_tests.py /path/to/project "python -m pytest -q"

# read-only test status + three actionable risks
python examples/monitoring/project_health.py /path/to/project "python -m pytest -q"

# an AI agent's pre-work research: evidence -> red-teamed plan
python examples/agent-reasoning/research_and_plan.py /path/to/project "fix the flaky upload test"

# ground your beliefs: verify claims about a topic, mechanically
python examples/agent-reasoning/verify_claims.py /path/to/project "the config parser handles errors"
```

Examples deliberately use only shipped API — anything marked planned in
[`docs/commands.md`](../docs/commands.md) is absent. The test suite imports
every script recursively to keep that promise true.
