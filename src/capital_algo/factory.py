from __future__ import annotations

from pathlib import Path
from typing import Any

from capital_algo.backtest import BacktestEngine
from capital_algo.broker.capital import CapitalClient
from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.config.loader import load_json, resolve_config_path
from capital_algo.data.capital_provider import CapitalDataProvider
from capital_algo.data.resolver import HistoricalDataResolver
from capital_algo.data.sqlite_cache import SQLiteMarketDataCache
from capital_algo.env import load_dotenv
from capital_algo.instruments import load_instruments
from capital_algo.risk.manager import RiskManager
from capital_algo.sessions import load_sessions
from capital_algo.strategies.orb import ORBStrategy


def load_project(root: Path) -> dict[str, Any]:
    root = root.resolve()
    load_dotenv(root / ".env")
    app = load_json(root / "config" / "app.json")
    project = {
        "root": root,
        "app": app,
        "broker": load_json(resolve_config_path(root, app["broker_config"])),
        "data": load_json(resolve_config_path(root, app["data_config"])),
        "strategy": load_json(resolve_config_path(root, app["strategy_config"])),
        "risk": load_json(resolve_config_path(root, app.get("risk_config", "config/risk.json"))),
        "instruments": load_json(resolve_config_path(root, app.get("instruments_config", "config/instruments.json"))),
        "sessions": load_json(resolve_config_path(root, app.get("sessions_config", "config/sessions.json"))),
        "backtest": load_json(resolve_config_path(root, app.get("backtest_config", "config/backtest.json"))),
    }
    return project


def create_capital_data_provider(project: dict[str, Any]) -> CapitalDataProvider:
    broker_config = project["broker"]
    capital_data_config_path = project["data"].get("fallback_data_config", "config/data/capital.json")
    capital_data_config = load_json(resolve_config_path(project["root"], capital_data_config_path))
    client = CapitalClient(
        environment=broker_config.get("environment", "demo"),
        timeout_seconds=int(broker_config.get("request_timeout_seconds", 20)),
        max_retries=int(broker_config.get("max_retries", 3)),
    )
    instruments = load_instruments(project["instruments"])
    provider = CapitalDataProvider(
        client,
        instruments,
        default_timeframe=capital_data_config.get("default_timeframe", "MINUTE"),
        max_points_per_request=int(capital_data_config.get("max_points_per_request", 1000)),
    )
    provider.connect()
    return provider


def create_data_resolver(
    project: dict[str, Any],
    connect_fallback: bool,
    fetch_policy_override: str | None = None,
) -> HistoricalDataResolver:
    data_config = project["data"]
    cache_path = resolve_config_path(project["root"], data_config["historical_store"]["path"])
    cache = SQLiteMarketDataCache(cache_path)
    fallback = create_capital_data_provider(project) if connect_fallback else None
    return HistoricalDataResolver(
        cache=cache,
        fallback_provider=fallback,
        provider_name=data_config.get("fallback_data_provider", "capital"),
        fetch_policy=fetch_policy_override or data_config.get("fetch_policy", "cache_first"),
        allow_api_fetch_for_missing_data=bool(data_config.get("allow_api_fetch_for_missing_data", True)),
        max_points_per_request=int(load_json(resolve_config_path(project["root"], data_config.get("fallback_data_config", "config/data/capital.json"))).get("max_points_per_request", 1000)),
    )


def create_backtest_engine(project: dict[str, Any], connect_fallback: bool) -> BacktestEngine:
    if project["app"]["active_strategy"] != "orb":
        raise ValueError(f"Unsupported strategy: {project['app']['active_strategy']}")
    sessions = load_sessions(project["sessions"])
    strategy_config = project["strategy"]
    session = sessions[strategy_config["session_name"]]
    resolver = create_data_resolver(project, connect_fallback=connect_fallback)
    broker = SimulatedBroker(
        starting_balance=float(project["backtest"]["starting_balance"]),
        currency=project["backtest"].get("account_currency", "USD"),
        execution_config=project["backtest"],
    )
    report_directory = resolve_config_path(project["root"], project["backtest"].get("report_directory", "reports"))
    return BacktestEngine(
        data_resolver=resolver,
        strategy=ORBStrategy(),
        session=session,
        risk_manager=RiskManager(project["risk"]),
        broker=broker,
        report_directory=report_directory,
        config_snapshot={
            "app": project["app"],
            "strategy": project["strategy"],
            "risk": project["risk"],
            "backtest": project["backtest"],
        },
        close_at_end=bool(strategy_config.get("close_at_session_end", True)),
    )
