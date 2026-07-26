# Eurostat Lens

An open-source proof of concept for asking natural-language questions about official Eurostat data.

The project combines a reusable Codex skill with a small FastAPI reference app. An agent searches
Eurostat metadata, inspects dataset dimensions, fetches a bounded slice, and returns:

- a concise interpretation;
- an interactive line or bar chart;
- a sortable, filterable table;
- CSV export;
- the dataset code, title, filters, update date, and reproducible API URL;
- Eurostat observation flags and truncation warnings when present;
- a live sidebar tool-call counter with per-call arguments, status, timing, and bounded result previews;
- multiple device-local investigations with separate histories.

The web app is intentionally a reference interface rather than a replacement for Eurostat's full
Data Browser.

## Repository

- `SKILL.md`: reusable Eurostat agent instructions.
- `scripts/eurostat_api.py`: standard-library Eurostat search, dimensions, and fetch helper.
- `app/sandbox_agent.py`: allow-listed tool-calling agent executed inside E2B.
- `app/e2b_agent.py`: E2B lifecycle and result handling.
- `app/main.py`: FastAPI endpoints and validated public response models.
- `static/`: dependency-free browser UI, table, chart, and CSV export.
- `tests/`: JSON-stat parsing and structured-result contract tests.

## Run the web app

Requirements:

- Python 3.10 or newer;
- [uv](https://docs.astral.sh/uv/);
- an E2B API key;
- an OpenRouter API key.

```bash
uv sync
cp .env.example .env
```

Add your keys to `.env`:

```dotenv
E2B_API_KEY=your_e2b_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
```

Start the app:

```bash
./run.sh
```

Open `http://127.0.0.1:8000`.

## How a question is handled

1. The browser sends the question and recent conversation history to `POST /api/chat/stream`.
2. The backend creates a short-lived E2B sandbox and copies in the skill, helper, and agent.
3. The model may call only three tools: search, inspect dimensions, and bounded fetch.
4. Each actual tool invocation is streamed to the sidebar as newline-delimited JSON.
5. The final fetch is preserved as structured rows and provenance.
6. FastAPI validates the result before returning it to the browser.
7. The browser generates the chart and table without executing model-authored HTML or JavaScript.

Each investigation keeps its complete display history in browser storage. To keep model input costs
bounded, the API receives only the six most recent messages plus an extractive summary of older
turns. The summary is capped at 2,400 characters and retains dataset codes and applied filters where
available. It does not trigger an additional model call, and the agent is instructed to verify
statistical facts again through the Eurostat tools.

Successful responses follow this shape:

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
      "x": "time_label",
      "y": "value",
      "series": "geo_label"
    },
    "warnings": []
  }
}
```

If the agent needs clarification or cannot fetch observations, `result` can be `null` and the
answer remains conversational.

## Use only the skill

The app is optional. To install the reusable skill into Codex:

```bash
mkdir -p ~/.codex/skills
cp -R . ~/.codex/skills/fetch-eurostat-data
```

After restarting or reloading Codex, ask it to use `$fetch-eurostat-data`.

The helper can also be used directly:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan
python3 scripts/eurostat_api.py fetch demo_pjan \
  --param geo=DE,FR \
  --param sex=T \
  --param age=TOTAL \
  --last-time-period 5
```

## Tests

```bash
uv run python -m unittest discover -v
node --check static/app.js
node tests/chat_state.test.mjs
```

The test suite uses recorded JSON-stat-shaped fixtures and does not require API keys. A bounded live
API request is useful as a separate canary because Eurostat always exposes the latest dataset
version.

## POC boundaries

- Each question currently creates a new E2B sandbox.
- Investigation history is device-local and is not synchronized between browsers.
- There are no accounts, saved analyses, or shareable result URLs.
- The app supports line and bar charts; maps and more advanced chart controls are future work.
- A production public deployment still needs rate limiting, caching, monitoring, and model-cost
  controls.

Eurostat's Statistics API and catalogue are public and do not require an API key.
