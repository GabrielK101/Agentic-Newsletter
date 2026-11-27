"""markdown_render.py - the plain-markdown digest renderer.

Builds the front page (as prepared by front_page.prepare_front_page) into
the markdown string used for the local/dry-run output and as the plain-
text fallback. No I/O; pure string assembly.
"""


def render_digest(lead: dict | None, secondary: list[dict], sections: list[dict],
                   ticker: list[dict], scoreboard: list[dict], sources: list[dict],
                   disclosure: str | None, history: list[dict]) -> str:
    """Build the front page as markdown: lead, then secondary stories,
    then each section's briefs, then markets/scoreboard/sources/disclosure
    if present."""
    history_by_id = {h["id"]: h for h in history}

    def _update_line(item: dict) -> str | None:
        update_of = item.get("update_of")
        if update_of is None:
            return None
        prior = history_by_id.get(update_of)
        return f"(follows: {prior['headline']})" if prior else None

    lines = []

    if lead is not None:
        lines.append(f"# {lead['headline']}")
        if lead.get("dek"):
            lines.append(f"*{lead['dek']}*")
        update_line = _update_line(lead)
        if update_line:
            lines.append(update_line)
        if lead.get("body"):
            lines.append(lead["body"])
        if lead.get("sources"):
            lines.append(f"Sources: {', '.join(lead['sources'])}")
        lines.append(lead["url"])
        lines.append("")

    if secondary:
        lines.append("## Also today\n")
        for item in secondary:
            lines.append(f"**{item['headline']}**")
            update_line = _update_line(item)
            if update_line:
                lines.append(update_line)
            if item.get("summary"):
                lines.append(item["summary"])
            lines.append(item["url"])
            lines.append("")

    for section in sections:
        if not section["briefs"]:
            continue
        lines.append(f"## {section['name']}\n")
        for brief in section["briefs"]:
            lines.append(f"**{brief['headline']}**")
            update_line = _update_line(brief)
            if update_line:
                lines.append(update_line)
            if brief.get("summary"):
                lines.append(brief["summary"])
            lines.append(brief["url"])
            lines.append("")

    if ticker:
        lines.append("## Markets\n")
        arrows = {"up": "^", "down": "v", "flat": "-"}
        for row in ticker:
            change = f" {row['change']}" if row.get("change") else ""
            arrow = arrows.get(row.get("direction"), "")
            lines.append(f"- {row['label']}: {row['value']}{change} {arrow}".rstrip())
        lines.append("")

    if scoreboard:
        lines.append("## Scoreboard\n")
        groups: dict[str, list[dict]] = {}
        for row in scoreboard:
            groups.setdefault(row.get("group", "Results"), []).append(row)
        for group, rows in groups.items():
            lines.append(f"**{group}**")
            for row in rows:
                prefix = f"{row['label']}: " if row.get("label") else ""
                lines.append(f"- {prefix}{row['line']}")
        lines.append("")

    if sources:
        lines.append("## Sources\n")
        for src in sources:
            lines.append(f"- {src['name']}" + (f" ({src['url']})" if src.get("url") else ""))
        lines.append("")

    if disclosure:
        lines.append(f"*{disclosure}*")

    return "\n".join(lines)
