"""agent_loop.py - the model-facing agent loop.

The model gets a request plus a menu of tools (schemas). Each round it either
answers (stop_reason == "end_turn") or asks for tools (stop_reason == "tool_use").
We run whatever it asks for, send the results back, and go round again.
"""
from datetime import datetime, timezone

import anthropic

from pipeline.front_page_schema import parse_digest
from pipeline.system_prompt import SYSTEM
from registry import run_tool, schemas
from render.newsletter_render import LONDON_TZ

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 15      # hard stop so a confused run can't loop (and bill) forever -
                    # raised from 10: the research plan needs more tool rounds
MAX_TOKENS = 6000   # a full multi-topic JSON digest can run long; 2500 was too tight


def build_request(config: dict, history: list[dict]) -> str:
    now_london = datetime.now(LONDON_TZ)
    now_utc = datetime.now(timezone.utc)
    today = now_london.strftime("%A %d %B %Y")
    topics = "\n".join(
        f"- {t['name']} (focus: {t['focus']}; commentary: {t['commentary']})"
        for t in config["topics"]
    )
    sites = "\n".join(f"- {s}" for s in config["sites"])

    general_news = ""
    if config.get("general_news"):
        general_news = (
            f"\n\nGeneral news (always include): {config['general_focus']}. Use "
            f"topic labels 'World' for major global news and 'Worth knowing' "
            f"for interesting or unexpected stories. Search broadly (for "
            f"example 'top news today', 'world news') in addition to the "
            f"topic searches."
        )

    if history:
        told_lines = "\n".join(
            f"- id {h['id']} | {h['told_on']} | {h['topic']} | {h['headline']} | "
            f"{h['url']} | {h['summary'][:120]}"
            for h in history
        )
    else:
        told_lines = "(none)"

    return (
        f"Today is {today} (Europe/London). Current time: "
        f"{now_utc.strftime('%H:%M')} UTC / {now_london.strftime('%H:%M %Z')}. "
        f"Use this to judge whether an event has actually finished - do not assume "
        f"something scheduled for today has already happened. The reader is in London; "
        f"report markets and sport as of the most recent COMPLETED session or event, "
        f"never an in-progress or pre-market one.\n\n"
        f"Build my digest from roughly the last {config['lookback_days']} days.\n\n"
        f"Topics:\n{topics}{general_news}\n\n"
        f"Sites to check:\n{sites}\n\n"
        f"Already told (last {config['history_days']} days):\n{told_lines}"
    )


def run_agent(config: dict, history: list[dict]) -> tuple[str, bool, dict, list[dict]]:
    """Run the tool-use loop. Returns (final_text, hit_max_turns, usage,
    tool_log) - tool_log is every tool call and its raw result, in order,
    for the run archive (see digest.py)."""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": build_request(config, history)}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    tool_log = []

    for turn in range(1, MAX_TURNS + 1):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=schemas(),
            messages=messages,
        )
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens

        # Replay the model's own turn into the transcript (the API is stateless).
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "max_tokens":
            print("[warning] output was cut off; raise MAX_TOKENS")

        if resp.stop_reason != "tool_use":
            break  # model gave its final answer

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                args = dict(block.input)
                if block.name == "read_feed":
                    args["hours"] = config["lookback_days"] * 24
                elif block.name == "search_web":
                    args["days"] = config["lookback_days"]
                print(f"[turn {turn}] {block.name}({args})")
                output = run_tool(block.name, args)
                tool_log.append({"tool": block.name, "args": args, "result": output})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,  # must match the request it answers
                    "content": output,
                })
        # Tool results go back as a *user* turn.
        messages.append({"role": "user", "content": results})
    else:
        return f"Stopped after {MAX_TURNS} turns without a final answer.", True, usage, tool_log

    return "".join(b.text for b in resp.content if b.type == "text"), False, usage, tool_log
