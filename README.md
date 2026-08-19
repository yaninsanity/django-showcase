# django-showcase

`django-showcase` is a lightweight Django reusable app that generates scenario-first product documentation from an existing Django project.

It is intentionally designed as a local build tool:

- no business models
- no migrations
- no Redis or Celery
- no persistent runtime state in the application database
- no permanent modification of user data

The core pipeline is:

```text
Django project
  -> discovery
  -> scenario graph
  -> capture plan
  -> static report
```

The architecture is deterministic-first. Static project signals drive discovery, while agentic planning is an optional provider boundary that can only return structured `SeedPlan` data.

## Install

```bash
pip install django-showcase
```

Optional AI provider support:

```bash
pip install "django-showcase[ai]"
```

Add the app to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...,
    "django_showcase",
]
```

## Usage

```bash
python manage.py showcase
python manage.py showcase --plan
python manage.py showcase --only orders
python manage.py showcase --agentic
python manage.py showcase --scenarios
```

Common production-safe toggles:

```python
SHOWCASE = {
  "FRONTEND_DIR": "frontend/",
  "FRONTEND_DIRS": ["backend_ui/", "frontend_ui/"],  # optional parallel roots
  "CAPTURE_BACKEND": "auto",  # auto | playwright | placeholder
  "CAPTURE_BASE_URL": "http://127.0.0.1:8000",  # required for real browser captures
  "CAPTURE_TIMEOUT_SECONDS": 20.0,
  "AGENT_PROVIDER": "openai",
  "AGENT_MODEL": "gpt-4.1-mini",
  "AGENT_TIMEOUT_SECONDS": 30.0,
  "AGENT_MAX_RETRIES": 2,
  "AGENTIC_SEED_STRATEGY": "all_pages",  # all_pages | goal_only
  "ARCHIVE_FILENAME": "showcase.zip",
  "PROMPT_FILE": ".showcase/prompts.json",  # optional JSON prompt overrides
  "PROMPTS": {
    # these keys are optional and override defaults in agent/prompts.py
    "seed_planner_system": "...",
    "seed_planner_user": "...",
    "frontend_route_system": "...",
    "frontend_route_user": "...",
  },
}
```

Additional CLI controls:

```bash
python manage.py showcase --agentic --frontend-dir ../frontend --frontend-dir ../admin-frontend
python manage.py showcase --agentic --prompt-file .showcase/prompts.json
python manage.py showcase --agentic --seed-strategy all_pages
```

Default output:

```text
.showcase/
├── manifest.json
├── report/
│   ├── index.html
│   └── scenarios/
└── screenshots/
```

## Frontend compatibility

Discovery is not limited to Django MVT. `discovery/frontend.py` now resolves a framework profile from `package.json` and then switches to the matching scan strategy for React, Vue, Svelte, Angular, or generic Node frontends. Each profile carries its own router file hints, router API signals, and component directory hints, so route and component discovery is framework-aware rather than one-size-fits-all.

Current built-in profiles:

- React: prioritises files with `Routes`, `Route`, `useRoutes`, `createBrowserRouter`
- Vue: prioritises `createRouter`, `createWebHistory`, `RouterView`, `routes`
- Svelte: prioritises `+page`, route folders, and lib/components structure
- Angular: prioritises `app-routing`, `RouterModule`, `provideRouter`, `Routes`
- Node/generic SPA: falls back to broad router/path signals

When deterministic scanning finds nothing and `--agentic` is enabled, the agent receives route-related source excerpts and returns candidate paths, which are validated (`agent/frontend.py`) before entering the pipeline — parameterized, wildcard, and non-`/` paths are rejected.

If OpenAI is not configured (`OPENAI_API_KEY` missing or provider dependency unavailable), the plugin degrades safely to deterministic scanning and writes warnings to the manifest/report instead of failing the run.

Configure the scan root with `SHOWCASE = {"FRONTEND_DIR": "frontend/"}`.

Every discovered route (including admin and configuration routes) gets at least one default scenario candidate and capture target. Scenario IDs are route-scoped (`module.route.state`) to avoid collisions when a module has many pages.

## Data isolation

Seeding writes demo objects only inside an isolated scenario session (`--scenarios`). Each scenario runs inside a database transaction that is always rolled back, so the project database is never polluted. In default read-only mode the executor performs zero writes by construction. Required fields the plan does not specify are filled with obvious demo values (`Demo name`, `demo@example.com`), and required foreign keys are satisfied by reusing or creating minimal related demo objects.

Capture execution is also fail-safe: with `CAPTURE_BACKEND="auto"`, real Playwright capture is attempted only when `CAPTURE_BASE_URL` is configured and Playwright is available; otherwise the engine degrades to placeholder images and records warnings in `manifest.json` and the report.

At the end of every full run, the tool builds `.showcase/showcase.zip` (or your `ARCHIVE_FILENAME`) containing manifest, report, screenshots, and metadata for one-click demo handoff.

## Agent prompts

All prompt text lives in a single module: `src/django_showcase/agent/prompts.py`. Providers (`agent/openai.py`, future backends) may only consume prompts from there, so behaviour changes stay reviewable in one place.

The agent boundary is enforced by construction:

- agents receive read-only schema metadata from `agent/tools.py`
- agents return a structured `SeedPlan`, never code or SQL
- `agent/guardrails.py` validates every plan against real models, fields, choices, and volume limits
- `agent/cache.py` keys plans by provider + goal + schema hash so repeated runs skip the API

## Current scope

This initial implementation focuses on the clean core:

- scenario-first domain model
- Django-native discovery from URL patterns
- deterministic scenario planning
- capture plan compilation
- static report and manifest generation
- explicit extension points for seed providers, agent providers, runtime isolation, and browser capture

The heavier runtime pieces are intentionally isolated behind small interfaces so the package can grow without coupling the core to Playwright or any specific LLM provider.
