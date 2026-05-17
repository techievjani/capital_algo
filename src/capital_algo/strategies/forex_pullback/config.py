from __future__ import annotations

from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "symbols": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
    "session": {
        "enabled": False,
        "start": "00:00",
        "end": "23:59",
    },
    "indicators": {
        "ema_15m": 50,
        "ema_5m": 20,
        "ema_1m_fast": 9,
        "ema_1m_slow": 20,
        "adx_period": 14,
        "adx_min": 20,
    },
    "filters": {
        "vwap_chop_lookback_minutes": 15,
        "max_vwap_crosses": 3,
        "allow_missing_spread": False,
        "require_news_data": False,
    },
    "candle_quality": {
        "min_body_percent": 55,
        "close_position_percent": 30,
        "max_dominant_wick_percent": 45,
    },
    "lookbacks": {
        "swing": 5,
        "impulse": 8,
        "pullback": 6,
    },
    "max_spread": {
        "EURUSD": 1.2,
        "GBPUSD": 1.8,
        "USDJPY": 1.5,
        "XAUUSD": 30,
    },
    "pip_size": {
        "EURUSD": 0.0001,
        "GBPUSD": 0.0001,
        "USDJPY": 0.01,
        "XAUUSD": 0.1,
    },
    "min_impulse_pips": {
        "EURUSD": 5,
        "GBPUSD": 8,
        "USDJPY": 6,
        "XAUUSD": 100,
    },
    "pullback_buffer_pips": {
        "EURUSD": 1.5,
        "GBPUSD": 2,
        "USDJPY": 2,
        "XAUUSD": 15,
    },
    "stop_buffer_pips": {
        "EURUSD": 1,
        "GBPUSD": 1.5,
        "USDJPY": 1.5,
        "XAUUSD": 10,
    },
    "target_r": 1.0,
    "news_blackout": {
        "enabled": True,
        "minutes_before": 15,
        "minutes_after": 15,
        "impact": "high",
    },
}


def merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_copy(DEFAULT_CONFIG)
    if config:
        _deep_update(merged, config)
    return merged


def symbol_value(config: dict[str, Any], section: str, symbol: str) -> float:
    values = config[section]
    if symbol not in values:
        raise KeyError(f"Missing {section} config for {symbol}")
    return float(values[symbol])


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return list(value)
    return value


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value

