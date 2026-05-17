from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capital_algo.config.loader import ConfigError, load_json, resolve_config_path


VALID_MODES = {"backtest", "demo", "paper", "live"}
VALID_FETCH_POLICIES = {"cache_first", "cache_only", "refresh"}
VALID_HISTORICAL_STORES = {"sqlite"}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_project_config(root: Path) -> ValidationResult:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        app = load_json(root / "config" / "app.json")
    except ConfigError as exc:
        return ValidationResult(errors=[str(exc)])

    mode = _required_str(app, "mode", errors, "config/app.json")
    broker = _required_str(app, "broker", errors, "config/app.json")
    data_provider = _required_str(app, "data_provider", errors, "config/app.json")
    active_strategy = _required_str(app, "active_strategy", errors, "config/app.json")

    if mode and mode not in VALID_MODES:
        errors.append(f"config/app.json: mode must be one of {sorted(VALID_MODES)}")

    broker_config = _load_referenced_config(root, app, "broker_config", errors)
    data_config = _load_referenced_config(root, app, "data_config", errors)
    strategy_config = _load_referenced_config(root, app, "strategy_config", errors)
    risk = _load_referenced_or_default(root, app, "risk_config", root / "config" / "risk.json", errors)
    instruments = _load_referenced_or_default(
        root,
        app,
        "instruments_config",
        root / "config" / "instruments.json",
        errors,
    )
    sessions = _load_referenced_or_default(root, app, "sessions_config", root / "config" / "sessions.json", errors)
    backtest = _load_referenced_or_default(root, app, "backtest_config", root / "config" / "backtest.json", errors)

    if broker_config is not None:
        _validate_environment("broker_config", broker_config, mode, errors, warnings)
    if data_config is not None:
        _validate_data_config(root, data_provider, data_config, errors, warnings)
    if strategy_config is not None:
        _validate_strategy_config(active_strategy, strategy_config, errors)
    if risk is not None:
        _validate_risk_config(mode, risk, errors)
    if instruments is not None and broker:
        _validate_instruments(broker, instruments, errors)
    if sessions is not None:
        _validate_sessions(sessions, errors)
    if backtest is not None:
        _validate_backtest_config(backtest, errors)

    return ValidationResult(errors=errors, warnings=warnings)


def _load_referenced_config(
    root: Path,
    source: dict[str, Any],
    key: str,
    errors: list[str],
) -> dict[str, Any] | None:
    raw_path = _required_str(source, key, errors, "config/app.json")
    if not raw_path:
        return None
    return _load_required_file(resolve_config_path(root, raw_path), errors)


