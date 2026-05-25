# Fetch Eurostat Data

Codex skill for finding relevant Eurostat datasets and fetching official Eurostat statistics through the public Eurostat dissemination API.

The skill helps agents:

- search Eurostat table-of-contents metadata;
- inspect JSON-stat dataset dimensions and labels;
- fetch bounded, filtered slices of data;
- answer with reproducible provenance such as dataset code, filters, unit, geography, and latest period.

## Contents

- `SKILL.md`: Codex skill instructions and metadata.
- `scripts/eurostat_api.py`: Standard-library Python helper for search, dimensions, and fetch commands.
- `references/eurostat-api.md`: Endpoint notes, parameter patterns, and troubleshooting.
- `agents/openai.yaml`: Optional agent display metadata.

## Quick Start

Run commands from this repository:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan
python3 scripts/eurostat_api.py fetch demo_pjan --param geo=DE --param sex=T --param age=TOTAL --last-time-period 5
```

The script uses only the Python standard library. It emits JSON for `search` and `dimensions`, and CSV for `fetch` by default.

## Install As A Codex Skill

Copy this folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R . ~/.codex/skills/fetch-eurostat-data
```

Then restart Codex or reload skills. The skill name is `fetch-eurostat-data`.

## API

This skill uses public Eurostat endpoints and does not require an API key:

- Statistics API: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset_code}`
- Table of contents: `https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt?lang=en`

