# Agentic Newsletter

An agent that builds a personalised daily news digest from RSS feeds and web search, using a hand-rolled tool-use loop on the Anthropic API.

## Setup (Windows)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
copy config.example.yaml config.yaml
```

Fill in `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`, and edit `config.yaml` for your own topics and sites.

### Environment variables

- `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` - required.
- `DIGEST_CONFIG` - path to the run config. Defaults to `./config.yaml`.
- `DIGEST_DB` - path to the SQLite DB file. Defaults to `digest.db` next to `db.py` (in the container: `/tmp/digest.db`).
- `DIGEST_STORAGE` - `local` (default, no-op), `gcs`, or `s3` (the latter is an unimplemented stub). `gcs` also needs:
  - `DIGEST_GCS_BUCKET` - required when `DIGEST_STORAGE=gcs`.
  - `DIGEST_DB_OBJECT` - object name within the bucket. Defaults to `digest.db`.
  - `DIGEST_ARCHIVE` - `true` to also upload each run's saved `.md`/`.json`/`.html` (and the web edition, if one was rendered) to `gs://<bucket>/digests/` and `gs://<bucket>/web/`. For a real model run (not `--fixture`), also uploads a raw debugging archive - tool results and the model's final JSON reply - to `gs://<bucket>/runs/<timestamp>.json`. Defaults off. Uploading does not make the bucket public - that's a separate infra decision.
  - Auth is Application Default Credentials only - no key files. On GCP compute this is automatic; locally, `gcloud auth application-default login`.
