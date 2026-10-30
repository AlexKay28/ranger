"""Token-spend control: quote a run before paying, then read the ledger.

    python cost_control.py /path/to/project

Financial honesty, in order:
  1. quote(prompt) — compose the EXACT prompt of a would-be run (the
     same seam as the real call, zero model calls) and measure it
     before a single token is spent
  2. a budget decision made on the quote, not on hope
  3. context_summarize()/context_clear() — shed recall weight when
     the quote says history dominates the bill
  4. the run, then agent.costs — the cumulative ledger of what it
     actually cost (real tokens when the backend reports them)
"""

import sys
from pathlib import Path

import ranger

# token budget for one interactive run; quotes above it get trimmed first
TOKEN_BUDGET = 2000


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    agent = ranger.Ranger(cwd=target, memory=True, timeout=120)

    # a first task seeds context so recall exists to price
    agent.ask("In one sentence, what is this project?", effort="low")

    question = "Read the source and list the three functions with the highest complexity."
    q = agent.quote(question, label="search")
    print("quote:", q["chars_total"], "chars ~", q["est_tokens_in"], "tokens")
    print("segments:", q["segments"])  # request / recall / grants / effort / other

    # 2. decide on the quote — the estimate is a preview, not a bill
    if q["est_tokens_in"] > TOKEN_BUDGET and q["segments"]["recall"] > 0:
        digest = agent.context_summarize()
        agent.context_clear()
        print("recall dominated the bill; replaced history with a",
              len(digest), "char digest")
        q = agent.quote(question, label="search")
        print("re-quote:", q["est_tokens_in"], "tokens")

    # 3. pay for exactly one bounded run
    agent.costs_reset()                       # ledger scoped to this work item
    answer = agent.search(question)
    print("\nanswer head:", answer.splitlines()[0] if answer else "(empty)")

    # 4. what it actually cost (tokens_in stays None until a backend
    # reports them — chars are always real)
    print("\nthis run cost:", agent.costs)


if __name__ == "__main__":
    main()
