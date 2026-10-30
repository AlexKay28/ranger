"""Frozen prompt/parse contracts: the 'laws' every harness run obeys (law 2).

Prompts are frozen templates; verdicts parse mechanically or raise — never guessed."""
from __future__ import annotations
import json
import re
from pathlib import Path

from ._util import (RangerError, RangerHarnessError, ANSWER_EXCERPT,
                    ROW_EXCERPT)

_PURE_LABELS = frozenset({"check", "critique", "diagnose", "extract", "lint",
                          "read", "search", "summarize", "test", "trace"})

# Command families with async twins (issue #9). par_map validates its
# call specs against this list; everything else stays sync-only.
_ASYNC_TWIN_METHODS = frozenset({"ask", "do", "write", "edit", "search", "check"})

# How many characters of recorded context a run may recall, max.
_MEMORY_BUDGET = 20000

# Frozen command prompt contracts (law 1: one call = one contract; the
# test suite pins them). The sync commands and their async twins build
# prompts from these single sources — a twin can never drift from its
# sync counterpart.


def _do_prompt(goal: str) -> str:
    return (
        f"Accomplish this goal in the current directory: {goal}\n"
        "Use your file and shell tools to actually do the work. "
        "When finished, reply with a short report: what you did, "
        "which files changed, and anything that failed."
    )


def _edit_prompt(target, instruction: str) -> str:
    return (
        f"Edit exactly this existing file: {target}\n\n"
        f"Instruction: {instruction}\n\n"
        "You may modify only that file. Do not create, edit, rename, or "
        "delete any other file. When finished, reply with a short report "
        "of the change and anything that failed."
    )


def _write_prompt(task: str, out) -> str:
    return (
        f"{task}\n\n"
        f"Write your complete answer as a file at exactly: {Path(out).resolve()}\n"
        "Do not print the answer to stdout; the file IS the answer. "
        "When done, reply with the file path only."
    )


def _search_prompt(goal: str) -> str:
    return (
        f"Search this codebase to answer: {goal}\n"
        "Use grep/glob tools over the working directory. "
        "Reply with a plain multiline report: each match as "
        "`file:line` followed by the matching line or a short note. "
        "No code changes."
    )


def _check_prompt(condition: str) -> str:
    return (
        f"Decide whether this condition is TRUE in the current directory: "
        f"{condition}\n"
        "Actually verify it with file reads or shell commands — never "
        "guess. The verdict must be the very first thing you print: "
        "a line containing only YES or only NO, nothing before it. "
        "One short line of evidence may follow it. No other preamble."
    )


def _extract_keys_clause(keys) -> str:
    return ", ".join(f'"{k}"' for k in keys)


def _extract_prompt(request: str, keys, many: bool) -> str:
    keys_list = "[" + _extract_keys_clause(keys) + "]"
    if many:
        shape = ("an answer that is EXACTLY ONE JSON array of objects "
                 '(for no matches: `[]`)')
    else:
        shape = ("an answer that is EXACTLY ONE JSON object "
                 '(for no matches: `{}`)')
    return (
        f"Extract structured data for this request: {request}\n\n"
        "Contract: your entire reply must be "
        + shape
        + f" — every object must carry exactly these keys: {keys_list}. "
        "The reply is raw JSON, nothing else: no prose before or after, "
        "no markdown fences, no comments, no trailing commas. Values may "
        "be strings, numbers, booleans or null — but the named keys must "
        "always be present. Verify the facts in the current directory "
        "first; do NOT modify, create, delete, or rename any file."
    )


def _parse_extract_json(answer: str):
    """JSON-decode an extract() reply, or raise RangerError (law 5)."""
    try:
        return json.loads(answer.strip())
    except ValueError:
        raise RangerError(
            f"extract() could not parse JSON from the agent reply "
            f"(trailing prose or malformed JSON):\n{answer[:ANSWER_EXCERPT]}"
        ) from None


def _extract_rows(data, many: bool, answer: str) -> list:
    """Normalize parsed JSON into a row list: many=True → array elements,
    many=False → the single object as a one-row list. None rows become {}
    (null is an honest empty row); every row must be a JSON object."""
    if many:
        if not isinstance(data, list):
            raise RangerError(
                f"extract() expected a JSON array with many=True, got: "
                f"{answer[:ANSWER_EXCERPT]}"
            )
        rows = [row if row is not None else {} for row in data]
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise RangerError(
                    f"extract() array element {i} is not a JSON object: "
                    f"{str(row)[:ROW_EXCERPT]!r}"
                )
        return rows
    if not isinstance(data, dict):
        raise RangerError(
            f"extract() expected one JSON object with many=False, got: "
            f"{answer[:ANSWER_EXCERPT]}"
        )
    return [data]


def _parse_extract_answer(answer: str, keys, many: bool):
    """Parse an extract() reply mechanically or raise RangerError (law 5)."""
    data = _parse_extract_json(answer)
    rows = _extract_rows(data, many, answer)
    # an empty array/object is the agent's legitimate "no matches" —
    # keys are then vacuously satisfied
    if not many and data == {}:
        return {}
    for i, row in enumerate(rows):
        missing = [k for k in keys if k not in row]
        if missing:
            kind = "row" if many else "object"
            quoted = ", ".join(map(repr, missing))
            excerpt = answer[:ANSWER_EXCERPT]
            head = f"extract() {kind} {i} is missing key(s) "
            tail = f"{quoted} from:\n{excerpt}"
            raise RangerError(head + tail)
    return rows if many else rows[0]


def _parse_check_verdict(answer: str) -> bool:
    """Boil a check() answer down to True/False or raise RangerError.

    Shared by the sync `check()` and the async twin — the verdict
    grammar is one contract (law 2), not two.
    """
    lines = answer.strip().splitlines()

    def standalone(line: str):
        m = re.fullmatch(r"\W*(yes|no)\W*", line.strip(), re.IGNORECASE)
        return m.group(1).upper() if m else None

    # a verdict is a line consisting solely of YES or NO; more than one
    # verdict is a contradiction, which is no verdict at all
    verdicts = [v for v in (standalone(l) for l in lines[:10]) if v]
    joined = "+".join(verdicts)
    if verdicts:
        if "YES+NO" in joined or "NO+YES" in joined:
            raise RangerError(
                "check() got contradictory YES and NO verdicts from:\n"
                + answer[:ANSWER_EXCERPT]
            )
        return verdicts[0] == "YES"

    match = re.match(r"\W*(yes|no)\b", answer.strip(), re.IGNORECASE)
    if match:
        first_line = lines[0] if lines else ""
        rest = first_line[re.match(r"\W*(yes|no)\b", first_line,
                                   re.IGNORECASE).end():]
        if re.search(r"\b(cannot|can'?t|couldn'?t|unable|unable to|"
                     r"unknown|unsure|not sure|no idea)\b", rest,
                     re.IGNORECASE):
            raise RangerError(
                "check() got an unconfident non-verdict from:\n"
                + answer[:ANSWER_EXCERPT]
            )
        return match.group(1).upper() == "YES"
    raise RangerError(
        f"check() could not parse a YES/NO verdict from:\n{answer[:ANSWER_EXCERPT]}"
    )