- `DIGEST_DELIVERY` - `local` (default: print + files under `digests/`) or `email` (requires `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and a recipient - see `DIGEST_TO` below).
- `DIGEST_TO` - who the email goes to. Overridable per-config with `recipient` in `config.yaml` (`DIGEST_TO` is the fallback if that's unset).
- `DIGEST_EMAIL_MODE` - `full` (default: every story inline, mobile-first - see `email_render.py`) or `teaser` (a short email with just the lead/secondary headlines and a button to the web edition).
- `DIGEST_WEB_BUCKET` - optional, a GCS bucket the code only ever uploads to, never changes the ACLs/IAM of - it must already grant public read (e.g. `allUsers`:`roles/storage.legacyObjectReader`) outside this code. When set, each run publishes the web edition to `gs://<bucket>/editions/<date>-<random 16-char token>.html` and links `https://storage.googleapis.com/<bucket>/...` in the email (both layout modes). A missing config or a failed publish just means the email sends without that link - never fatal. The rendered page is checked for an email address, the recipient, or `notes` text before it's ever uploaded; if any appear, publishing is skipped.
  - `DIGEST_WEB_LATEST_TOKEN` - optional, a fixed token; when set, each run also publishes a stable `gs://<bucket>/editions/latest-<token>.html` (same content as that day's dated edition).
- `FOOTBALL_DATA_API_KEY` - optional. Enables `sports_data.get_football`, used when a topic's `data.sports` includes `premier_league` (see `config.yaml` below). Unset: that part of the scoreboard is just skipped.

## Running

```
python digest.py
python digest.py --dry-run           # skip saving to the DB, still write files
python digest.py --send              # force email delivery for this run, overriding DIGEST_DELIVERY
python digest.py --fixture           # skip the model and all tools; use a canned front-page digest to test rendering/delivery
python digest.py --fixture --send    # test the actual email send, free and instant - no model calls, no DB writes
python digest.py --check             # validate config/env only - no model, tool, or email calls; exits non-zero on any problem
```

**Delivery happens before the DB is updated.** If sending fails, nothing gets marked "told" - a retry picks the same stories up again. A crash between send and save can at worst repeat a story in the next digest; it can never silently lose one.

`--fixture` is the fast way to test email end-to-end (HTML rendering, SMTP login/send) without paying for or waiting on a real search run. Combine it with `--dry-run` so repeated test runs don't pollute the "already told" history with the fixture's fake URLs.

## File structure

- `registry.py` - the `@tool` decorator, tool registry, and the `run_tool`/`schemas` dispatcher used by the agent loop.
- `tools.py` - the tools themselves: `read_feed`, `find_feed`, `fetch_article`, `search_web`.
- `digest.py` - orchestration and the CLI entry point: loads config, runs the pipeline end to end, hands the result off for delivery.
- `agent_loop.py` - the model-facing tool-use loop: the SYSTEM prompt, building the request, and the turn-by-turn loop itself.
- `fixtures.py` - canned test stories for exercising rendering/delivery without calling the model or any tools (`--fixture`).
- `config.py` / `config.yaml` - loads and validates the run config (lookback window, history window, topics, sites).
- `db.py` - SQLite storage for past stories, used to dedupe and to report follow-ups.
- `storage.py` - syncs the DB file to/from a remote backend before/after a run (currently local-only; `s3`/`gcs` are stubs).
- `delivery.py` - delivery mechanics: saves files, builds and sends the email.
- `newsletter_render.py` - shared rendering logic (safe_url, clamp_summary, format_relative_date, kicker/"Follows:" text) plus the older table-based full/teaser email layouts - kept, but no longer the default email (see `email_render.py`).
- `email_render.py` - the default email: mobile-first, single-column by default, with side-by-side sections/ticker as a progressive enhancement (the "fluid hybrid" technique) that degrades safely in any client, including the Gmail app with no `<style>` support.
- `webpage.py` - the web edition: one self-contained HTML page (inline CSS, Google Fonts links) built from the same front-page shape as the email, saved alongside it under `digests/` (`DIGEST_DELIVERY=local` only) and optionally published publicly (see `DIGEST_WEB_BUCKET` above).
- `market_data.py` - closing-session market figures (via `yfinance`), fetched by code so the ticker is reliable every day - see a topic's `data.ticker` in `config.yaml`.
- `sports_data.py` - finished-event sport results (F1 via the Jolpica API; football via football-data.org, optional) - see a topic's `data.sports` in `config.yaml`.
- `design/` - a design-tool mockup of the web edition's look - reference only, not runtime code.
- `tests/` - `test_db.py` (standalone script, run directly) plus pytest suites: `test_email_render.py`, `test_data_modules.py`, `test_fixture_end_to_end.py`.
- `config.prod.yaml` - committed, non-secret production config baked into the Docker image.
- `Dockerfile` / `.dockerignore` - container image for running the job on a schedule. Not deployed anywhere yet.

## Docker

```
docker build -t news-digest .
docker run --rm --env-file .env -e DIGEST_STORAGE=local news-digest --fixture
```

The image runs as a non-root user, uses `config.prod.yaml` (`DIGEST_CONFIG=config.prod.yaml`), and defaults to `DIGEST_STORAGE=gcs` with `DIGEST_DB=/tmp/digest.db`. The entrypoint is fixed (`python digest.py`) with a default arg of `--send` - a real email send - so `docker run news-digest` alone sends for real; pass different args after the image name (as above, to `--fixture`, free and instant) to override just that, without repeating "python digest.py". The storage backend is also overridden to `local` in the example above, since there's no real GCS bucket to sync against. Run `docker run --rm --env-file .env news-digest --check` (or `python digest.py --check` locally) to validate config and required env vars - including GCS bucket reachability when `DIGEST_STORAGE=gcs` - without any model, tool, or email calls. This split (`ENTRYPOINT`/`CMD` rather than one `CMD`) is also what lets Cloud Run jobs override the args per-execution without touching the image.

## Tests

```
python tests/test_db.py
pytest -q
```

`test_db.py` is self-contained (no network access, no real `digest.db` touched) and prints `all tests passed`. The pytest suites mock every external call (yfinance, Jolpica, football-data.org) - no network access either.

## Roadmap

- FastAPI + React UI
- MCP server wrapping the tools, for follow-up Q&A
- An `s3` storage backend and a `webhook` delivery backend
- Actually deploy the container somewhere on a schedule (Cloud Run Jobs + Cloud Scheduler, most likely)
