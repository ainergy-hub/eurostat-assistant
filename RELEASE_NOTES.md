# Release notes

## 0.3.0 — 2026-11-01

| Component | Version |
| --- | --- |
| Web app (`backend/`, `frontend/`) | 0.3.0 |
| `fetch-eurostat-data` agent skill (`skill/`) | 0.3.0 |

This is the first public release of Eurostat Assistant, formerly Eurostat Lens. It covers
everything since v0.2. The app is now safe to self-host: it requires a password, limits load and
unlock attempts, and serves all browser assets itself. The agent skill now has its own version
number and works in any skill-aware harness, not just Codex.

### Upgrade notes

Read these before upgrading an existing deployment.

- **`APP_PASSWORD` is required.** The server will not start without it. For local use only, set
  `APP_ALLOW_UNLOCKED=true` to opt out.
- **The repository layout changed.** Python code is now in `backend/`, browser code in `frontend/`,
  and the skill in `skill/`. Run `uv sync` in `backend/` (the virtual environment is now
  `backend/.venv`) and `npm ci` in `frontend/`. `.env` stays at the repository root, and URLs are
  unchanged.
- **Local startup listens on 127.0.0.1 only.** Set `HOST=0.0.0.0` to allow access from other
  machines.
- **Proxy headers are trusted only from `FORWARDED_ALLOW_IPS`** (default 127.0.0.1), including in
  Docker. Behind a reverse proxy, set it to the proxy's address. If you don't, all users share one
  unlock-attempt limit.
- **E2B is gone.** `E2B_API_KEY` is no longer used. The agent runs as a local child process.
  `LOCAL_AGENT_CONCURRENCY` (default 2) and `LOCAL_AGENT_QUEUE_LIMIT` (default 4) control load.
- **Restarting the server signs everyone out**, because sessions are now stored on the server.
- **Install the skill as `fetch-eurostat-data`** from the top-level `skill/` folder. See the
  README for install locations for each harness.

### New

- **Choose a model.** Set `OPENROUTER_MODEL_OPTIONS` to offer several OpenRouter models. The first
  is the default. The **Development** page shows the model, tools, and limits in use.
- **More chart types.** Bar, scatter, heatmap, histogram, and box plots, drawn with Vega-Lite and
  checked by the server. Ask the agent to sort, relabel, rescale, or add a trendline. Click a
  legend item to highlight one series.
- **Compare two measures.** Ask how two indicators relate, such as GDP and emissions, and get a
  scatter plot matched by country and year. EU and euro-area totals are left out so they don't
  distort the comparison.
- **Watch the agent work.** Each step streams to the browser with a short reason for it.
- **Retry** a failed or unsatisfying answer without retyping the question.
- **Unlimited chat history**, stored in the browser's IndexedDB. Chats from v0.2 migrate
  automatically.
- **Download log** saves a diagnostic log of a chat without the data rows.
- **Clearer sources.** Dataset codes link to the Eurostat Data Browser, next to the exact API URL
  that reproduces the data.
- The app suggests starting a new chat when a conversation gets long.
- Optional feedback form that saves submissions to Airtable.
- Light and dark themes, a redesigned layout with collapsible sections, and a GitHub link in the
  top bar.

### Security

- Password lock with 12-hour sessions. **Lock app** ends the session on the server, so a copied
  cookie stops working.
- Failed unlocks are limited to 5 per address and 50 in total per 15 minutes.
- Vega and the IBM Plex fonts are served by the app. Nothing loads from a CDN or Google Fonts, and
  a strict Content-Security-Policy is set on every response.
- CSV exports can no longer contain spreadsheet formulas.
- Error messages no longer show server paths, tracebacks, or OpenRouter error text.
- Request bodies over 4 MB are rejected, and excess chat requests get HTTP 429 instead of piling
  up.
- The `/docs` and `/redoc` pages are turned off. The schema is still at `/openapi.json`.
- Added [SECURITY.md](SECURITY.md) with a private way to report vulnerabilities.

### Agent skill 0.3.0

- Version is now in the `SKILL.md` frontmatter (`metadata.version`) and printed by
  `python3 scripts/eurostat_api.py --version`. The helper's `User-Agent` is
  `eurostat-assistant-skill/0.3.0`.
- Works in Claude Code, Codex, the Claude apps, and other skill-aware harnesses.
  `agents/openai.yaml` remains as optional Codex metadata.
- Reads dataset dimensions from SDMX metadata, so large datasets no longer block discovery.
  Matching also understands more manufacturing and agriculture terms.
- Rejects requests that set both an explicit time and "latest N periods" before calling Eurostat,
  with a message saying which to drop. Eurostat used to fail these with HTTP 400.
- Searches up to two candidate datasets before asking you to choose between different measures,
  and grounds the question in real dataset titles and codes.
- Request limits are in `agent_limits.json`, shared with the web app. The helper uses the same
  defaults when the file is missing.

### Fixes

- A stopped agent now always shuts down its helper processes.
- Agents are cancelled when the browser disconnects, freeing their slot.
- Tool activity stays green when the answer succeeds.
- Answers that use several datasets keep a separate table for each.

### Development

- Prompt regression tests replay recorded Eurostat exchanges offline in CI.
- Docker and CI use Python 3.14. The app still supports Python 3.10 and newer.
- Added [CONTRIBUTING.md](CONTRIBUTING.md) and [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md),
  which records why each change was made.
