"""Release metadata invariants that do not need packaging tools in CI."""

import re
from pathlib import Path

import ranger


REPO = Path(__file__).resolve().parent.parent
PYPROJECT = (REPO / "pyproject.toml").read_text()
README = (REPO / "README.md").read_text()


def test_distribution_identity_is_publishable_and_matches_runtime():
    assert 'name = "rangers"' in PYPROJECT  # PyPI name; `ranger` is taken
    version = re.search(r'^version = "([^"]+)"$', PYPROJECT, re.MULTILINE)
    assert version and version.group(1) == ranger.__version__
    assert "readme = { file = \"README.md\"" in PYPROJECT
    assert "requires-python = \">=3.9\"" in PYPROJECT


def test_pypi_readme_uses_an_absolute_cheatsheet_url():
    """PyPI cannot resolve a GitHub-relative image URL in its long description."""
    assert "https://raw.githubusercontent.com/AlexKay28/ranger/" in README
    assert "pip install rangers" in README
    assert "import ranger" in README


def test_source_distribution_manifest_includes_project_assets():
    manifest = (REPO / "MANIFEST.in").read_text()
    for asset in ("LICENSE", "README.md", "docs/cheatsheet.png",
                  "docs/*.md", "scripts/cheatsheet.py"):
        assert asset in manifest
    assert "ranger = [\"py.typed\"]" in PYPROJECT
    assert (REPO / "ranger" / "py.typed").is_file()
