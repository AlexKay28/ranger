"""Documentation & examples coverage gates.

These tests fail when the code and the docs drift apart:
- every public Ranger method and module function appears in docs/API.md
- every constructor setting is documented
- every example compiles, is main-guarded, and uses only shipped API

"No docs, no merge" as a mechanical gate, not a promise.
"""

import importlib.util
import inspect
import py_compile
import re
import struct
import sys
from pathlib import Path

import pytest

import ranger
from ranger import Ranger

REPO = Path(__file__).resolve().parent.parent
API_TEXT = (REPO / "docs" / "API.md").read_text()
README_TEXT = (REPO / "README.md").read_text()
CHEATSHEET_SOURCE = (REPO / "scripts" / "cheatsheet.py").read_text()

PUBLIC_METHODS = [
    name for name, _ in inspect.getmembers(Ranger, predicate=inspect.isfunction)
    if not name.startswith("_")
]
CTOR_PARAMS = [
    p for p in inspect.signature(Ranger.__init__).parameters if p != "self"
]
MODULE_PUBLIC = ["Ranger", "RangerError", "DEFAULT_MODEL", "register_backend",
                 "backends", "debate", "__version__"]


def test_api_documents_every_public_method():
    missing = [m for m in PUBLIC_METHODS if f"`{m}" not in API_TEXT]
    assert not missing, (
        f"docs/API.md is missing methods: {missing} — document them or remove them"
    )


def test_api_documents_every_constructor_setting():
    missing = [p for p in CTOR_PARAMS if f"`{p}" not in API_TEXT]
    assert not missing, (
        f"docs/API.md is missing constructor settings: {missing}"
    )


def test_api_documents_module_level_api():
    missing = [n for n in MODULE_PUBLIC if n not in API_TEXT]
    assert not missing, f"docs/API.md is missing module attributes: {missing}"


def test_readme_links_the_reference_and_catalog():
    assert "docs/API.md" in README_TEXT          # API reference reachable
    assert "docs/commands.md" in README_TEXT     # command catalog reachable
    assert "docs/PARADIGM.md" in README_TEXT     # design backbone reachable
    assert "docs/ARCHITECTURE.md" in README_TEXT # codebase tour reachable
    assert "docs/PUBLISHING.md" in README_TEXT   # release checklist reachable
    assert "backend" in API_TEXT                 # backends documented


def test_cheatsheet_is_embedded_and_covers_the_shipped_surface():
    """The README image is generated data, not a stale opaque artifact."""
    image = REPO / "docs" / "cheatsheet.png"
    assert 'src="https://raw.githubusercontent.com/AlexKay28/ranger/' in README_TEXT
    assert image.is_file() and image.stat().st_size > 20_000
    # PNG IHDR: dimensions remain legible on GitHub, no Pillow dependency in CI.
    with image.open("rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"
        assert f.read(4) == b"\x00\x00\x00\r" and f.read(4) == b"IHDR"
        width, height = struct.unpack(">II", f.read(8))
    assert width >= 1000 and height >= 1200
    # Public commands and the extensibility seam must occur in the source
    # data that renders the card. New API -> this gate reminds us to redraw.
    for command in ("ask", "do", "write", "check", "search", "summarize",
                    "gate", "until", "review", "challenge", "second_opinion",
                    "refine_with", "debate", "register_backend"):
        assert command in CHEATSHEET_SOURCE, (
            f"cheatsheet misses {command} — update scripts/cheatsheet.py and redraw")
    assert "ranger.__version__" in CHEATSHEET_SOURCE  # version is not hardcoded


def test_examples_compile_and_are_main_guarded():
    example_files = sorted((REPO / "examples").glob("*.py"))
    assert example_files, "no examples found"
    for path in example_files:
        py_compile.compile(path, doraise=True)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        t0 = __import__("time").perf_counter()
        spec.loader.exec_module(mod)          # importing must be side-effect-free
        assert __import__("time").perf_counter() - t0 < 2.0, f"{path.name} does work at import"
        assert hasattr(mod, "main"), f"{path.name} lacks a main guard"
        assert "if __name__" in path.read_text(), f"{path.name} has no __main__ gate"


def test_examples_use_only_shipped_api():
    shipped = set(dir(Ranger)) | {"models", "Ranger"} | set(dir(ranger))
    shipped = {s for s in shipped if not s.startswith("_")}
    for path in sorted((REPO / "examples").glob("*.py")):
        src = path.read_text()
        used = {
            name
            for tup in re.findall(
                r"agent\.(\w+)\(|ranger\.Ranger\.(\w+)\(|ranger\.(\w+)", src
            )
            for name in tup
            if name and not name.startswith("_")
        }
        unshipped = used - shipped - {"Path"}
        assert not unshipped, f"{path.name} uses unshipped API: {unshipped}"


def test_every_shipped_command_has_an_example_usage():
    """Every public API surface must appear somewhere in examples/."""
    all_example_text = "\n".join(
        p.read_text() for p in sorted((REPO / "examples").glob("*.py"))
    )
    for command in ("ask", "summarize", "write", "do", "search", "check",
                    "gate", "until", "models", "with_config",
                    # multi-agent interactions (v0.6)
                    "review", "challenge", "second_opinion", "refine_with",
                    "debate"):
        assert f".{command}(" in all_example_text or f"Ranger.{command}" in all_example_text, (
            f"no example demonstrates .{command}()"
        )