def _load_required_file(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except ConfigError as exc:
        errors.append(str(exc))
        return None


def _load_referenced_or_default(
    root: Path,
    source: dict[str, Any],
    key: str,
    default_path: Path,
    errors: list[str],
) -> dict[str, Any] | None:
    raw_path = source.get(key)
    if isinstance(raw_path, str) and raw_path:
        return _load_required_file(resolve_config_path(root, raw_path), errors)
    return _load_required_file(default_path, errors)


def _required_str(
    data: dict[str, Any],
    key: str,
    errors: list[str],
    label: str,
) -> str | None:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: required string field missing or empty: {key}")
        return None
    return value


def _validate_environment(
    label: str,
    config: dict[str, Any],
    mode: str | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    environment = config.get("environment")
    if not isinstance(environment, str) or not environment:
        errors.append(f"{label}: environment is required")
        return

    if mode == "live" and environment != "live":
        errors.append(f"{label}: live mode requires live environment")
    if mode in {"demo", "paper"} and environment == "live":
        errors.append(f"{label}: {mode} mode cannot use live environment")
    if mode == "backtest" and environment == "live":
        warnings.append(f"{label}: backtest is configured with a live environment")


def _validate_data_config(
    root: Path,
    data_provider: str | None,
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    if data_provider != "cached":
        return

    historical_store = config.get("historical_store")
    if not isinstance(historical_store, dict):
        errors.append("data_config: historical_store object is required")
        return

    store_type = historical_store.get("type")
    if store_type not in VALID_HISTORICAL_STORES:
        errors.append(f"data_config: historical_store.type must be one of {sorted(VALID_HISTORICAL_STORES)}")

    store_path = historical_store.get("path")
    if not isinstance(store_path, str) or not store_path:
        errors.append("data_config: historical_store.path is required")

    fetch_policy = config.get("fetch_policy")
    if fetch_policy not in VALID_FETCH_POLICIES:
        errors.append(f"data_config: fetch_policy must be one of {sorted(VALID_FETCH_POLICIES)}")

    fallback_config = config.get("fallback_data_config")
    allow_fetch = config.get("allow_api_fetch_for_missing_data")
    if allow_fetch is True and isinstance(fallback_config, str):
        fallback_path = resolve_config_path(root, fallback_config)
        if not fallback_path.exists():
            errors.append(f"data_config: fallback_data_config not found: {fallback_path}")
    elif allow_fetch is True:
        warnings.append("data_config: API fetch is allowed but fallback_data_config is not set")

    timestamp_timezone = config.get("timestamp_timezone")
    if timestamp_timezone != "UTC":
        errors.append("data_config: timestamp_timezone must be UTC")


def _validate_strategy_config(
    active_strategy: str | None,
    config: dict[str, Any],
    errors: list[str],
) -> None:
    strategy_id = config.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id:
        errors.append("strategy_config: strategy_id is required")
    if active_strategy == "orb":
        required = ["opening_range_minutes", "trade_direction", "stop_loss_mode"]
        for key in required:
            if key not in config:
                errors.append(f"strategy_config: ORB requires {key}")
        if config.get("trade_direction") not in {"long", "short", "both"}:
            errors.append("strategy_config: trade_direction must be long, short, or both")
        if not isinstance(config.get("opening_range_minutes"), int) or config.get("opening_range_minutes", 0) <= 0:
            errors.append("strategy_config: opening_range_minutes must be a positive integer")


def _validate_risk_config(mode: str | None, config: dict[str, Any], errors: list[str]) -> None:
    for key in ["account_risk_per_trade_pct", "max_daily_loss_pct"]:
        value = config.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            errors.append(f"config/risk.json: {key} must be a positive number")

    for key in ["max_open_positions", "max_trades_per_day"]:
        value = config.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"config/risk.json: {key} must be a positive integer")

    allow_live = config.get("allow_live_trading")
    if not isinstance(allow_live, bool):
        errors.append("config/risk.json: allow_live_trading must be boolean")
    if mode == "live" and allow_live is not True:
        errors.append("config/risk.json: live mode requires allow_live_trading=true")


def _validate_instruments(
    broker: str,
    config: dict[str, Any],
    errors: list[str],
) -> None:
    instruments = config.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        errors.append("config/instruments.json: instruments must be a non-empty list")
        return

    seen_symbols: set[str] = set()
    for index, instrument in enumerate(instruments):
        label = f"config/instruments.json: instruments[{index}]"
        if not isinstance(instrument, dict):
            errors.append(f"{label} must be an object")
            continue

        symbol = instrument.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            errors.append(f"{label}.symbol is required")
        elif symbol in seen_symbols:
            errors.append(f"{label}.symbol is duplicated: {symbol}")
        else:
            seen_symbols.add(symbol)

        brokers = instrument.get("brokers")
        if not isinstance(brokers, dict):
            errors.append(f"{label}.brokers must be an object")
            continue

        mapping = brokers.get(broker)
        if not isinstance(mapping, dict) or not mapping:
            errors.append(f"{label}.brokers must include selected broker: {broker}")
            continue

        if broker == "capital" and not mapping.get("epic"):
            errors.append(f"{label}.brokers.capital.epic is required")


def _validate_sessions(config: dict[str, Any], errors: list[str]) -> None:
    sessions = config.get("sessions")
    if not isinstance(sessions, dict) or not sessions:
        errors.append("config/sessions.json: sessions must be a non-empty object")
        return
    for name, session in sessions.items():
        label = f"config/sessions.json: sessions.{name}"
        if not isinstance(session, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in ["timezone", "open", "close"]:
            if not isinstance(session.get(key), str) or not session.get(key):
                errors.append(f"{label}.{key} is required")


def _validate_backtest_config(config: dict[str, Any], errors: list[str]) -> None:
    starting_balance = config.get("starting_balance")
    if not isinstance(starting_balance, (int, float)) or starting_balance <= 0:
        errors.append("config/backtest.json: starting_balance must be a positive number")
    report_directory = config.get("report_directory")
    if not isinstance(report_directory, str) or not report_directory:
        errors.append("config/backtest.json: report_directory is required")
