# Development history

This is the project's living engineering record. It complements `git log`: Git is the source of
truth for exact diffs and authorship, while this document explains what changed and why the change
was made. The historical entries below were reconstructed from commit messages and diffs. A reason
marked **inferred** was not stated explicitly in the commit and should be read as context, not as a
contemporaneous design decision.

## How to maintain this record

Update this file in the same change as the code it describes:

1. Add a concise entry under **Unreleased** while developing. Record the user or system problem,
   the important implementation decision, relevant tests or migrations, and rejected alternatives
   when they materially explain the design.
2. After committing, move the entry into a dated section and add the short commit hash and exact
   commit subject. If one change spans several commits, list all of them under one coherent entry.
3. Link issues, pull requests, benchmarks, or decision documents when they contain useful context.
   Never copy secrets, credentials, private prompts, or sensitive data into this record.
4. Keep entries answer-first. Git already preserves line-level detail; this record should preserve
   intent, trade-offs, compatibility implications, and operational consequences.

Suggested entry shape:

```markdown
### `abcdef0` — Exact commit subject

- **Changed:** The externally meaningful behavior or architecture change.
- **Reasoning:** The problem addressed, why this approach was chosen, and important trade-offs.
- **Validation/impact:** Tests, migration requirements, compatibility notes, or follow-up work.
```

## Unreleased

### Throttle failed app unlock attempts

- **Changed:** `POST /api/auth/unlock` allows 5 failed attempts per client address and 50 across
  all clients in a 15-minute sliding window. Further attempts get HTTP 429 with `Retry-After` and
  are not checked against the password. A successful unlock clears the client's counter. The
  Docker image no longer passes `--forwarded-allow-ips="*"`; it trusts proxy headers only from
  the addresses in `FORWARDED_ALLOW_IPS`, defaulting to 127.0.0.1 as `run.sh` does.
- **Reasoning:** The password check had no attempt limit. Trusting forwarded headers from any
  address let a client send a new `X-Forwarded-For` value with each request and never hit the
  per-client limit. The global cap bounds memory and total guessing, at the cost that a
  distributed attacker can block unlocking for everyone for up to 15 minutes.
- **Validation/impact:** Added tests with a patched clock for lockout, rejection of the correct
  password while locked out, reset on success, window expiry, per-client isolation, the global
  cap, and pruning. Docker deployments behind a reverse proxy must set `FORWARDED_ALLOW_IPS` to
  the proxy's address, or all users share one per-client limit.

### Neutralise formulas in CSV exports

- **Changed:** CSV export now prefixes text cells starting with `=`, `+`, `-`, `@`, tab, or carriage
  return with an apostrophe. Numbers are untouched. CSV building moved from `result_view.js` into
  the DOM-free `static/csv.js` so it can be unit tested.
- **Reasoning:** Labels and values come from Eurostat responses and model output. A cell such as
  `=HYPERLINK(...)` became a live formula when the export was opened in Excel or LibreOffice.
- **Validation/impact:** Added unit tests for every trigger character, numbers, quotes, and header
  labels, plus a smoke test that downloads the CSV from the browser and checks its contents.

### Return generic agent errors to clients

- **Changed:** `AgentError` now carries a separate `public_message`. `/api/chat` and
  `/api/chat/stream` return only that message and log the full error server-side. Timeouts and
  busy capacity keep specific, actionable messages; everything else returns a generic retry message.
- **Reasoning:** Child-process failures were forwarded verbatim, exposing Python tracebacks,
  absolute server paths, and up to 1,000 characters of OpenRouter error bodies to any user.
- **Validation/impact:** Added endpoint tests confirming internal detail is logged but not returned
  for both the JSON and streaming endpoints. Operators should read server logs to diagnose failures.

### Refuse to start without an app password

- **Changed:** The server now fails at startup when `APP_PASSWORD` is unset, unless
  `APP_ALLOW_UNLOCKED=true` is set explicitly. `run.sh` applies the same check before launching.
- **Reasoning:** In preparation for open-sourcing, a deployment that forgot the password left every
  `/api/*` endpoint open, letting anyone spend the operator's OpenRouter credit and write to their
  Airtable feedback table. Failing closed makes the unlocked mode a deliberate choice.
- **Validation/impact:** Added startup tests for the missing-password, opt-in, and password cases.
  Existing deployments without `APP_PASSWORD` must set it or opt in before upgrading.

### Prevent conflicting Eurostat time selectors

