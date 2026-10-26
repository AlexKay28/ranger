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
COMMANDS_TEXT = (REPO / "docs" / "commands.md").read_text()
CHEATSHEET_SOURCE = (REPO / "scripts" / "cheatsheet.py").read_text()
SKILL_TEXT = (REPO / "SKILL.md").read_text()

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
    assert "SKILL.md" in README_TEXT              # agent instructions reachable
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
    for command in ("ask", "do", "edit", "write", "check", "read", "search", "summarize", "test",
                    "gate", "until", "review", "challenge", "second_opinion",
                    "refine_with", "debate", "register_backend"):
        assert command in CHEATSHEET_SOURCE, (
            f"cheatsheet misses {command} — update scripts/cheatsheet.py and redraw")
    assert "ranger.__version__" in CHEATSHEET_SOURCE  # version is not hardcoded


def test_root_skill_is_shipped_and_covers_safe_agent_workflows():
    assert SKILL_TEXT.startswith("---\nname: ranger\n")
    for detail in ("pip install rangers", "import ranger", "gate_cmd=",
                   "max_iter", "RangerError", "KeyboardInterrupt",
                   "subprocess.run", "subprocess.Popen", "OpenRouter",
                   "AlexKay28/ranger", "ranger execution bug"):
        assert detail in SKILL_TEXT, f"SKILL.md misses {detail!r}"


def test_examples_compile_and_are_main_guarded():
    example_files = sorted((REPO / "examples").rglob("*.py"))
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
    for path in sorted((REPO / "examples").rglob("*.py")):
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
        p.read_text() for p in sorted((REPO / "examples").rglob("*.py"))
    )
    for command in ("ask", "read", "summarize", "write", "do", "edit", "search", "test", "check",
                    "gate", "until", "models", "with_config",
                    # multi-agent interactions (v0.6)
                    "review", "challenge", "second_opinion", "refine_with",
                    "debate"):
        assert f".{command}(" in all_example_text or f"Ranger.{command}" in all_example_text, (
            f"no example demonstrates .{command}()"
        )


# --- commands.md catalog gates -------------------------------------------

# Methods the catalog may legitimately list as planned (🔜/🌱 tiers).
PLANNED_COMMANDS = {"critique",
                   "fix", "transform", "commit"}

_CATALOG_HEADER = re.compile(r"^### `(?:ranger\.)?(?:Ranger\.|agent\.)?(\w+)\s*\(",
                             re.MULTILINE)


def _catalog_sections(text):
    """Split commands.md into (shipped_area, planned_area) by tier headers."""
    planned_from = text.find("## 🔜")
    return text[:planned_from], text[planned_from:]


def test_commands_catalog_matches_shipped_surface():
    """The ✅ tier of commands.md must equal the real public API, no drift."""
    shipped_area, planned_area = _catalog_sections(COMMANDS_TEXT)
    catalog = set(_CATALOG_HEADER.findall(shipped_area))
    expected = set(PUBLIC_METHODS) | {"debate"}
    assert catalog == expected, (
        f"commands.md ✅ tier drifted: undocumented {expected - catalog}, "
        f"ghost entries {catalog - expected} — sync docs/commands.md with "
        f"ranger/__init__.py"
    )


def test_commands_catalog_planned_tier_only_lists_known_planned():
    """The 🔜/🌱 tiers may only list names that are not shipped yet."""
    _, planned_area = _catalog_sections(COMMANDS_TEXT)
    listed = set(_CATALOG_HEADER.findall(planned_area))
    shipped = set(PUBLIC_METHODS) | {"debate"}
    assert not (listed & shipped), (
        f"commands.md lists shipped methods as planned: {listed & shipped}"
    )
    assert not (listed - PLANNED_COMMANDS), (
        f"commands.md plans unknown commands {listed - PLANNED_COMMANDS} — "
        f"add them to PLANNED_COMMANDS or remove the section"
    )


# --- README gates ----------------------------------------------------------

def test_readme_examples_use_only_shipped_api():
    """Code blocks in README must not reference unshipped methods."""
    shipped = set(dir(Ranger)) | {"models", "Ranger"} | set(dir(ranger))
    shipped = {s for s in shipped if not s.startswith("_")}
    used = {
        name
        for tup in re.findall(
            r"agent\.(\w+)\(|ranger\.Ranger\.(\w+)\(|ranger\.(\w+)",
            README_TEXT,
        )
        for name in tup
        if name and not name.startswith("_")
    }
    unshipped = used - shipped - {"Path"}
    assert not unshipped, f"README uses unshipped API: {unshipped}"


def test_readme_install_command_matches_pypi_distribution():
    """README's pip install line must match the actual PyPI project name."""
    pyproject = (REPO / "pyproject.toml").read_text()
    match = re.search(r'^name\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "cannot find project name in pyproject.toml"
    dist_name = match.group(1)
    assert f"pip install {dist_name}" in README_TEXT, (
        f"README must show `pip install {dist_name}` (the PyPI distribution)"
    )


def test_readme_carries_pypi_badges():
    """Version + downloads badges keep the README/PyPI landing page honest."""
    assert "img.shields.io/pypi/v/" in README_TEXT, "PyPI version badge missing"
    assert "img.shields.io/pypi/dm/" in README_TEXT, "downloads badge missing"
