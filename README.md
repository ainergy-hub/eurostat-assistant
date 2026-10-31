# Eurostat Assistant

Ask a question in plain language and get an answer built from current Eurostat data, with the
dataset code, filters, and API URL attached so you can check it. The repository has two parts, and
each works without the other:

- The `fetch-eurostat-data` Codex skill and its CLI helper, which find datasets, list their
  dimensions, and fetch filtered observations.
- A reference web app where you chat with an agent. It answers with sources, a chart, a filterable
  table, and a CSV download.

It works best for focused questions that one Eurostat dataset can answer.
**Limitations:** it does not freely combine datasets, draw maps, or have user accounts. It is not a
replacement for the [Eurostat Data Browser](https://ec.europa.eu/eurostat/databrowser/).

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

## A. Quick start: web app

You need Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and an OpenRouter API key.

1. Install the dependencies:

   ```bash
   cd backend && uv sync && cd ..
   ```

2. Create your settings file:

   ```bash
   cp .env.example .env
   ```

3. Open `.env` and fill in at least `OPENROUTER_API_KEY`, `OPENROUTER_MODEL_OPTIONS`, and
   `APP_PASSWORD`. See [Settings](#settings) for what each one does.

4. Start the app:

   ```bash
   ./run.sh
   ```

5. Open <http://127.0.0.1:8000>, enter your password, and ask a question.

### What you can ask

It works best for focused questions that one Eurostat dataset can answer. For example:

- *Compare the population of Germany, France, and Italy over the latest 5 years.*
- *How has annual inflation changed in the EU since 2020?*
- *Compare the unemployment rate in Spain and Portugal over the latest 8 years.*

Every answer includes:

- **A chart.** Trends are charted automatically. Ask for a bar, scatter, heatmap, histogram, or box
  plot, or ask it to sort, relabel, rescale, or add a trendline.
- **A table** of up to 500 rows that you can sort, filter, and download as CSV.
- **Sources**: the dataset code, the filters used, the last update date, data flags, and the API URL
  that reproduces the data.

You can ask follow-up questions. Changes to the last chart reuse the data already loaded instead of
fetching it again. To compare two measures, such as GDP and emissions, ask for their relationship
and you get a scatter plot matched by country and year.

Your chat history is saved in your browser, not on the server.

### Settings

All settings live in `.env` at the root of the repository.

| Variable | Required | What it does |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | Yes | Your OpenRouter API key. |
| `OPENROUTER_MODEL_OPTIONS` | Yes | Comma-separated list of chat models. The first is the default. |
| `APP_PASSWORD` | Yes | Password that protects the app. See below. |
| `OPENROUTER_TITLE_MODEL` | No | Model that names your chats. Defaults to `openai/gpt-5.4-nano`. |
| `LOCAL_AGENT_CONCURRENCY` | No | How many questions can run at once. Defaults to `2`. |
| `AIRTABLE_*` | No | Turns on the feedback form. See [Feedback form](#optional-feedback-form). |
| `HOST`, `PORT` | No | Where the server listens. Defaults to `127.0.0.1:8000`. |

**Password and sessions.** After you enter the password, you stay signed in for 12 hours, or until
you click **Lock app**. Restarting the server or changing the password signs everyone out. On your
own machine you can skip the password with `APP_ALLOW_UNLOCKED=true`. Never do that on a server
other people can reach.

**Access from other machines.** By default only your own computer can open the app. Set
`HOST=0.0.0.0` to allow access from your network. Behind a reverse proxy, set
`FORWARDED_ALLOW_IPS` to the proxy's address.

### Optional: feedback form

The feedback form sends submissions to an Airtable table. To turn it on:

1. Create a table with these fields: `Category` (single select or text), `Feedback` (long text),
   `Rating` (number), `email` (email or text), `Chat log attachment` (attachment), and
   `Created at` (created time).
2. Create a [personal access token](https://airtable.com/create/tokens) with only the
   `data.records:write` scope, limited to that base.
3. Set `AIRTABLE_ACCESS_TOKEN`, `AIRTABLE_BASE_ID` (starts with `app`), and `AIRTABLE_TABLE_ID`
   (starts with `tbl`) in `.env`. You can find both IDs in the table's URL.

A user's chat log is attached only if they choose to include it.

## B. Quick start: Codex skill

Copy the skill into your Codex skills folder:

```bash
mkdir -p ~/.codex/skills
cp -R skill ~/.codex/skills/fetch-eurostat-data
```

Reload Codex and ask it to use `$fetch-eurostat-data`.

You can also run the helper yourself from `skill/`:

```bash
cd skill

# Find datasets
python3 scripts/eurostat_api.py search "population by age country"

# See a dataset's dimensions and codes
python3 scripts/eurostat_api.py dimensions demo_pjan

# Fetch data for Germany and France over the latest 5 years
python3 scripts/eurostat_api.py fetch demo_pjan \
  --param geo=DE,FR --param sex=T --param age=TOTAL \
  --last-time-period 5
```

`fetch` prints CSV, or JSON with `--output json`. It needs either `--time` or `--last-time-period`,
and returns at most 500 rows unless you pass `--max-rows`.

### How it works

1. You ask a question in the browser.
2. The server starts a short-lived agent for that question, with a 180-second time limit.
3. The agent can do four things: search Eurostat's catalogue, look up a dataset's dimensions, fetch
   data, and publish a result. It may make up to 12 of these calls.
4. Each step streams to your browser, so you can watch its progress.
5. The server checks the final result, and the browser draws the chart and table.

The model only chooses data and chart settings. It never writes HTML or code that runs in your
browser. All limits are in `skill/agent_limits.json`.

Vega, Vega-Lite, Vega-Embed, and the IBM Plex fonts are served from
`frontend/static/vendor/`. The browser makes no third-party asset requests. Every response sets a
Content-Security-Policy restricting scripts, styles, fonts, and connections to the app's origin.
Vega expressions use `vega-interpreter`, so the policy does not require `'unsafe-eval'`.

The agent runs in a separate process but not in a full sandbox. Don't give it shell access or let it
run user code without proper isolation.

**Download log** in the investigation header saves a diagnostic log without the data rows. Chat text
can still contain values, so check it before sharing. **Development** in the sidebar shows the
model, tools, and limits in use.

API endpoints: `POST /api/chat/stream` (streamed answer), `POST /api/chat` (single response), and
`GET /api/health` (readiness check).

The browser API documentation pages at `/docs` and `/redoc` are disabled for now. Endpoint
definitions remain in the repository, and the OpenAPI schema is available at `/openapi.json`.
To deploy documentation later, self-host the Swagger UI or ReDoc assets and use a CSP nonce or
hash for any inline initialization scripts before re-enabling the documentation routes in
`backend/app/main.py`. FastAPI's default documentation pages use external CDN scripts that the
current Content-Security-Policy blocks. Verify the documentation renders under that policy.

## Development

```text
skill/                   The fetch-eurostat-data Codex skill, also loaded by the server
  SKILL.md               Skill instructions, also the agent's system prompt
  scripts/               eurostat_api.py CLI helper
  references/            API and chart-selection notes
  agent_limits.json      Runtime limits shared by the server and the helper
backend/                 Python: FastAPI server, agent, and their tests
  app/                   FastAPI server and agent runtime
  tests/                 Python unit tests and prompt regression fixtures
  pyproject.toml         Python dependencies (uv)
frontend/                Browser client and its tests
  static/                HTML, CSS, and JavaScript served at /static
  tests/                 Node unit tests and the Playwright smoke test
  package.json           Node test tooling
run.sh                   Starts the web app locally
Dockerfile               Container image for deployment
```

There is no separate frontend build: the backend serves `frontend/static/` as is. Set
`EUROSTAT_STATIC_DIR` to serve the browser files from another folder.

Run the tests. None of them need API keys.

```bash
# Backend
cd backend
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python -m tests.prompt_regression replay

# Frontend (the smoke test starts the backend, so sync the backend first)
cd ../frontend
npm ci
npx playwright install chromium
npm run test:unit
npm run test:smoke
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for pull request guidelines and how to record new prompt
scenarios. Report security issues privately as described in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
