# Contributing

## Setup

```bash
make install
cp .env.example .env
```

## Code Style

- **Formatter**: `black` (88 char line length)
- **Linter**: `ruff` (see pyproject.toml for rules)
- **Type checker**: `pyright` in strict mode
- **Imports**: `isort` with black profile

Run `make check` before submitting a PR.

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(core): add import resolution engine
fix(parser): handle empty files gracefully
docs(readme): update CLI reference
```

## Testing

```bash
make test        # full test suite
make test-cov    # with HTML coverage report
```

Minimum 75% coverage required for merge.
