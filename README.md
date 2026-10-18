# Agentic Newsletter

An agent that builds a personalised daily news digest from RSS feeds and web search, using a hand-rolled tool-use loop on the Anthropic API.

## Setup (Windows)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`.

## Running

```
python digest.py
```

## File structure

- `registry.py` - the `@tool` decorator, tool registry, and the `run_tool`/`schemas` dispatcher used by the agent loop.
- `tools.py` - the tools themselves: `read_feed`, `find_feed`, `fetch_article`, `search_web`.
- `digest.py` - the agent loop: calls the model with the tool schemas, executes whatever tools it asks for, and returns the finished digest.

## Roadmap

- SQLite memory, so the agent can report deltas instead of repeating itself
- `config.yaml` for sources/interests/depth-per-topic, instead of hardcoded values
- FastAPI + React UI
- MCP server wrapping the tools, for follow-up Q&A