- **Observed behavior:** A paired electricity-price and unemployment request completed catalogue
  discovery and dimension inspection, but all observation fetches failed. Retrying could appear to
  resolve the problem when the model happened to generate a different combination of arguments.
- **Root cause:** The `fetch_eurostat` contract allowed an explicit `time` selection and
  `last_time_period` in the same request. The host validation and CLI helper passed both through,
  while the Eurostat Statistics API rejects `time`/`TIME_PERIOD` and `lastTimePeriod` together with
  HTTP 400. One attempted retry removed `time=...` from `params` but retained the separate `time`
  array, so the request remained invalid.
- **Changed:** The tool schema now documents the selectors as mutually exclusive. Host preflight
  validation and the CLI helper reject the conflict before network access, including when an
  explicit time is supplied as a `time=...` entry in `params`. The error tells the agent to choose
  exact periods or the latest N periods.
- **Validation/impact:** Added regression coverage for both explicit-time input forms at the host
  and CLI layers. The complete Python suite passes 81 tests, the JavaScript suite passes 38 tests,
  and the affected electricity and unemployment filters were independently verified to return data
  when either time-selection method is used alone. This changes invalid requests from a remote
  Eurostat error into a deterministic, actionable local error; valid requests are unaffected.

- Changed dimension inspection to read SDMX dataflow structure, codelists, and available-position
  constraints before falling back to a one-period Statistics API request. The normalized catalogue
  now supports matching independently of JSON-stat observation responses, including aliases for
  manufacturing and agriculture terminology. This prevents large data cubes from blocking metadata
  discovery while retaining compatibility when SDMX metadata is missing or malformed; unit tests
  cover URL construction, XML parsing, constraint filtering, observation-free inspection, fallback,
  and the added matching behavior.
- Added this living development record and linked it from the README. It captures the existing Git
  history and establishes a lightweight convention for preserving rationale alongside future work.

## 2026-08-01

### `cc81486` — Update default model to gpt-5.6-luna-pro

- **Changed:** Switched the default model from `openai/gpt-4.1-mini` to
  `openai/gpt-5.6-luna-pro` across runtime configuration, examples, the regression harness, and
  tests, while retaining multiple selectable models.
- **Reasoning:** Keep the default execution path aligned with the preferred model while ensuring
  configuration and documentation do not drift from application behavior.

### `2a7f265` — Add Kimi model and improve paired-measure handling

- **Changed:** Added Kimi as a model option; widened bounded catalogue discovery; excluded aggregate
  geographies from country joins; preserved the semantic x/y axes of paired charts when applying
  styling; and added a recorded electricity/emissions regression scenario.
- **Reasoning:** Relationship analysis needs comparable geographic rows and stable measure roles.
  Aggregates mixed with countries distort scatter results, and restyling must not silently swap the
  meaning of axes.

### `e2cbf24` — Replace E2B sandbox with local process agent

- **Changed:** Removed E2B and introduced a short-lived local child-process runner with an
  allow-listed environment, concurrency semaphore, process cleanup, and 180-second timeout. Renamed
  Eurostat Lens to Eurostat Assistant and replaced the E2B dependency and tests.
- **Reasoning:** Reduce reliance on an external sandbox service and simplify deployment while
  retaining bounded execution and request isolation. The commit explicitly notes that this is
  process isolation, not a strong operating-system sandbox.
- **Operational impact:** `E2B_API_KEY` is no longer required; `LOCAL_AGENT_CONCURRENCY` controls
  parallel agent processes and defaults to two.

### `9c36daa` — Add retry functionality for prompts

- **Changed:** Added retry actions for successful answers and request failures while preserving
  conversation context, plus detection of the latest unanswered error. Moved development settings
  into the top bar.
- **Reasoning:** A transient model or network failure should not force users to reconstruct a
  question or lose conversational context.

### `375fba8` — Introduce agent_limits.json and enforce limits

- **Changed:** Centralized query, response, runtime, and tool-call limits in `agent_limits.json`;
  enforced preflight cell estimates and response-byte caps; consolidated result selection,
  re-charting, and pairing under `publish_result`; and exposed limits in the development UI.
- **Reasoning:** One authoritative limit source avoids divergence among prompts, helpers, runtime
  validation, deployment, and UI. Preflight rejection prevents unnecessarily broad Eurostat
  requests before observations are downloaded.

### `73f1dad` — Add model selection and development settings page

