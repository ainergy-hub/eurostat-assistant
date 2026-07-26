# Eurostat Lens

Eurostat Lens is an open-source toolkit for answering natural-language questions with current,
official Eurostat data. It contains two independently usable parts:

- **`fetch-eurostat-data` Codex skill and CLI helper** for dataset discovery, dimension inspection,
  and reproducible data retrieval.
- **Eurostat Lens reference web app** for conversational investigations with sourced answers,
  interactive charts, filterable tables, and CSV export.

The project is designed for focused questions that can be answered from a bounded slice of one
Eurostat dataset. It is a reference implementation, not a replacement for Eurostat's full Data
Browser or a general-purpose business intelligence platform.

## Current scope

Eurostat Lens can:

- search Eurostat's table-of-contents metadata for candidate datasets;
- inspect dataset-specific dimensions, category codes, labels, and update dates;
- fetch and flatten filtered JSON-stat 2.0 observations;
- preserve the dataset code, title, applied filters, update date, flags, and reproducible API URL;
- return up to 500 observations in a sortable, filterable table with CSV export;
- render line charts, horizontal or vertical bar charts, and scatter plots;
- pair two filtered measures by shared geography/period keys for correlation scatter plots;
- stream tool-call status, arguments, duration, and bounded result previews to the app;
- perform bounded candidate discovery before asking about ambiguous measures and limit repeated searches, inspections, and fetches;
- keep up to 30 separate investigations in local browser storage;
- carry recent conversational context and a compact summary into follow-up questions;
- reuse the most recent chart's validated rows for follow-ups without fetching the same API data again.

The current scope does not include:

- arbitrary joins or calculations across multiple datasets;
- maps, dashboards, or model-authored custom visualizations;
- accounts, cloud synchronization, shared investigations, or versioned historical snapshots;
- production controls such as user accounts, rate limiting, caching, monitoring, or usage budgets.

Eurostat publishes the latest version of each dataset through its public APIs. The data endpoints do
not require an API key; the optional web app requires E2B and OpenRouter credentials to run its
sandboxed agent.

## Repository layout

- `SKILL.md`: reusable Eurostat agent workflow and answering rules.
- `scripts/eurostat_api.py`: standard-library search, dimensions, and fetch CLI.
- `references/eurostat-api.md`: API patterns and troubleshooting notes.
- `agents/openai.yaml`: Codex skill display metadata.
- `app/sandbox_agent.py`: allow-listed tool-calling agent executed inside E2B.
- `app/e2b_agent.py`: E2B lifecycle, event streaming, and result handling.
- `app/main.py`: FastAPI endpoints and validated public response models.
- `static/`: browser UI, investigation state, Vega-Lite charts, tables, and CSV export.
- `tests/`: helper, response-contract, chart, Markdown, and browser-state tests.

## Use the Codex skill

The skill and CLI helper work without E2B, OpenRouter, or third-party Python packages.

Install this repository as a personal Codex skill:

```bash
mkdir -p ~/.codex/skills
cp -R . ~/.codex/skills/fetch-eurostat-data
```

Restart or reload Codex, then ask it to use `$fetch-eurostat-data`.

You can also call the helper directly:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan
python3 scripts/eurostat_api.py fetch demo_pjan \
  --param geo=DE,FR \
  --param sex=T \
  --param age=TOTAL \
  --last-time-period 5
```

`search` and `dimensions` emit JSON. `fetch` emits CSV by default and also supports
`--output json`. Use `--max-rows` to change the default 500-observation output limit.

## Run the web app

Requirements:

- Python 3.10 or newer;
- [uv](https://docs.astral.sh/uv/);
- an [E2B](https://e2b.dev/) API key;
- an [OpenRouter](https://openrouter.ai/) API key.

Install dependencies and create the local environment file:

```bash
uv sync
cp .env.example .env
```

Add your credentials to `.env`:

```dotenv
E2B_API_KEY=your_e2b_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
APP_PASSWORD=choose-a-strong-password
```

`OPENROUTER_MODEL` is optional and defaults to `openai/gpt-4.1-mini`.
`APP_PASSWORD` enables the app lock. When it is set, the browser receives a secure, HTTP-only
session cookie after a successful unlock. Sessions last 12 hours or until **Lock app** is selected.
Leave `APP_PASSWORD` unset only when the app is running in an already trusted environment.

Start the app:

```bash
./run.sh
```

Open `http://127.0.0.1:8000`. The server listens on all interfaces by default. Set `HOST` or
`PORT` in the environment to override the defaults.

## Deploy to Railway

The repository includes a production `Dockerfile` and `railway.json`. Railway builds the locked
`uv` environment, starts Uvicorn on the platform-provided `PORT`, and checks `/api/health` before
promoting a deployment.

1. Create a Railway project and deploy this repository from GitHub, or run `railway up` from the
   repository root.
