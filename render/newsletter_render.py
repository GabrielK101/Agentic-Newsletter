"""newsletter_render.py - thin facade over the split-out render modules.

This module used to hold everything: text/date utilities, the "web
edition" HTML-table renderer, and the teaser-email renderer. It's now
split into:
  - summary_text.py: text/date/kicker/summary utilities (LONDON_TZ,
    safe_url, format_relative_date, kicker_parts, follows_text,
    sentence_ends, clamp_summary, clean_summary, ...)
  - web_edition_render.py: the main front-page renderer (render_html,
    render_text, and the band/hero/grid/brief builders behind them)
  - teaser_render.py: the teaser email renderer (render_teaser_html,
    render_teaser_text)

Everything importable from here before the split is still importable
from here - this module just re-exports it, so existing `from
newsletter_render import ...` call sites keep working unchanged.
"""
from render.summary_text import (
    LONDON_TZ,
    SUMMARY_CEILING_BRIEF,
    SUMMARY_CEILING_HERO,
    SUMMARY_CEILING_MAJOR,
    SUMMARY_WORD_FLOOR,
    clamp_summary,
    clean_summary,
    follows_text,
    format_relative_date,
    kicker_parts,
    safe_url,
    sentence_ends,
)
from render.web_edition_render import (
    CONTENT_WIDTH,
    MAX_CARDS,
    brief_list_band,
    footer_band,
    hero_band,
    render_html,
    render_text,
)
from render.teaser_render import render_teaser_html, render_teaser_text

__all__ = [
    "LONDON_TZ",
    "SUMMARY_CEILING_BRIEF",
    "SUMMARY_CEILING_HERO",
    "SUMMARY_CEILING_MAJOR",
    "SUMMARY_WORD_FLOOR",
    "clamp_summary",
    "clean_summary",
    "follows_text",
    "format_relative_date",
    "kicker_parts",
    "safe_url",
    "sentence_ends",
    "CONTENT_WIDTH",
    "MAX_CARDS",
    "brief_list_band",
    "footer_band",
    "hero_band",
    "render_html",
    "render_text",
    "render_teaser_html",
    "render_teaser_text",
]
