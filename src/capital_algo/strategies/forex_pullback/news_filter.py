from __future__ import annotations

from datetime import timedelta

from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, NewsEvent


def is_news_blackout(context: ForexPullbackContext, config: dict) -> tuple[bool, str]:
    news_config = config["news_blackout"]
    if not news_config.get("enabled", True):
        return False, ""
    if not context.news_events:
        if config["filters"].get("require_news_data", False):
            return True, "News filter requires events but none were provided"
        return False, ""

    before = timedelta(minutes=int(news_config.get("minutes_before", 15)))
    after = timedelta(minutes=int(news_config.get("minutes_after", 15)))
    required_impact = str(news_config.get("impact", "high")).lower()
    for event in context.news_events:
        if not _event_applies(event, context.symbol):
            continue
        if event.impact.lower() != required_impact:
            continue
        if event.timestamp_utc - before <= context.current_time <= event.timestamp_utc + after:
            return True, f"High-impact news blackout active: {event.title or event.symbol or event.currency}"
    return False, ""


def _event_applies(event: NewsEvent, symbol: str) -> bool:
    if event.symbol and event.symbol == symbol:
        return True
    if event.currency and event.currency in symbol:
        return True
    return event.symbol is None and event.currency is None

