#!/usr/bin/env python3
"""One-shot split of ranger/__init__.py into modules (loop cycle 8).

HISTORICAL: executed exactly once at cycle 8 against the pre-split
single-file package; kept as the reproducible record of the layout.
Not re-runnable (it reads the original monolith).

Constraints honored:
- tests/ untouched; package re-exports keep the `ranger.<name>` surface
- stdlib seams (ranger.subprocess / ranger.os / asyncio) survive because
  submodule `import subprocess` binds the SAME module object the tests patch
- `ranger._Spinner` is patched by tests → the consumer resolves it through
  the package at CALL time (engine._spinner_cls)
- Ranger becomes mixins + a slim core; inspect.getmembers sees the same set
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "ranger" / "__init__.py").read_text()
LINES = SRC.splitlines()

def seg(a, b):
    return "\n".join(LINES[a - 1:b])

# ---- target-module assignment for Ranger methods -----------------------
MIXIN_OF = {
    # commands (dialogue + fact + async twins + par_map + gate)
    "models": "commands", "with_config": "commands",
    "context_summarize": "commands", "context_compact": "commands",
    "context_clear": "commands", "ask": "commands", "summarize": "commands",
    "read": "commands", "write": "commands", "_transform_spec": "commands",
    "transform": "commands", "do": "commands", "edit": "commands",
    "plan": "commands", "search": "commands", "trace": "commands",
    "test": "commands", "lint": "commands", "diagnose": "commands",
    "critique": "commands", "check": "commands", "extract": "commands",
    "ask_async": "commands", "do_async": "commands",
    "search_async": "commands", "write_async": "commands",
    "edit_async": "commands", "check_async": "commands",
    "par_map": "commands", "gate": "commands",
    # snapshots / git
    "_git": "snapshots", "snapshot": "snapshots", "_repo_root": "snapshots",
    "_rollback_target": "snapshots",
    "_paths_changed_since": "snapshots", "rollback": "snapshots",
    "commit": "snapshots", "_auto_snapshot": "snapshots",
    # bounded loops
    "_gate_ev": "loops", "_gate_evidence": "loops", "_verdict": "loops",
    "_pre_loop_snapshot": "loops", "_rollback_on_red": "loops",
    "until": "loops", "attempt": "loops", "resolve": "loops", "fix": "loops",
    # multi-agent methods
    "verify_claims": "multi", "_last_claim": "multi", "_decision": "multi",
    "_sections": "multi", "review": "multi", "_challenge_attack": "multi",
    "_challenge_defense": "multi", "_challenge_ruling": "multi",
    "challenge": "multi", "second_opinion": "multi",
    "refine_with": "multi",
    # safety rails
    "_resolve_safety": "safety", "_assert_path_allowed": "safety",
    "_guard_do": "safety", "_check_do_after": "safety",
    # transport engine + costs
    "_child_env": "engine", "costs": "engine", "costs_reset": "engine",
    "_record_costs": "engine", "_resolve_run_options": "engine",
    "_effective_model": "engine", "_collect_skills": "engine",
    "_compose_prompt": "engine", "_prepare_run": "engine",
    "_spawn_sync": "engine", "_kill_async": "engine",
    "_spawn_async": "engine", "_complete_run": "engine",
    "_run": "engine", "_run_async": "engine",
}

TREE = ast.parse(SRC)
ranger_cls = next(n for n in TREE.body
                 if isinstance(n, ast.ClassDef) and n.name == "Ranger")
methods = {}
for m in ranger_cls.body:
    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
        start = min([d.lineno for d in m.decorator_list] + [m.lineno])
        methods[m.name] = (start, m.end_lineno)
        assert m.name in MIXIN_OF or m.name in ("__init__", "__repr__"), m.name

ordered = [m.name for m in ranger_cls.body
           if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
assert set(MIXIN_OF) == set(n for n in ordered if n not in ("__init__", "__repr__"))

GROUPS = {k: [] for k in ("commands", "snapshots", "loops", "multi",
                          "safety", "engine")}
for name in ordered:
    if name in ("__init__", "__repr__"):
        continue
    a, b = methods[name]
    GROUPS[MIXIN_OF[name]].append(seg(a, b))

CLASS_DOCSTRING = seg(918, 993)
CORE = seg(*methods["__init__"]) + "\n\n" + seg(*methods["__repr__"])

PRE = """from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ._util import (DEFAULT_MODEL, _LOG, _NO_COLOR, _RESET, _COLORS, _c,
                    _clip, _interrupt_payload, _kill_tree,
                    _RUN_KEYS, _normalize_patterns,
                    _path_matches, RangerError, RangerTimeout,
                    RangerHarnessError)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)
