#!/usr/bin/env python3
"""Render docs/cheatsheet.png — the README visual command card.

The image is generated from the CONTENT data below (a design spec by the
gpt-6.1-sol critic), and tests/test_docs.py gates that data against the
real public API, so the card can never drift from the code.

Regenerate after changing the API or the version:

    python scripts/cheatsheet.py
"""

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ranger  # noqa: E402  (version string comes from the source of truth)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
W, H = 1200, 1534
PAD = 24
RADIUS = 16

BG = "#0B1018"
PANEL = "#151E2B"
HEADING = "#F0F5FC"
CODE = "#D4E2F3"
COMMENT = "#92A5BC"
ACCENT = "#54E0BC"
BORDER = "#29384D"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def _font(name, size):
    return ImageFont.truetype(str(FONT_DIR / name), size)


def sans_bold(size):
    return _font("DejaVuSans-Bold.ttf", size)


def sans(size):
    return _font("DejaVuSans.ttf", size)


def mono(size):
    return _font("DejaVuSansMono.ttf", size)


def mono_bold(size):
    return _font("DejaVuSansMono-Bold.ttf", size)


# ---------------------------------------------------------------------- #
# card specs: panel bounds, title, one-line description, code lines.
# Code keeps "->" (accent) and "  # ..." (comment) as data so the drift
# gates can grep the real API here.

CARDS = [
    {
        "bounds": (44, 190, 1112, 220),
        "num": "01", "title": "START IN PYTHON",
        "desc": "Requires an authenticated opencode or codex CLI on PATH.",
        "code": [
            "from ranger import Ranger",
            "model = Ranger.models()[0]",
            'a = Ranger(model=model, cwd=".")',
            'print(a.ask("What should we fix first?"))',
            'a.do("Add tests for the parser")',
        ],
        "code_size": 23,
        "code_y": 84,
        "code_step": 25,
    },
    {
        "bounds": (44, 428, 547, 178),
        "num": "02", "title": "DIALOGUE",
        "desc": "Recall conversation; answer, act, or edit one file.",
        "code": [
            "a.ask(prompt)       -> str",
            "a.do(goal)          -> report",
            "a.edit(file, instruction) -> report",
            "a.write(task)       -> file path",
        ],
        "code_y": 88,
        "code_step": 24,
    },
    {
        "bounds": (609, 428, 547, 202),
        "num": "03", "title": "FACTS",
        "desc": "Memory-free facts and verdicts.",
        "code": [
            "a.check(condition)  -> bool",
            "a.read(file, question) -> answer",
            "a.search/summarize(goal) -> findings",
            "a.test()            -> test diagnosis",
            "a.critique(file_or_diff) -> review",
        ],
    },
    {
        "bounds": (44, 648, 1112, 202),
        "num": "04", "title": "LOOPS",
        "desc": "Plan -> act -> verify. Bounded rounds; explicit gates.",
        "code": [
            'a.until("Fix tests", gate_cmd="python -m pytest -q")',
            'a.until("Finish docs", condition="README covers the API")',
            "a.refine_with(critic, \"Fix tests\", max_iter=3)",
            "a.gate(\"python -m pytest -q\")  # bool; no model",
        ],
    },
    {
        "bounds": (44, 868, 1112, 194),
        "num": "05", "title": "MULTI-AGENT",
        "desc": "Compose peers; reviewers and judges ignore their own chat history.",
        "note": "debate: import ranger",
        "code": [
            'critic.review("src/", author=a)       # structured verdict',
            "critic.challenge(a)                  # attack a claim",
            'a.second_opinion(critic, "Safe?")      # compare answers',
            'ranger.debate(a, critic, "Design?", judge=skeptic)',
        ],
        "code_y": 88,
        "code_step": 23,
    },
    {
        "bounds": (44, 1080, 1112, 222),
        "num": "06", "title": "CONFIGURATION",
        "desc": "Constructor defaults; per-call overrides. cwd: constructor/with_config only.",
        "columns": [
            (68, [
                ("model", "model ID"),
                ("backend", "harness adapter"),
                ("cwd", "working directory"),
                ("timeout", "seconds per run"),
                ("auto", "approve tool permissions"),
            ]),
            (624, [
                ("mode", "opencode agent name"),
                ("session", "continue harness context"),
                ("memory_budget", "recall cap in characters"),
                ("stats", "telemetry in a.last"),
                ("skills", "files, directories, prose"),
            ]),
        ],
    },
    {
        "bounds": (44, 1320, 1112, 142),
        "num": "07", "title": "REPLACE THE HARNESS",
        "desc": "opencode (default) or codex. Same API; different harness.",
        "code": [
            'a = Ranger(backend="codex")',
            'ranger.register_backend("mine", MyHarness)',
        ],
        "code_y": 86,
    },
]

