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
- `DIGEST_DB` - path to the SQLite DB file. Defaults to `digest.db` next to `db.py`.
- `DIGEST_STORAGE` - `local` (default, no-op), `s3`, or `gcs` (the latter two are unimplemented stubs).
- `DIGEST_DELIVERY` - `local` (default: print + files under `digests/`), `email`, or `webhook` (the latter two are unimplemented stubs).

## Running

```
python digest.py
python digest.py --dry-run   # skip saving to the DB, still write files
```

## File structure

- `registry.py` - the `@tool` decorator, tool registry, and the `run_tool`/`schemas` dispatcher used by the agent loop.
- `tools.py` - the tools themselves: `read_feed`, `find_feed`, `fetch_article`, `search_web`.
- `digest.py` - the agent loop: calls the model with the tool schemas, executes whatever tools it asks for, parses and filters the result, and hands it off for delivery.
- `config.py` / `config.yaml` - loads and validates the run config (lookback window, history window, topics, sites).
- `db.py` - SQLite storage for past stories, used to dedupe and to report follow-ups.
- `storage.py` - syncs the DB file to/from a remote backend before/after a run (currently local-only; `s3`/`gcs` are stubs).
- `delivery.py` - delivers the finished digest (currently local-only: stdout + dated files under `digests/`; `email`/`webhook` are stubs).

## Roadmap

- FastAPI + React UI
- MCP server wrapping the tools, for follow-up Q&A
- Real `s3`/`gcs` storage backends and `email`/`webhook` delivery backends