"""

module_doc = {
    "_safety.py": ("Safety rails: allow/deny path predicates and pre/post "
                   "guards around mutating commands (law 4: pure-Python "
                   "predicates, never prompt politeness)."),
    "_snapshots.py": ("Git snapshot/rollback/commit rails: hidden-ref "
                      "snapshots through a temporary index, honest restores, "
                      "stage-and-commit only — no destructive verbs."),
    "_loops.py": ("Bounded agent loops: gates and verdicts, until/attempt/"
                  "resolve/fix — mechanical verdicts, honest budgets, never "
                  "a sympathy pass."),
    "_multi.py": ("Multi-agent methods: claims verification, reviews, "
                  "challenges and refinement — frozen reply contracts, "
                  "adversarial by construction."),
    "_commands.py": ("The command methods: dialogue, facts, async twins and "
                     "bounded parallelism — thin frozen prompts over the "
                     "transport engine, nothing else."),
    "_engine.py": ("The transport engine: run-option resolution, prompt "
                   "composition, spawn/kill/complete pipelines for BOTH "
                   "seams (sync subprocess.run, asyncio), the costs ledger."),
}

CLS = {"safety": "SafetyMixin", "snapshots": "SnapshotMixin",
       "loops": "LoopsMixin", "multi": "MultiMixin",
       "commands": "CommandsMixin", "engine": "EngineMixin"}

for mod, group in GROUPS.items():
    fname = f"_{mod}.py"
    body = "\n\n".join(group)
    extra = ""
    if mod == "multi":
        extra = """

def _ranger_cls():
    \"\"\"Late-bind the Ranger class through the package.

    Ranger is composed FROM these mixins, so importing it here would be
    circular — resolve it per call instead.
    \"\"\"
    import ranger
    return ranger.Ranger
"""
        body = body.replace("isinstance(author, Ranger)",
                            "isinstance(author, _ranger_cls())")
        body = body.replace("isinstance(critic, Ranger)",
                            "isinstance(critic, _ranger_cls())")
    if mod in ("commands", "engine"):
        warn_shim = """

def _warn_default_model():
    \"\"\"Mock seam forwarder: the patchable guard lives on the package.\"\"\"
    import ranger
    ranger._warn_default_model()
"""
        extra += warn_shim
    if mod in ("engine", "commands"):
        extra += """

from ._backends import _BACKEND_CLASSES  # noqa: E402 (runs reference it)
"""
        if mod == "commands":
            body = body.replace(
                "        clone = Ranger.__new__(Ranger)",
                "        cls = type(self)\n"
                "        clone = cls.__new__(cls)  # was Ranger.__new__(Ranger): "
                "resolve via the instance")
        else:
            body = body.replace(
                "            spinner = _Spinner(label, prompt)",
                "            spinner = _spinner_cls()(label, prompt)")
            extra += """

def _spinner_cls():
    \"\"\"Resolve _Spinner through the package at CALL time.

    Tests patch the package attribute ``ranger._Spinner`` — baking the
    class into this module would hide the attribute the mock seam targets.
    \"\"\"
    import ranger
    return ranger._Spinner
"""
    out = (f'"""{module_doc[fname]}"""\n' + PRE + extra + "\n\n"
           f"class {CLS[mod]}:\n"
           '    """Mixin — composed into ranger.Ranger (no bases)."""\n\n'
           + body + "\n")
    (ROOT / "ranger" / fname).write_text(out)

# ---- _util.py -----------------------------------------------------------
(R1, R2) = (52, 127)      # DEFAULT_MODEL .. _path_matches
util = (f'"""Shared constants, exceptions and small helpers for the whole '
        f'package."""\n'
        + "from __future__ import annotations\n\n"
        + "import logging\nimport fnmatch\nimport os\nimport re\nimport signal\n"
          "import subprocess\nimport sys\nimport threading\nimport time\n"
          "from pathlib import Path\n\n" + seg(52, 57) + "\n\n"
        + seg(82, 127) + "\n\n"
        + seg(806, 916) + "\n")
(ROOT / "ranger" / "_util.py").write_text(util)