- **Changed:** Added `/settings/development`, a validated model selector backed by
  `OPENROUTER_MODEL_OPTIONS`, runtime/tool metadata, browser-local selection, and coverage for the
  new API and UI behavior.
- **Reasoning:** Make model experimentation and runtime constraints inspectable without changing
  server code, while validating selections server-side so clients cannot request arbitrary models.

## 2026-07-31

### `22412e1` — Add prompt regression, select_result, and matching

- **Changed:** Added an offline cassette-based prompt regression harness and CI workflow; introduced
  explicit result selection after multiple fetches; added accent-insensitive complete-dimension
  matching; and tightened parsing, labels, and chart context.
- **Reasoning:** Unit tests alone cannot protect multi-step agent behavior. Recorded tool exchanges
  make semantic workflows deterministic and reviewable, while explicit result publication prevents
  the wrong fetch from becoming the user-facing answer.

## 2026-07-28

### `8f82a0b` — Show pending response purpose in UI

- **Changed:** Persisted the current tool-call reason in in-flight state and displayed it while a
  response is pending.
- **Reasoning:** Carry the explanation introduced in the preceding commit into the waiting state, so
  users can understand what the agent is doing before the result arrives.

### `dd0b1f0` — Show tool purposes and preserve multi-dataset tables

- **Changed:** Added user-facing reasons to tool calls, preserved separate tables for answers backed
  by several datasets, replaced direct API-query navigation with an in-app observation panel, and
  de-emphasized raw trace details.
- **Reasoning:** Agent activity should communicate intent rather than expose only technical calls,
  and combining sources must not collapse observations into a misleading single table.

## 2026-07-27

### `4c19eeb` — Migrate chat history to IndexedDB

- **Changed:** Replaced the 30-chat `localStorage` design with asynchronous IndexedDB stores for
  metadata and message/event payloads, lazy loading, error notifications, and automatic legacy-data
  migration.
- **Reasoning:** Remove the fixed history limit and avoid loading or rewriting every full chat when
  only the history list is needed. Separate stores reduce routine I/O while keeping history local to
  the browser.
- **Migration:** Existing `eurostat-lens-chats-v1` data migrates automatically on first load.

### `a22da18` — Improve topbar icons and theme toggle

- **Changed:** Replaced text glyphs with accessible SVG controls, enlarged touch targets, clarified
  theme-toggle state, and refined responsive sizing.
- **Reasoning:** Improve visual consistency, touch usability, and accessible labeling across themes
  and screen sizes.

### `36dc314` — Redesign UI with collapsible sections and simplified copy

- **Changed:** Made result tables and provenance collapsible, simplified terminology from
  “investigation” to “chat,” reduced navigation chrome, and added screen-reader-only labels.
- **Reasoning:** Keep dense results available without letting them dominate the answer, and reduce
  unnecessary interface language and space usage.

### `74f5b99` — Add interactive legend for multi-series charts

- **Changed:** Added click selection for legend items so readers can highlight series and dim the
  remainder.
- **Reasoning:** Multi-series Eurostat charts can become visually dense; interactive focus improves
  comparison without discarding context or requiring a new query.

## 2026-07-26

### `a12a8a6` — Add validated chart selection and configure_chart tool

- **Changed:** Added a chart-purpose reference, a host-validated chart configuration path, more
  chart types and safe options, and extensive rendering/contract tests.
- **Reasoning:** Let the model express analytical intent without allowing it to emit executable or
  arbitrary Vega-Lite. Host validation bounds field roles, chart options, and transformations.

### `c884612` — Add Vega-Lite charts and theme toggle

- **Changed:** Replaced the custom SVG renderer with bounded Vega-Lite specifications and
  Vega-Embed, added persistent light/dark theming, and updated chart/theme tests.
- **Reasoning:** Use a mature declarative renderer for richer, more consistent charts while keeping
  the model separated from raw visualization specifications.

### `3a8b407` — Add psycopg dependency and refine chat list styling

- **Changed:** Added the binary Psycopg package and its locked transitive dependencies, and adjusted
  sidebar item sizing and delete-button layout.
- **Reasoning:** PostgreSQL client support was being prepared or enabled; the exact intended
  database integration is not recorded in the commit. The styling changes improve control alignment.

### `a6b6ac0` — Add Railway deployment support with public health endpoint

- **Changed:** Added a production container, Railway configuration, public readiness probe, and
  `0.0.0.0` default binding, with deployment instructions.
