# Contributing

## Local setup

Use a project-local virtual environment and install the development extras:

```bash
python -m pip install -e ".[dev,mcp]"
python -m pytest -q
```

Before opening a pull request, also run:

```bash
python -m compileall -q src tests
python -m build --wheel --sdist
```

Keep parser changes covered by offline fixtures. Live KAP checks are optional,
low-intensity validation gates and must use only the public KAP website; do not
add MKK credentials, private endpoints, or copied response dumps containing
personal data.

## Pull requests

Describe the public KAP surface affected, the compatibility impact, and the
tests run. Keep sync and async behavior in parity, preserve the stable Pydantic
models, and avoid committing generated caches, virtual environments, or local
benchmark output.