# ---- _contracts.py ------------------------------------------------------
(RC1, RC2) = (618, 805)
contracts = ('"""Frozen prompt/parse contracts: the \'laws\' every harness '
             'run obeys (law 2).\n\nPrompts are frozen templates; verdicts '
             'parse mechanically or raise — never guessed."""\n'
             + "from __future__ import annotations\n"
               "import json\nimport re\nfrom pathlib import Path\n\n"
               "from ._util import RangerError, RangerHarnessError\n\n"
             + seg(RC1, RC2) + "\n")
(ROOT / "ranger" / "_contracts.py").write_text(contracts)

# ---- _backends.py -------------------------------------------------------
backends = ('"""Harness backend adapters: opencode, codex, pi, openhands, '
            'claude.\n\nOne build_cmd/parse_output contract per CLI; the '
            'public API is identical across them (law 1).\n\nExternal flag '
            'and schema behavior is frozen from official docs of each CLI '
            '(landing commits cite the URLs)."""\n'
            + "from __future__ import annotations\n\n"
              "import json\nimport os\nimport re\nimport subprocess\n"
              "import time\nfrom pathlib import Path\n\n"
              "from ._util import (RangerError, RangerTimeout, RangerHarnessError, "
              "_c, _clip)\n\n"
            + seg(128, 617) + "\n")
(ROOT / "ranger" / "_backends.py").write_text(backends)

# ---- _debate.py ---------------------------------------------------------
debate = ('"""The module-level multi-agent composition: a two-agent '
          'debate.\n\nA debate digests disagreement; it never crowns a '
          'winner (law 5)."""\n'
          + PRE.replace("from ._contracts import", "from ._contracts import")
          + "\n\n" + seg(3225, len(LINES)) + "\n")
(ROOT / "ranger" / "_debate.py").write_text(debate)

# ---- new __init__.py ----------------------------------------------------
head = seg(1, 30)  # module docstring (closes at its own `"""` on line 30)
init = head + """

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ._util import (DEFAULT_MODEL, _LOG, _NO_COLOR, _RESET, _COLORS, _c,
                    _clip, _interrupt_payload, _kill_tree, _Spinner,
                    _RUN_KEYS, _normalize_patterns,
                    _path_matches, RangerError, RangerTimeout,
                    RangerHarnessError)
from ._contracts import (_PURE_LABELS, _ASYNC_TWIN_METHODS, _MEMORY_BUDGET,
                         _do_prompt, _edit_prompt, _write_prompt,
                         _search_prompt, _check_prompt, _extract_keys_clause,
                         _extract_prompt, _parse_extract_json, _extract_rows,
                         _parse_extract_answer, _parse_check_verdict)
from ._backends import (_Backend, _OpenCodeBackend, _CodexBackend,
                        _PiBackend, _OpenHandsBackend, _ClaudeBackend,
                        _BACKEND_CLASSES, backends, register_backend)
from ._debate import debate
from ._safety import SafetyMixin
from ._snapshots import SnapshotMixin
from ._loops import LoopsMixin
from ._multi import MultiMixin
from ._commands import CommandsMixin
from ._engine import EngineMixin

__all__ = ["Ranger", "RangerError", "RangerTimeout", "RangerHarnessError",
           "DEFAULT_MODEL", "register_backend", "backends", "debate"]
__version__ = "0.7.1"

# One-time staleness warning guard: a process that resolves a run to the
# baked DEFAULT_MODEL is told once (per process) that the id may be stale.
# Lives ON THE PACKAGE: tests patch this attribute directly.
_DEFAULT_MODEL_WARNED = False


def _warn_default_model() -> None:
    \"\"\"Warn once per process when the baked DEFAULT_MODEL is chosen.

    The package default is frozen at release time and can go stale; an
    explicit `model=` or `RANGER_MODEL` always silences this. Uses the
    module logger only — ranger never adds logging handlers.
    \"\"\"
    global _DEFAULT_MODEL_WARNED
    if _DEFAULT_MODEL_WARNED:
        return
    _DEFAULT_MODEL_WARNED = True
    _LOG.warning(
        "ranger: using baked DEFAULT_MODEL '%s' which may be stale; "
        "pass model= or set RANGER_MODEL", DEFAULT_MODEL,
    )



class Ranger(SafetyMixin, SnapshotMixin, LoopsMixin, MultiMixin,
             CommandsMixin, EngineMixin):
""" + CLASS_DOCSTRING + """

""" + CORE.rstrip() + "\n"
(ROOT / "ranger" / "__init__.py").write_text(init)
print("split written")
