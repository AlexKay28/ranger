# Publishing `rangers` to PyPI

The PyPI **distribution** is `rangers`; the Python package remains
`import ranger`. Publishing is a release operation — never run it from an
arbitrary working tree.

## One-time setup

1. Create or sign in to the PyPI account that will own
   [`rangers`](https://pypi.org/project/rangers/).
2. Create a scoped API token for `rangers` (the first release needs an
   account-wide token because the project does not exist yet).
3. Store the token in a password manager or CI secret, **never** in this
   repository, notebook, terminal history, or a wheel.

## Release checklist

From a clean checkout on `main`:

```bash
python -m pip install --upgrade build twine
rm -rf build dist *.egg-info
python -m pytest -q
python -m build
python -m twine check --strict dist/*

# Review exactly what would be uploaded before continuing.
ls -lh dist/
python -m twine upload --repository testpypi dist/*
```

Install the TestPyPI wheel in a fresh environment and import it:

```bash
python -m venv /tmp/rangers-test
/tmp/rangers-test/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple \
  rangers==<version>
/tmp/rangers-test/bin/python -c 'import ranger; print(ranger.__version__)'
```

Only after that succeeds, upload the **same artifacts** to production:

```bash
python -m twine upload dist/*
git tag -a v<version> -m "rangers <version>"
git push origin v<version>
```

PyPI versions are immutable. If anything is wrong after upload, publish a
new patch version; never try to overwrite the existing one.