- **Reasoning:** Hosted platforms need an externally bound service and an unauthenticated health
  endpoint to promote a locked deployment. The endpoint exposes readiness booleans only.

### `7aa2294` — Add optional app lock with session cookie

- **Changed:** Added password-controlled app locking, signed HMAC session cookies with a 12-hour
  lifetime, authentication endpoints/middleware, lock/unlock UI, tests, and a v0.3.0 version bump.
- **Reasoning:** Provide a lightweight access boundary for exposed deployments without introducing
  accounts or cloud identity. Secure HTTP-only cookies keep the session token out of browser script.

### `41a20f6` — Auto-link dataset codes to Eurostat Data Browser

- **Changed:** Linked recognized dataset codes to the Eurostat Data Browser and separated that link
  from the exact filtered API query.
- **Reasoning:** Readers need both a human-friendly official dataset page and reproducible access to
  the precise request used for the answer.

### `8b0a3a7` — Clarify ambiguous measures after bounded discovery

- **Changed:** Required one catalogue search and inspection of up to two credible datasets before
  asking users to choose among materially different statistical measures.
- **Reasoning:** A clarification grounded in real dataset titles, units, and codes is more useful
  than an abstract question, while strict discovery bounds prevent open-ended exploration.

### `704a5f5` — Add paired-scatter tool, search/rate limits, and validations

- **Changed:** Added server-side joining of two fetched measures for scatter plots; validated
  complete-dimension codes and empty results; bounded calls and rounds; cached/reused identical
  work; improved catalogue ranking; and supported multiple sources in the UI.
- **Reasoning:** Correlation questions require paired observations from separate datasets, but the
  join and chart contract must remain host-controlled. Tool limits and call reuse bound latency,
  cost, and accidental API load.

### `7543f77` — Reuse latest chart result & add export log

- **Changed:** Passed the latest validated result into follow-up turns, added explicit context-result
  reuse, and introduced a downloadable diagnostic log with timing and request events.
- **Reasoning:** Chart-only follow-ups should not repeat identical Eurostat calls. A bounded export
  makes failures and agent behavior inspectable without exporting observation rows by default.

### `622e098` — Expand README with scope, structure, and usage guide

- **Changed:** Reorganized the README around the two independently usable project parts, explicit
  scope and limitations, repository layout, request flow, endpoints, response contract, setup, and
  licensing.
- **Reasoning:** Make operational boundaries and architecture understandable before users install or
  deploy the app, and distinguish the reusable skill from the reference application.

### `462de88` — Add scatter plots and refactor chart rendering

- **Changed:** Added scatter plots and model chart choice, extracted rendering into
  `static/chart.js`, validated numeric axes, and supported horizontal and vertical bars.
- **Reasoning:** Isolate visualization logic for testing and extension, while rejecting chart
  configurations that do not match the returned data.

### `18f107a` — Add live tool-call streaming with sidebar activity UI

- **Changed:** Streamed tool-call progress, arguments, status, duration, and bounded previews to the
  browser; added a CommonMark renderer and streaming/tool-state tests.
- **Reasoning:** Long-running data retrieval should expose progress and diagnostics rather than leave
  the user waiting without feedback.

### `7d3ead9` — Release Eurostat Lens v0.2 with structured results

- **Changed:** Rebuilt the proof of concept as Eurostat Lens with a structured result contract,
  provenance, charts, sortable/filterable tables, CSV export, multi-chat browser history, context
  compaction, responsive UI, and Python/JavaScript coverage.
- **Reasoning:** Move from unstructured chat output to a trustworthy data product whose values,
  filters, source, and visualization can be validated and reused. Context compaction controls model
  input size as conversations grow.

## 2026-05-26

### `beb0da9` — inital commit using e2b

- **Changed:** Added the first FastAPI/browser chat application, an E2B-backed agent runner,
  environment and dependency setup, and launch scripts around the existing Eurostat helper.
- **Reasoning (inferred):** Turn the standalone retrieval skill into a conversational reference app
  while using an external sandbox as the initial execution boundary.

## 2026-05-25

### `b7f82a6` — Initial commit

- **Changed:** Established the reusable Codex skill, standard-library Eurostat search/dimensions/
  fetch CLI, API reference, metadata, README, and MIT license.
- **Reasoning (inferred):** Create a dependency-light, reproducible foundation for discovering and
  retrieving official Eurostat data before adding an application layer.