2. Add these service variables in Railway:

   ```dotenv
   E2B_API_KEY=your_e2b_api_key
   OPENROUTER_API_KEY=your_openrouter_api_key
   OPENROUTER_MODEL=openai/gpt-4.1-mini
   APP_PASSWORD=choose-a-strong-password
   ```

3. Generate a public domain from the service's **Settings → Networking** page.

Do not set `PORT`; Railway injects it automatically. `OPENROUTER_MODEL` is optional.
`APP_PASSWORD` is strongly recommended for a public deployment. The health endpoint is intentionally
public so Railway can verify a locked deployment, but it exposes only service readiness booleans.

## How the app works

1. The browser sends a question, up to six recent messages, an extractive summary of older
   messages, and the most recent structured chart result to `POST /api/chat/stream`.
2. FastAPI creates a short-lived E2B sandbox and copies in the skill, API helper, and agent runner.
3. The model can use four allow-listed tools: dataset search, dimension inspection, bounded fetch,
   and paired scatter composition.
4. The backend streams each actual tool invocation to the browser as newline-delimited JSON.
5. The host preserves the latest fetched slice as structured rows and provenance, validates any
   model-selected chart fields, and derives a safe default chart when needed.
6. FastAPI validates the public result before the browser renders it. The browser does not execute
   model-authored HTML or JavaScript.

The browser translates the validated `chart` contract into a bounded Vega-Lite specification and
renders it as SVG with Vega-Embed. Vega 6.2.0, Vega-Lite 6.4.3, and Vega-Embed 7.1.0 are loaded from
the jsDelivr CDN; the model never supplies arbitrary Vega-Lite specifications.

Complete display history stays in browser storage. The agent receives the six most recent messages,
a summary of at most 2,400 characters, and (when available) the latest chart's validated result.
The structured result is treated as reusable Eurostat tool output, so follow-ups that are answerable
from those rows do not repeat dataset search, dimension inspection, or the data fetch. A different
dataset, filter, geography, time range, or unavailable fact still triggers a new lookup.

The agent executes at most 12 unique tools per request, with smaller per-tool ceilings. Identical
calls reuse their earlier output, invalid complete-dimension filters are rejected before an API
request, and zero-row fetches do not become public results.

Use **Download log** in the current investigation header to export a local JSON diagnostic log.
The export contains the chat, dataset and filter metadata, tool-call status, timing for new
responses, compacted context, and recorded request errors. Observation rows and tool result
previews are excluded. Review the file before sharing because the chat text may still contain
reported values.

### HTTP endpoints

- `GET /`: web interface.
- `GET /api/auth/status`: app-lock status.
- `POST /api/auth/unlock`: unlock the app with `APP_PASSWORD`.
- `POST /api/auth/lock`: clear the current app session.
- `GET /api/health`: public service and agent-credential readiness probe.
- `POST /api/chat`: validated, non-streaming chat response.
- `POST /api/chat/stream`: newline-delimited status, tool-call, result, and error events.

A successful chat result follows this public contract:

```json
{
  "answer": "The population increased...",
  "result": {
    "dataset": {
      "code": "demo_pjan",
      "title": "Population on 1 January by age and sex",
      "updated": "2026-07-09T11:00:00+0200",
      "source_url": "https://ec.europa.eu/eurostat/api/..."
    },
    "sources": [],
    "filters": {
      "geo": ["DE", "FR"],
      "sex": ["T"],
      "age": ["TOTAL"],
      "lastTimePeriod": ["5"]
    },
    "columns": [],
    "rows": [],
    "chart": {
      "type": "line",
      "orientation": null,
      "x": "time_label",
      "y": "value",
      "series": "geo_label",
      "title": "Population on 1 January by age and sex"
    },
    "warnings": []
  },
  "tool_calls": 4,
  "tool_call_details": []
}
```

Dataset codes shown in answers and source cards link to the corresponding Eurostat Data Browser
page. The separate API-query link preserves the exact filtered request used for the result.

When the agent needs clarification, it can search and inspect candidate datasets without fetching
observations. Its grounded question is returned in `answer`, while `result` remains `null`. A failed
lookup can also return a conversational `answer` with no result.

For correlation questions spanning two datasets, the agent joins observations on shared keys such
as geography and period. The result uses `chart.type: "scatter"`, includes both numeric measures in
each table row, and lists both Eurostat datasets in `sources`.

## Tests

```bash
uv run python -m unittest discover -v
node --check static/app.js
node --check static/chart.js
node tests/chart.test.mjs
node tests/chat_state.test.mjs
node tests/markdown_renderer.test.mjs
```

The automated suite uses recorded JSON-stat-shaped fixtures and does not require API keys. A small,
filtered live request is useful as a separate canary because Eurostat always exposes the latest
dataset version.

## License

This project is available under the [MIT License](LICENSE).
