# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub:
**Security → Report a vulnerability** on this repository. Do not open a public issue,
pull request, or discussion for a suspected vulnerability.

Include the affected version or commit, steps to reproduce, and the impact you expect. We aim to
acknowledge reports within five working days and will keep you informed while we work on a fix.

## Scope

In scope:

- the FastAPI server in `app/`, including the app lock, session handling, and request limits;
- the browser client in `static/`;
- the agent runner and its handling of model output and Eurostat responses.

Out of scope:

- deployments run by other people, and their configuration;
- vulnerabilities in OpenRouter, Eurostat, Airtable, or other third-party services;
- findings that require an attacker who already knows `APP_PASSWORD`, unless they reach
  beyond what an unlocked user can already do.

## Supported versions

Only the latest commit on `main` receives security fixes.
