# Eurostat Assistant

Ask a question in plain language and get an answer built from current Eurostat data, with the
dataset code, filters, and API URL attached so you can check it. The repository has two parts, and
each works without the other:

- The `fetch-eurostat-data` Codex skill and its CLI helper, which find datasets, list their
  dimensions, and fetch filtered observations.
- A reference web app where you chat with an agent. It answers with sources, a chart, a filterable
  table, and a CSV download.

It works best for focused questions that one Eurostat dataset can answer. It is not a replacement
for the Eurostat Data Browser.

![Eurostat Assistant homepage with a question box and example investigations](docs/images/app-screenshot.png)

## What it does

- Searches Eurostat's catalogue and reads a dataset's dimensions and codes without downloading
  observations.
- Fetches filtered JSON-stat observations and keeps the dataset code, filters, update date, flags,
  and the API URL that reproduces the fetch.
- Shows up to 500 rows in a sortable, filterable table with CSV export.
- Draws trend charts on its own and other chart types on request, including bar, scatter, heatmap,
  histogram, and box plots. You can ask it to sort, relabel, rescale, or add a trendline.
- Pairs two measures on shared geography and period for correlation scatter plots.
- Answers follow-ups from the last chart's rows instead of fetching the same data again.
- Keeps your history in the browser's IndexedDB.

It does not join datasets freely, draw maps, or have accounts, sync, rate limiting, or monitoring.

## Use the Codex skill

The skill and helper need no OpenRouter key and no third-party Python packages.

```bash
mkdir -p ~/.codex/skills
cp -R . ~/.codex/skills/fetch-eurostat-data
```

Reload Codex and ask it to use `$fetch-eurostat-data`. Or call the helper directly:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan
python3 scripts/eurostat_api.py fetch demo_pjan \
  --param geo=DE,FR --param sex=T --param age=TOTAL \
  --last-time-period 5
```

`fetch` prints CSV by default, or JSON with `--output json`. Every fetch needs `--time` or
`--last-time-period`, and returns at most 500 rows unless you pass `--max-rows`.

## Run the web app

You need Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and an
[OpenRouter](https://openrouter.ai/) API key.

```bash
uv sync
cp .env.example .env
```

Edit `.env` before starting the app. Replace the example API key, model names, and password
with your own values:

- `OPENROUTER_API_KEY`: required.
- `OPENROUTER_MODEL_OPTIONS`: required. Comma-separated chat models. The first is the default.
- `OPENROUTER_TITLE_MODEL`: model that writes chat titles. Defaults to `openai/gpt-5.4-nano`.
- `APP_PASSWORD`: required. Locks the app behind a 12-hour session. **Lock app** ends the session
  on the server. Sessions live in server memory, so a restart or a new password signs everyone
  out. On a trusted machine, set `APP_ALLOW_UNLOCKED=true` instead. Never do that on a public
  server.
- `LOCAL_AGENT_CONCURRENCY`: how many agent processes run at once. Defaults to `2`.
- `AIRTABLE_ACCESS_TOKEN`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_ID`: optional. They turn on the
  feedback form.

Leave the optional `AIRTABLE_*` variables blank unless you configure feedback.

Start the app:

```bash
./run.sh
```

Open `http://127.0.0.1:8000`. The server listens only on the loopback interface by default. Set
`HOST` or `PORT` to change where it listens; `HOST=0.0.0.0` allows access from other machines.
Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to the proxy's address to trust its headers.

For feedback, create an Airtable table with these fields:

- `Category`: single select or single-line text.
- `Feedback`: long text.
- `Rating`: number.
- `email`: email or single-line text.
- `Chat log attachment`: attachment.
- `Created at`: created-time field.

Then create a
[personal access token](https://airtable.com/create/tokens) with only the `data.records:write`
scope and only that base. The base and table IDs are in the table URL and start with `app` and
`tbl`. The chat log is sent only if the user opts in.

## How it works

Each question runs in a short-lived child process with a 180-second timeout and a stripped-down
environment. The model can call four tools: search, inspect dimensions, fetch, and publish a
result. The server streams each call to the browser as newline-delimited JSON, validates the final
result, and the browser renders it as a Vega-Lite chart. The model never writes HTML, JavaScript,
or Vega-Lite.

Each request gets at most 12 tool calls. All limits live in `agent_limits.json`. The child process
is not an OS sandbox, so don't add shell or user-code execution without real isolation.

**Download log** in the investigation header exports a JSON diagnostic log without the data rows.
Review it before sharing because chat text can still contain reported values.
**Development** in the sidebar shows the model, tools, limits, and runtime details.

Main endpoints: `POST /api/chat/stream` for streamed answers, `POST /api/chat` for a single
response, and `GET /api/health` for a public readiness check.

## Tests

```bash
uv sync --frozen
npm ci
npx playwright install chromium
uv run python -m unittest discover -v
npm run test:unit
npm run test:smoke
uv run python -m tests.prompt_regression replay
```

None of these need API keys. They run on recorded fixtures, and the smoke test loads the app in
headless Chrome.

Prompt regressions are paired files: a scenario in `tests/prompt_scenarios/<id>.json` with prompts
and expected outcomes, and a cassette in `tests/prompt_cassettes/<id>.json` with recorded
responses. Record a new scenario against live services, then replay offline. Replace `scenario_id`
with the scenario's filename without `.json`:

```bash
uv run python -m tests.prompt_regression record scenario_id
uv run python -m tests.prompt_regression replay scenario_id
```

Review cassettes before committing. They contain Eurostat data and generated answers.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and pull request guidelines. Report
vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
