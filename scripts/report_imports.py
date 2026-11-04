#!/usr/bin/env python3
"""Clean report: per ranger/*.py module, the KEPT vs DEAD imported names."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def imported_names(tree):
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.setdefault(a.asname or a.name.split(".")[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.setdefault(a.asname or a.name, node.lineno)
    return names


def used_names(tree):
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                used.add(n.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            used.update(node.names)
    return used


for f in sorted((ROOT / "ranger").glob("*.py")):
    tree = ast.parse(f.read_text())
    imports = imported_names(tree)
    used = used_names(tree)
    dead = sorted(n for n in imports if n != "annotations" and n not in used)
    kept = sorted(n for n in imports if n in imports and n in used)
    print(f"== {f.name}: {len(dead)} dead / {len(kept)} kept")
    print("   KEPT:", ", ".join(kept))
    print("   DEAD:", ", ".join(dead))
