from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from capital_algo.broker.capital import CapitalAPIError, CapitalClient
from capital_algo.batch import BatchBacktestRunner, load_batch_config
from capital_algo.config.validation import validate_project_config
from capital_algo.data.csv_io import export_candles, import_candles
from capital_algo.data.sqlite_cache import SQLiteMarketDataCache
from capital_algo.env import load_dotenv
from capital_algo.factory import create_backtest_engine, create_data_resolver, load_project
from capital_algo.config.loader import load_json, resolve_config_path
from capital_algo.asset_mean_reversion_backtest import run_cached_asset_mean_reversion_backtest
from capital_algo.forex_pullback_backtest import run_cached_forex_pullback_backtest
from capital_algo.live.runner import ForexPullbackLiveRunner, MultiStrategyLiveRunner
from capital_algo.notifications import TelegramNotificationError, TelegramNotifier


def main() -> int:
    parser = argparse.ArgumentParser(prog="capital-algo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config")
    validate_parser.add_argument("--root", default=".", help="Project root directory")

    auth_parser = subparsers.add_parser("validate-capital-auth")
    auth_parser.add_argument("--root", default=".", help="Project root directory")

    telegram_parser = subparsers.add_parser("test-telegram")
    telegram_parser.add_argument("--root", default=".", help="Project root directory")
    telegram_parser.add_argument("--telegram-config", default="config/notifications/telegram.json")

    fetch_parser = subparsers.add_parser("fetch-data")
    fetch_parser.add_argument("--root", default=".", help="Project root directory")
    fetch_parser.add_argument("--symbol", required=True)
    fetch_parser.add_argument("--timeframe", default="MINUTE")
    fetch_parser.add_argument("--start", required=True, help="UTC start, e.g. 2026-01-01T13:30:00Z")
    fetch_parser.add_argument("--end", required=True, help="UTC end, e.g. 2026-01-01T20:00:00Z")
    fetch_parser.add_argument("--refresh", action="store_true", help="Refetch requested range and upsert cache")

    backtest_parser = subparsers.add_parser("run-backtest")
    backtest_parser.add_argument("--root", default=".", help="Project root directory")
    backtest_parser.add_argument("--symbol", default=None)
    backtest_parser.add_argument("--timeframe", default=None)
    backtest_parser.add_argument("--start", required=True, help="UTC start, e.g. 2026-01-01T13:30:00Z")
    backtest_parser.add_argument("--end", required=True, help="UTC end, e.g. 2026-01-01T20:00:00Z")
    backtest_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not connect to Capital.com; fail if cache is incomplete",
    )

    export_parser = subparsers.add_parser("export-csv")
    export_parser.add_argument("--root", default=".", help="Project root directory")
    export_parser.add_argument("--symbol", required=True)
    export_parser.add_argument("--timeframe", default="MINUTE")
    export_parser.add_argument("--start", required=True)
    export_parser.add_argument("--end", required=True)
    export_parser.add_argument("--output", required=True)

    import_parser = subparsers.add_parser("import-csv")
    import_parser.add_argument("--root", default=".", help="Project root directory")
    import_parser.add_argument("--input", required=True)

    batch_parser = subparsers.add_parser("run-batch")
    batch_parser.add_argument("--root", default=".", help="Project root directory")
    batch_parser.add_argument("--batch-config", default="config/batches/fx_orb_15m.json")
    batch_parser.add_argument("--start", required=True)
    batch_parser.add_argument("--end", required=True)
    batch_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not connect to Capital.com; fail if cache is incomplete",
    )
    batch_parser.add_argument("--refresh", action="store_true", help="Refetch all requested windows and upsert cache")

    pullback_parser = subparsers.add_parser("run-forex-pullback-backtest")
    pullback_parser.add_argument("--root", default=".", help="Project root directory")
    pullback_parser.add_argument("--symbols", default=None, help="Comma-separated symbols. Default: all cached forex pairs")
    pullback_parser.add_argument("--start", default=None, help="UTC start. Default: earliest cached candle")
    pullback_parser.add_argument("--end", default=None, help="UTC end. Default: latest cached candle")
    pullback_parser.add_argument("--strategy-config", default="config/strategies/forex_pullback_scalper.json")
    pullback_parser.add_argument("--report-name", default=None)
    pullback_parser.add_argument("--strict-spread", action="store_true", help="Reject missing spread instead of allowing cached candles without spread")
    pullback_parser.add_argument("--enable-news-filter", action="store_true", help="Enable news blackout filter")
    pullback_parser.add_argument("--trailing", action="store_true", help="Enable trailing stop from backtest execution config")
    pullback_parser.add_argument("--trailing-activation-r", type=float, default=0.5)
    pullback_parser.add_argument("--trailing-distance-r", type=float, default=0.5)

    asset_mr_parser = subparsers.add_parser("run-asset-mean-reversion-backtest")
    asset_mr_parser.add_argument("--root", default=".", help="Project root directory")
    asset_mr_parser.add_argument("--symbols", default=None, help="Comma-separated symbols. Default: strategy config symbols")
    asset_mr_parser.add_argument("--start", default=None, help="UTC start. Default: earliest cached candle")
    asset_mr_parser.add_argument("--end", default=None, help="UTC end. Default: latest cached candle")
    asset_mr_parser.add_argument("--strategy-config", default="config/strategies/btc_gold_mean_reversion.json")
    asset_mr_parser.add_argument("--report-name", default=None)
    asset_mr_parser.add_argument("--trailing", action="store_true", help="Enable trailing stop from backtest execution config")
    asset_mr_parser.add_argument("--trailing-activation-r", type=float, default=0.5)
    asset_mr_parser.add_argument("--trailing-distance-r", type=float, default=0.5)

    live_parser = subparsers.add_parser("run-forex-pullback-live")
    live_parser.add_argument("--root", default=".", help="Project root directory")
    live_parser.add_argument("--live-config", default="config/live.json")
    live_parser.add_argument("--once", action="store_true", help="Process one polling iteration and exit")
    live_parser.add_argument("--max-iterations", type=int, default=None)

    multi_live_parser = subparsers.add_parser("run-multi-strategy-live")
    multi_live_parser.add_argument("--root", default=".", help="Project root directory")
    multi_live_parser.add_argument("--live-config", default="config/live_multi_demo.json")
    multi_live_parser.add_argument("--once", action="store_true", help="Process one polling iteration and exit")
    multi_live_parser.add_argument("--max-iterations", type=int, default=None)

    args = parser.parse_args()

    if args.command == "validate-config":
        result = validate_project_config(Path(args.root))
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        for error in result.errors:
            print(f"ERROR: {error}")
        if result.ok:
            print("Config validation passed.")
            return 0
        return 1

    if args.command == "validate-capital-auth":
        root = Path(args.root).resolve()
        load_dotenv(root / ".env")
        project = load_project(root)
        client = CapitalClient(
            environment=project["broker"].get("environment", "demo"),
            timeout_seconds=int(project["broker"].get("request_timeout_seconds", 20)),
            max_retries=int(project["broker"].get("max_retries", 3)),
        )
        try:
            client.connect()
            snapshot = client.get_account_snapshot()
        except CapitalAPIError as exc:
            print(f"Capital.com auth failed: {exc}")
            return 1
        print(f"Capital.com auth passed: account={snapshot.account_id} currency={snapshot.currency}")
        return 0

    if args.command == "test-telegram":
        root = Path(args.root).resolve()
        load_dotenv(root / ".env")
        config = load_json(resolve_config_path(root, args.telegram_config))
        try:
            TelegramNotifier(config).send_test()
        except TelegramNotificationError as exc:
            print(f"Telegram test failed: {exc}")
            return 1
        print("Telegram test passed.")
        return 0

    if args.command == "fetch-data":
        project = load_project(Path(args.root))
        resolver = create_data_resolver(
            project,
            connect_fallback=True,
            fetch_policy_override="refresh" if args.refresh else None,
        )
        start_utc = _parse_utc(args.start)
        end_utc = _parse_utc(args.end)
        try:
            candles = resolver.get_candles(args.symbol, args.timeframe, start_utc, end_utc)
        except CapitalAPIError as exc:
            print(f"Capital.com data fetch failed: {exc}")
            return 1
        print(f"Data ready: {len(candles)} candles for {args.symbol} {args.timeframe}")
        return 0

    if args.command == "run-backtest":
        project = load_project(Path(args.root))
        symbol = args.symbol or project["backtest"].get("default_symbol")
        timeframe = args.timeframe or project["backtest"].get("default_timeframe", "MINUTE")
        engine = create_backtest_engine(project, connect_fallback=not args.cache_only)
        try:
            result = engine.run(symbol, timeframe, _parse_utc(args.start), _parse_utc(args.end))
        except CapitalAPIError as exc:
            print(f"Capital.com data fetch failed: {exc}")
            return 1
        print(f"Backtest complete: trades={result.trade_count} rejected={result.rejected_signal_count}")
        print(f"Net profit: {result.metrics['net_profit']:.2f}")
        print(f"Report: {result.report_directory}")
        return 0

    if args.command == "export-csv":
        project = load_project(Path(args.root))
        cache = _cache_from_project(project)
        data_provider = project["data"].get("fallback_data_provider", "capital")
        candles = cache.get_candles(
            data_provider,
            args.symbol,
            args.timeframe,
            _parse_utc(args.start),
            _parse_utc(args.end),
        )
        export_candles(Path(args.output), candles)
        print(f"Exported {len(candles)} candles to {args.output}")
        return 0

    if args.command == "import-csv":
        project = load_project(Path(args.root))
        cache = _cache_from_project(project)
        cache.initialize()
        candles = import_candles(Path(args.input))
        cache.upsert_candles(candles)
        grouped = defaultdict(list)
        for candle in candles:
            grouped[(candle.provider, candle.instrument, candle.timeframe)].append(candle)
        for (provider, instrument, timeframe), group in grouped.items():
            timestamps = [candle.timestamp_utc for candle in group]
            cache.record_fetch(
                provider,
                instrument,
                timeframe,
                min(timestamps),
                max(timestamps),
                "success",
                len(group),
                notes=f"csv import: {args.input}",
            )
        print(f"Imported {len(candles)} candles from {args.input}")
        return 0

    if args.command == "run-batch":
        project = load_project(Path(args.root))
        batch_config = load_batch_config(project["root"], args.batch_config)
        try:
            resolver = create_data_resolver(
                project,
                connect_fallback=not args.cache_only,
                fetch_policy_override="refresh" if args.refresh else "cache_only" if args.cache_only else None,
            )
            runner = BatchBacktestRunner(
                project,
                resolver,
                batch_config,
                _parse_utc(args.start),
                _parse_utc(args.end),
            )
            report_directory = runner.run()
        except CapitalAPIError as exc:
            print(f"Capital.com data fetch failed: {exc}")
            return 1
        print(f"Batch backtest complete: {report_directory}")
        return 0

    if args.command == "run-forex-pullback-backtest":
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] if args.symbols else None
        trailing_stop = {
            "enabled": bool(args.trailing),
            "activation_r": args.trailing_activation_r,
            "distance_r": args.trailing_distance_r,
        }
        result = run_cached_forex_pullback_backtest(
            root=Path(args.root),
            symbols=symbols,
            start_utc=_parse_utc(args.start) if args.start else None,
            end_utc=_parse_utc(args.end) if args.end else None,
            strategy_config_path=args.strategy_config,
            allow_missing_spread=not args.strict_spread,
            disable_news_filter=not args.enable_news_filter,
            trailing_stop=trailing_stop,
            report_name=args.report_name,
        )
        total_trades = sum(int(row.get("trade_count", 0)) for row in result.rows)
        net_profit = sum(float(row.get("net_profit", 0.0)) for row in result.rows)
        print(f"Forex pullback backtest complete: pairs={len(result.rows)} trades={total_trades}")
        print(f"Net profit: {net_profit:.2f}")
        print(f"Report: {result.report_directory}")
        return 0

    if args.command == "run-asset-mean-reversion-backtest":
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] if args.symbols else None
        trailing_stop = {
            "enabled": bool(args.trailing),
            "activation_r": args.trailing_activation_r,
            "distance_r": args.trailing_distance_r,
        }
        result = run_cached_asset_mean_reversion_backtest(
            root=Path(args.root),
            symbols=symbols,
            start_utc=_parse_utc(args.start) if args.start else None,
            end_utc=_parse_utc(args.end) if args.end else None,
            strategy_config_path=args.strategy_config,
            trailing_stop=trailing_stop,
            report_name=args.report_name,
        )
        total_trades = sum(int(row.get("trade_count", 0)) for row in result.rows)
        net_profit = sum(float(row.get("net_profit", 0.0)) for row in result.rows)
        print(f"Asset mean-reversion backtest complete: symbols={len(result.rows)} trades={total_trades}")
        print(f"Net profit: {net_profit:.2f}")
        print(f"Report: {result.report_directory}")
        return 0

    if args.command == "run-forex-pullback-live":
        runner = ForexPullbackLiveRunner(Path(args.root), args.live_config)
        result = runner.run(once=args.once, max_iterations=args.max_iterations)
        print(
            "Forex pullback live runner complete: "
            f"iterations={result.iterations} evaluated={result.evaluated} "
            f"signals={result.signals} submitted={result.orders_submitted} rejected={result.orders_rejected}"
        )
        print(f"State: {result.state_path}")
        print(f"Log: {result.log_path}")
        return 0

    if args.command == "run-multi-strategy-live":
        runner = MultiStrategyLiveRunner(Path(args.root), args.live_config)
        result = runner.run(once=args.once, max_iterations=args.max_iterations)
        print(
            "Multi-strategy live runner complete: "
            f"iterations={result.iterations} evaluated={result.evaluated} "
            f"signals={result.signals} submitted={result.orders_submitted} rejected={result.orders_rejected}"
        )
        print(f"State: {result.state_path}")
        print(f"Log: {result.log_path}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_from_project(project: dict) -> SQLiteMarketDataCache:
    data_config = project["data"]
    path = resolve_config_path(project["root"], data_config["historical_store"]["path"])
    cache = SQLiteMarketDataCache(path)
    cache.initialize()
    return cache
