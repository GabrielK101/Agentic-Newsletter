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
  - `DIGEST_ARCHIVE` - `true` to also upload each run's saved `.md`/`.json`/`.html` to `gs://<bucket>/digests/`. Defaults off.
  - Auth is Application Default Credentials only - no key files. On GCP compute this is automatic; locally, `gcloud auth application-default login`.
- `DIGEST_DELIVERY` - `local` (default: print + files under `digests/`) or `email` (requires `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and a recipient - see `DIGEST_TO` below).
- `DIGEST_TO` - who the email goes to. Overridable per-config with `recipient` in `config.yaml` (`DIGEST_TO` is the fallback if that's unset).

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
- `newsletter_render.py` - the HTML/text layout engine that turns stories into the rendered email.
- `webpage.py` - the web edition: one self-contained HTML page (inline CSS, Google Fonts links) built from the same front-page shape as the email, saved alongside it under `digests/` (`DIGEST_DELIVERY=local` only).
- `design/` - a design-tool mockup of the web edition's look - reference only, not runtime code.
- `tests/` - standalone test scripts, each runnable directly (no test runner required): `test_db.py`.
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
```

Both are self-contained (no network access, no real `digest.db` touched) and print `all tests passed` / the standard `unittest` summary on success.

## Roadmap

- FastAPI + React UI
- MCP server wrapping the tools, for follow-up Q&A
- An `s3` storage backend and a `webhook` delivery backend
- Actually deploy the container somewhere on a schedule (Cloud Run Jobs + Cloud Scheduler, most likely)