HEADER = {
    "name": "ranger",
    "concept": "The agent is a function call.",
    "support": "Python owns the loop. The harness runs the tools.",
    "tagline": "the loop is yours",
}

FOOTER = f"v{ranger.__version__}  |  MIT  |  github.com/AlexKay28/ranger"


# ---------------------------------------------------------------------- #
# rendering

def draw_code_line(d, x, y, text, size):
    """One monospace line; '->' accent, '  # ...' comment-colored."""
    f = mono(size)
    code_part, _hash, comment = text.partition("  # ")
    for seg in re.split(r"(->)", code_part):
        if not seg:
            continue
        color = ACCENT if seg == "->" else CODE
        d.text((x, y), seg, font=f, fill=color)
        x += d.textlength(seg, font=f)
    if comment:
        d.text((x, y), "# " + comment, font=f, fill=COMMENT)


def draw_card(d, card):
    x, y, w, h = card["bounds"]
    d.rounded_rectangle((x, y, x + w, y + h), radius=RADIUS,
                        fill=PANEL, outline=BORDER, width=1)
    # title: accent number, then heading title
    num_f = mono_bold(19)
    title_f = sans_bold(21)
    d.text((x + PAD, y + 18), f"{card['num']} /", font=num_f, fill=ACCENT)
    nx = x + PAD + d.textlength(f"{card['num']} /", font=num_f) + 10
    d.text((nx, y + 16), card["title"], font=title_f, fill=HEADING)
    if card.get("note"):
        note_f = mono(18)
        nw = d.textlength(card["note"], font=note_f)
        d.text((x + w - PAD - nw, y + 20), card["note"],
               font=note_f, fill=COMMENT)
    d.text((x + PAD, y + 54), card["desc"], font=sans(20), fill=COMMENT)

    if "code" in card:
        size = card.get("code_size", 21)
        step = card.get("code_step", size + 6)
        cy = y + card.get("code_y", 94)
        for line in card["code"]:
            draw_code_line(d, x + PAD, cy, line, size)
            cy += step
    if "columns" in card:
        step = 23
        cy = y + 94
        for col_x, rows in card["columns"]:
            ry = cy
            for label, desc in rows:
                f = mono(20)
                d.text((col_x, ry), label, font=f, fill=CODE)
                lx = col_x + d.textlength("memory_budget", font=f) + 16
                d.text((lx, ry), desc, font=f, fill=COMMENT)
                ry += step


def render():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # header — name left, concept lines beside it, tagline top-right
    name_f = sans_bold(58)
    d.text((44, 52), HEADER["name"], font=name_f, fill=HEADING)
    nx = 44 + d.textlength(HEADER["name"], font=name_f) + 40
    d.text((nx, 54), HEADER["concept"], font=sans_bold(29), fill=HEADING)
    d.text((nx, 96), HEADER["support"], font=sans(23), fill=COMMENT)
    tag_f = mono_bold(21)
    tag = HEADER["tagline"]
    d.text((W - 44 - d.textlength(tag, font=tag_f), 60), tag,
           font=tag_f, fill=ACCENT)

    for card in CARDS:
        draw_card(d, card)

    footer_f = mono(18)
    fw = d.textlength(FOOTER, font=footer_f)
    d.text(((W - fw) / 2, 1484), FOOTER, font=footer_f, fill=COMMENT)

    out = REPO / "docs" / "cheatsheet.png"
    img.save(out, optimize=True)
    print(f"wrote {out} ({W}x{H})")


if __name__ == "__main__":
    render()
