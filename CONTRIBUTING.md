# Contributing

Thanks for your interest in improving Eurostat Assistant. Bug reports, fixes, and focused
improvements are welcome.

## Before you start

- Report security issues privately as described in [SECURITY.md](SECURITY.md), not in a public
  issue.
- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Keep pull requests small and focused on one change.

## Development setup

Follow the setup steps in the [README](README.md): install the Python environment with `uv sync`
in `backend/`, install the browser test tooling with `npm ci` in `frontend/`, copy `.env.example`
to `.env`, and start the app with `./run.sh`.

## Checks

Run these before opening a pull request. CI runs the same checks.

```bash
cd backend
uv run python -m unittest discover -s tests
uv run python -m tests.prompt_regression replay

cd ../frontend
npm run test:unit
npm run test:smoke
```

Add or update tests for behaviour you change. If you change agent prompts or tools, review the
prompt regression scenarios in `backend/tests/prompt_scenarios/`. Record new cassettes only when the
change needs them, and review their contents before committing.

### Prompt regression scenarios

Each scenario is a pair of files: `backend/tests/prompt_scenarios/<id>.json` holds the prompts and
expected outcomes, and `backend/tests/prompt_cassettes/<id>.json` holds the recorded responses.
Record a scenario against live services once, then replay it offline. Run these from `backend/`,
replacing `scenario_id` with the scenario's filename without `.json`:

```bash
uv run python -m tests.prompt_regression record scenario_id
uv run python -m tests.prompt_regression replay scenario_id
```

Cassettes contain Eurostat data and generated answers, so review them before committing.

## Pull requests

- Describe what changed, why, and how you tested it.
- Do not commit `.env`, API keys, chat logs, or other private data.
- By contributing, you agree that your contributions are licensed under the
  [MIT License](LICENSE).
