from __future__ import annotations

import csv
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from capital_algo.broker.capital import CapitalAPIError, CapitalBroker, CapitalClient
from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.config.loader import load_json, resolve_config_path
from capital_algo.data.sqlite_cache import SQLiteMarketDataCache
from capital_algo.factory import create_capital_data_provider, load_project
from capital_algo.instruments import load_instruments, broker_mapping
from capital_algo.live.notifications import LiveNotificationManager
from capital_algo.live.state import LiveState
from capital_algo.models import Candle, OrderType, Signal, TradeAction
from capital_algo.notifications import TelegramNotifier
from capital_algo.risk.manager import RiskManager
from capital_algo.strategies.asset_breakout import AssetBreakoutStrategy, BreakoutContext, BreakoutDirection
from capital_algo.strategies.forex_pullback import ForexPullbackContext, ForexTrendPullbackScalper, TradeDirection
from capital_algo.strategies.asset_mean_reversion import (
    AssetMeanReversionStrategy,
    MeanReversionContext,
    MeanReversionDirection,
)


@dataclass(frozen=True)
class LiveRunResult:
    iterations: int
    evaluated: int
    signals: int
    orders_submitted: int
    orders_rejected: int
    state_path: Path
    log_path: Path


class ForexPullbackLiveRunner:
    def __init__(self, root: Path, live_config_path: str = "config/live.json") -> None:
        self.root = root.resolve()
        self.project = load_project(self.root)
        self.live_config = load_json(resolve_config_path(self.root, live_config_path))
        self.strategy_config = load_json(resolve_config_path(self.root, self.live_config["strategy_config"]))
        self.symbols = list(self.live_config.get("symbols") or self.strategy_config["symbols"])
        self.strategy_config["symbols"] = self.symbols
        if self.live_config.get("require_spread", True):
            self.strategy_config.setdefault("filters", {})["allow_missing_spread"] = False
        self.state_path = resolve_config_path(self.root, self.live_config.get("state_path", "runtime/live_state.json"))
        self.log_directory = resolve_config_path(self.root, self.live_config.get("log_directory", "runtime/logs"))
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_directory / f"live_decisions_{datetime.now(timezone.utc):%Y%m%d}.csv"
        self.state = LiveState.load(self.state_path)
        self.strategy = ForexTrendPullbackScalper(self.strategy_config)
        self.risk_manager = RiskManager(self.project["risk"])
        self.cache = SQLiteMarketDataCache(resolve_config_path(self.root, self.project["data"]["historical_store"]["path"]))
        self.cache.initialize()
        self.provider_name = self.project["data"].get("fallback_data_provider", "capital")
        self.data_provider = None
        self.broker = self._create_broker()

    def run(self, once: bool = False, max_iterations: int | None = None) -> LiveRunResult:
        self._validate_gates()
        self._reconcile_open_positions()
        iterations = 0
        evaluated = 0
        signals = 0
        orders_submitted = 0
        orders_rejected = 0
        self._ensure_log_header()

        while True:
            iterations += 1
            self._reconcile_open_positions()
            for symbol in self.symbols:
                outcome = self._process_symbol(symbol)
                evaluated += int(outcome["evaluated"])
                signals += int(outcome["signal"])
                orders_submitted += int(outcome["submitted"])
                orders_rejected += int(outcome["rejected"])
            self.state.save(self.state_path)
            if once or (max_iterations is not None and iterations >= max_iterations):
                break
            time.sleep(float(self.live_config.get("poll_seconds", 20)))

        return LiveRunResult(iterations, evaluated, signals, orders_submitted, orders_rejected, self.state_path, self.log_path)

    def _process_symbol(self, symbol: str) -> dict[str, int]:
        candles_1m = self._load_recent_candles(symbol)
        if len(candles_1m) < 80:
            self._log(symbol, None, "skip", "insufficient_1m_candles")
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}

        latest = candles_1m[-1]
        latest_key = latest.timestamp_utc.isoformat()
        if self.state.last_processed_candle.get(symbol) == latest_key:
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}

        candles_5m = _aggregate(candles_1m, 5, "MINUTE_5")
        candles_15m = _aggregate(candles_1m, 15, "MINUTE_15")
        if len(candles_5m) < 80 or len(candles_15m) < 80:
            self.state.last_processed_candle[symbol] = latest_key
            self._log(symbol, latest, "skip", "insufficient_derived_candles")
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}

        self._update_paper_broker(symbol, latest)
        context = ForexPullbackContext(
            symbol=symbol,
            current_time=latest.timestamp_utc,
            candles_1m=candles_1m[-80:],
            candles_5m=candles_5m[-80:],
            candles_15m=candles_15m[-80:],
            current_spread=_spread_pips(latest, self.strategy_config, symbol),
            config={},
            news_events=[],
        )
        evaluation = self.strategy.evaluate(context)
        self.state.last_processed_candle[symbol] = latest_key
        if not evaluation.should_trade:
            reason = evaluation.rejection_reason.value if evaluation.rejection_reason else "no_signal"
            self._log(symbol, latest, "reject", reason)
            return {"evaluated": 1, "signal": 0, "submitted": 0, "rejected": 0}

        if self.state.last_signal_candle.get(symbol) == latest_key:
            self._log(symbol, latest, "reject", "duplicate_signal")
            return {"evaluated": 1, "signal": 0, "submitted": 0, "rejected": 0}

        signal = _evaluation_to_signal(evaluation)
        if len(self.broker.get_open_positions()) >= int(self.project["risk"].get("max_open_positions", 1)):
            self._log(symbol, latest, "risk_reject", "max_open_positions_reached")
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}
        self._restore_daily_risk_count(latest.timestamp_utc.date().isoformat())
        decision = self.risk_manager.evaluate(
            signal,
            self.broker.get_account_snapshot(),
            evaluation.entry_price or latest.close,
            trading_day=latest.timestamp_utc.date().isoformat(),
        )
        if not decision.approved or decision.order is None:
            self._log(symbol, latest, "risk_reject", decision.reason)
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

        order = replace(
            decision.order,
            metadata={
                **decision.order.metadata,
                "entry_price": evaluation.entry_price or latest.close,
            },
        )
        pending_key = f"{symbol}:{latest_key}"
        self.state.pending_orders[pending_key] = {
            "symbol": symbol,
            "candle_time": latest_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "action": order.action.value,
            "size": order.size,
            "entry_price": evaluation.entry_price or latest.close,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
        }
        self.state.save(self.state_path)
        result = self._submit_order(order, evaluation.entry_price or latest.close, latest.timestamp_utc.isoformat())
        if result.status.value == "FILLED":
            self._record_trade(latest.timestamp_utc.date().isoformat())
            self.state.last_signal_candle[symbol] = latest_key
            self.state.pending_orders.pop(pending_key, None)
            self.state.append_order_event(
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "event": "filled",
                    "symbol": symbol,
                    "broker_order_id": result.broker_order_id,
                    "candle_time": latest_key,
                    "action": order.action.value,
                    "size": order.size,
                    "entry_price": evaluation.entry_price or latest.close,
                    "stop_loss": order.stop_loss,
                    "take_profit": order.take_profit,
                }
            )
            self._reconcile_open_positions()
            self.state.save(self.state_path)
            self._log(symbol, latest, "submitted", signal.reason)
            return {"evaluated": 1, "signal": 1, "submitted": 1, "rejected": 0}

        self.state.pending_orders.pop(pending_key, None)
        self.state.append_order_event(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "rejected",
                "symbol": symbol,
                "candle_time": latest_key,
                "reason": result.rejection_reason or result.status.value,
            }
        )
        self.state.save(self.state_path)
        self._log(symbol, latest, "broker_reject", result.rejection_reason or result.status.value)
        return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

    def _load_recent_candles(self, symbol: str) -> list[Candle]:
        end = _latest_closed_minute(datetime.now(timezone.utc))
        start = end - timedelta(minutes=int(self.live_config.get("lookback_minutes", 1500)))
        if self.live_config.get("mode") in {"paper", "live"} and self.project["data"].get("allow_api_fetch_for_missing_data", True):
            provider = self._data_provider()
            candles = _fetch_recent_candles_chunked(provider, symbol, start, end)
            self.cache.upsert_candles(candles)
        return self.cache.get_candles(self.provider_name, symbol, "MINUTE", start, end)

    def _data_provider(self):
        if self.data_provider is None:
            self.data_provider = create_capital_data_provider(self.project)
        return self.data_provider

    def _create_broker(self):
        mode = self.live_config.get("mode", "paper")
        if mode == "paper":
            account = self.live_config.get("paper_account", {})
            execution_config = {"trailing_stop": self.live_config.get("trailing_stop", {})}
            return SimulatedBroker(
                starting_balance=float(account.get("starting_balance", 10000.0)),
                currency=account.get("currency", "USD"),
                execution_config=execution_config,
            )
        client = CapitalClient(
            environment=self.project["broker"].get("environment", "demo"),
            timeout_seconds=int(self.project["broker"].get("request_timeout_seconds", 20)),
            max_retries=int(self.project["broker"].get("max_retries", 3)),
        )
        broker = CapitalBroker(
            client,
            epic_by_symbol=_capital_epic_map(self.project),
            enable_order_placement=bool(self.live_config.get("order_execution", {}).get("enabled", False)),
            trailing_stop_config=self.live_config.get("trailing_stop", {}),
        )
        broker.connect()
        return broker

    def _submit_order(self, order, price: float, timestamp: str):
        if isinstance(self.broker, SimulatedBroker):
            return self.broker.submit_order_at_price(order, price, timestamp)
        return self.broker.submit_order(order)

    def _update_paper_broker(self, symbol: str, candle: Candle) -> None:
        if isinstance(self.broker, SimulatedBroker):
            self.broker.update_for_bar(symbol, candle.high, candle.low, candle.close, candle.timestamp_utc.isoformat())

    def _validate_gates(self) -> None:
        mode = self.live_config.get("mode", "paper")
        if mode not in {"paper", "demo", "live"}:
            raise RuntimeError("live_config.mode must be paper, demo, or live")
        execution = self.live_config.get("order_execution", {})
        if mode == "demo":
            if self.project["broker"].get("environment") != "demo":
                raise RuntimeError("Demo execution requires broker environment demo")
            if execution.get("allow_demo_orders") is not True or execution.get("enabled") is not True:
                raise RuntimeError("Demo execution requires order_execution.enabled and allow_demo_orders")
        if mode == "live":
            if self.project["broker"].get("environment") != "live":
                raise RuntimeError("Live mode requires broker environment live")
            if self.project["risk"].get("allow_live_trading") is not True:
                raise RuntimeError("Live mode requires risk.allow_live_trading=true")
            if execution.get("allow_live_orders") is not True or execution.get("enabled") is not True:
                raise RuntimeError("Live mode requires order_execution.enabled and allow_live_orders")
        if self.live_config.get("shutdown", {}).get("on_stop") not in {"stop_new_entries", "leave_positions_open"}:
            raise RuntimeError("shutdown.on_stop must be explicit")

    def _reconcile_open_positions(self) -> None:
        positions = self.broker.get_open_positions()
        reconciled: dict[str, dict[str, Any]] = {}
        for position in positions:
            if position.instrument not in self.symbols:
                continue
            key = position.broker_position_id or f"{position.instrument}:{position.average_price}:{position.size}"
            reconciled[key] = {
                "symbol": position.instrument,
                "size": position.size,
                "average_price": position.average_price,
                "unrealized_pnl": position.unrealized_pnl,
                "broker_position_id": position.broker_position_id,
                "reconciled_at": datetime.now(timezone.utc).isoformat(),
                "metadata": position.metadata,
            }
        self.state.open_positions = reconciled
        self.state.metadata["last_reconciled_at"] = datetime.now(timezone.utc).isoformat()

    def _restore_daily_risk_count(self, day: str) -> None:
        key = self.state.global_trade_count_key(day)
        self.risk_manager.current_day = day
        self.risk_manager.trades_today = int(self.state.daily_trade_counts.get(key, 0))

    def _record_trade(self, day: str) -> None:
        self.risk_manager.record_trade()
        key = self.state.global_trade_count_key(day)
        self.state.daily_trade_counts[key] = self.risk_manager.trades_today

    def _ensure_log_header(self) -> None:
        if self.log_path.exists():
            return
        with self.log_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["timestamp_utc", "symbol", "candle_time", "event", "reason"])

    def _log(self, symbol: str, candle: Candle | None, event: str, reason: str) -> None:
        with self.log_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                symbol,
                candle.timestamp_utc.isoformat() if candle else "",
                event,
                reason,
            ])


class MultiStrategyLiveRunner:
    def __init__(self, root: Path, live_config_path: str = "config/live_multi_demo.json") -> None:
        self.root = root.resolve()
        self.project = load_project(self.root)
        self.live_config = load_json(resolve_config_path(self.root, live_config_path))
        self.groups = [_prepare_strategy_group(self.root, group) for group in self.live_config.get("strategy_groups", [])]
        if not self.groups:
            raise RuntimeError("live multi config requires at least one strategy_group")
        self.symbols = sorted({symbol for group in self.groups for symbol in group["symbols"]})
        self.state_path = resolve_config_path(self.root, self.live_config.get("state_path", "runtime/live_multi_state.json"))
        self.log_directory = resolve_config_path(self.root, self.live_config.get("log_directory", "runtime/logs"))
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_directory / f"live_multi_decisions_{datetime.now(timezone.utc):%Y%m%d}.csv"
        self.state = LiveState.load(self.state_path)
        self.risk_manager = RiskManager(self.project["risk"])
        self.cache = SQLiteMarketDataCache(resolve_config_path(self.root, self.project["data"]["historical_store"]["path"]))
        self.cache.initialize()
        self.provider_name = self.project["data"].get("fallback_data_provider", "capital")
        self.data_provider = None
        self.broker = self._create_broker()
        self.notifications = self._create_notification_manager()

    def run(self, once: bool = False, max_iterations: int | None = None) -> LiveRunResult:
        self._validate_gates()
        for closed_event in self._reconcile_open_positions():
            self.notifications.notify_trade_closed(closed_event)
        self.notifications.send_startup(self._safe_account_snapshot())
        iterations = 0
        evaluated = 0
        signals = 0
        orders_submitted = 0
        orders_rejected = 0
        self._ensure_log_header()

        while True:
            iterations += 1
            print(f"[{datetime.now(timezone.utc).isoformat()}] live iteration {iterations} symbols={','.join(self.symbols)}", flush=True)
            for closed_event in self._reconcile_open_positions():
                self.notifications.notify_trade_closed(closed_event)
            for group in self.groups:
                for symbol in group["symbols"]:
                    outcome = self._process_group_symbol(group, symbol)
                    evaluated += int(outcome["evaluated"])
                    signals += int(outcome["signal"])
                    orders_submitted += int(outcome["submitted"])
                    orders_rejected += int(outcome["rejected"])
            account = self._safe_account_snapshot()
            self.notifications.maybe_send_heartbeat(
                iterations,
                evaluated,
                signals,
                orders_submitted,
                orders_rejected,
                account,
                self.state.open_positions,
            )
            self.notifications.maybe_send_daily_summary(account, self.state.open_positions)
            self.state.save(self.state_path)
            if once or (max_iterations is not None and iterations >= max_iterations):
                break
            time.sleep(float(self.live_config.get("poll_seconds", 20)))

        return LiveRunResult(iterations, evaluated, signals, orders_submitted, orders_rejected, self.state_path, self.log_path)

    def _process_group_symbol(self, group: dict[str, Any], symbol: str) -> dict[str, int]:
        candles_1m = self._load_recent_candles(symbol)
        minimum_1m = int(group.get("minimum_1m_candles", 80))
        if len(candles_1m) < minimum_1m:
            self._log(group, symbol, None, "skip", "insufficient_1m_candles")
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}

        latest = candles_1m[-1]
        latest_key = latest.timestamp_utc.isoformat()
        state_key = f"{group['name']}:{symbol}"
        if self.state.last_processed_candle.get(state_key) == latest_key:
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}

        self._update_paper_broker(symbol, latest)
        evaluation = self._evaluate(group, symbol, candles_1m, latest)
        self.state.last_processed_candle[state_key] = latest_key
        if evaluation is None:
            self._log(group, symbol, latest, "skip", "insufficient_derived_candles")
            return {"evaluated": 0, "signal": 0, "submitted": 0, "rejected": 0}
        if not evaluation.should_trade:
            reason = evaluation.rejection_reason.value if evaluation.rejection_reason else "no_signal"
            self._log(group, symbol, latest, "reject", reason)
            return {"evaluated": 1, "signal": 0, "submitted": 0, "rejected": 0}

        if self.state.last_signal_candle.get(state_key) == latest_key:
            self._log(group, symbol, latest, "reject", "duplicate_signal")
            return {"evaluated": 1, "signal": 0, "submitted": 0, "rejected": 0}

        signal = _multi_evaluation_to_signal(group, evaluation)
        if any(position.instrument == symbol for position in self.broker.get_open_positions()):
            self._log(group, symbol, latest, "risk_reject", "symbol_position_already_open")
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}
        if len(self.broker.get_open_positions()) >= int(self.project["risk"].get("max_open_positions", 1)):
            self._log(group, symbol, latest, "risk_reject", "max_open_positions_reached")
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

        entry_price = evaluation.entry_price or latest.close
        trading_day = latest.timestamp_utc.date().isoformat()
        symbol_limit = _symbol_max_trades_per_day(group, symbol)
        if symbol_limit is not None and self.state.daily_trade_counts.get(self.state.trade_count_key(symbol, trading_day), 0) >= symbol_limit:
            self._log(group, symbol, latest, "risk_reject", "symbol_max_trades_per_day_reached")
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

        self._restore_daily_risk_count(trading_day)
        risk_manager = RiskManager(_risk_config_for_symbol(self.project["risk"], group, symbol))
        risk_manager.current_day = self.risk_manager.current_day
        risk_manager.trades_today = self.risk_manager.trades_today
        decision = risk_manager.evaluate(
            signal,
            self.broker.get_account_snapshot(),
            entry_price,
            trading_day=trading_day,
        )
        if not decision.approved or decision.order is None:
            self._log(group, symbol, latest, "risk_reject", decision.reason)
            return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

        order = replace(decision.order, metadata={**decision.order.metadata, "entry_price": entry_price})
        pending_key = f"{state_key}:{latest_key}"
        self.state.pending_orders[pending_key] = {
            "group": group["name"],
            "symbol": symbol,
            "candle_time": latest_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "action": order.action.value,
            "size": order.size,
            "entry_price": entry_price,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
        }
        self.state.save(self.state_path)
        result = self._submit_order(order, entry_price, latest.timestamp_utc.isoformat())
        if result.status.value == "FILLED":
            self.risk_manager.trades_today = risk_manager.trades_today
            self._record_trade(trading_day, symbol)
            self.state.last_signal_candle[state_key] = latest_key
            self.state.pending_orders.pop(pending_key, None)
            self.state.append_order_event(
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "event": "filled",
                    "group": group["name"],
                    "strategy_kind": group["strategy_kind"],
                    "symbol": symbol,
                    "broker_order_id": result.broker_order_id,
                    "candle_time": latest_key,
                    "action": order.action.value,
                    "size": order.size,
                    "entry_price": entry_price,
                    "stop_loss": order.stop_loss,
                    "take_profit": order.take_profit,
                }
            )
            filled_event = self.state.order_events[-1]
            for closed_event in self._reconcile_open_positions():
                self.notifications.notify_trade_closed(closed_event)
            self.notifications.notify_trade_open(filled_event, self._safe_account_snapshot())
            self.state.save(self.state_path)
            self._log(group, symbol, latest, "submitted", signal.reason)
            return {"evaluated": 1, "signal": 1, "submitted": 1, "rejected": 0}

        self.state.pending_orders.pop(pending_key, None)
        self.state.append_order_event(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "rejected",
                "group": group["name"],
                "strategy_kind": group["strategy_kind"],
                "symbol": symbol,
                "candle_time": latest_key,
                "reason": result.rejection_reason or result.status.value,
            }
        )
        self.state.save(self.state_path)
        self._log(group, symbol, latest, "broker_reject", result.rejection_reason or result.status.value)
        return {"evaluated": 1, "signal": 1, "submitted": 0, "rejected": 1}

    def _evaluate(self, group: dict[str, Any], symbol: str, candles_1m: list[Candle], latest: Candle):
        if group["strategy_kind"] == "forex_pullback":
            candles_5m = _aggregate(candles_1m, 5, "MINUTE_5")
            candles_15m = _aggregate(candles_1m, 15, "MINUTE_15")
            if len(candles_5m) < 80 or len(candles_15m) < 80:
                return None
            return group["strategy"].evaluate(
                ForexPullbackContext(
                    symbol=symbol,
                    current_time=latest.timestamp_utc,
                    candles_1m=candles_1m[-80:],
                    candles_5m=candles_5m[-80:],
                    candles_15m=candles_15m[-80:],
                    current_spread=_spread_pips(latest, group["strategy_config"], symbol),
                    config={},
                    news_events=[],
                )
            )

        candles_5m = _aggregate(candles_1m, 5, "MINUTE_5")
        history_bars = max(220, int(group["strategy_config"].get("history_bars", 220)))
        if len(candles_5m) < history_bars:
            return None
        recent_5m = candles_5m[-history_bars:]
        symbol_config = group["strategy_config"].get("symbols", {}).get(symbol, {})
        strategy_type = symbol_config.get("strategy_type", "mean_reversion")
        if strategy_type == "breakout":
            return group["strategies"][symbol].evaluate(BreakoutContext(symbol=symbol, candles_5m=recent_5m))
        return group["strategies"][symbol].evaluate(MeanReversionContext(symbol=symbol, candles_5m=recent_5m))

    def _load_recent_candles(self, symbol: str) -> list[Candle]:
        end = _latest_closed_minute(datetime.now(timezone.utc))
        start = end - timedelta(minutes=int(self.live_config.get("lookback_minutes", 1500)))
        if self.live_config.get("mode") in {"paper", "demo", "live"} and self.project["data"].get("allow_api_fetch_for_missing_data", True):
            provider = self._data_provider()
            candles = _fetch_recent_candles_chunked(provider, symbol, start, end)
            self.cache.upsert_candles(candles)
        return self.cache.get_candles(self.provider_name, symbol, "MINUTE", start, end)

    def _data_provider(self):
        if self.data_provider is None:
            self.data_provider = create_capital_data_provider(self.project)
        return self.data_provider

    def _create_broker(self):
        mode = self.live_config.get("mode", "paper")
        if mode == "paper":
            account = self.live_config.get("paper_account", {})
            execution_config = {"trailing_stop": self.live_config.get("trailing_stop", {})}
            return SimulatedBroker(
                starting_balance=float(account.get("starting_balance", 10000.0)),
                currency=account.get("currency", "USD"),
                execution_config=execution_config,
            )
        client = CapitalClient(
            environment=self.project["broker"].get("environment", "demo"),
            timeout_seconds=int(self.project["broker"].get("request_timeout_seconds", 20)),
            max_retries=int(self.project["broker"].get("max_retries", 3)),
        )
        broker = CapitalBroker(
            client,
            epic_by_symbol=_capital_epic_map(self.project),
            enable_order_placement=bool(self.live_config.get("order_execution", {}).get("enabled", False)),
            trailing_stop_config=self.live_config.get("trailing_stop", {}),
        )
        broker.connect()
        return broker

    def _create_notification_manager(self) -> LiveNotificationManager:
        config = self.live_config.get("notifications", {})
        telegram_config = {}
        telegram_path = config.get("telegram_config")
        if telegram_path:
            telegram_config = load_json(resolve_config_path(self.root, telegram_path))
        elif isinstance(config.get("telegram"), dict):
            telegram_config = dict(config["telegram"])
        elif config:
            telegram_config = dict(config)
        notifier = TelegramNotifier(telegram_config) if telegram_config else TelegramNotifier.disabled()
        return LiveNotificationManager(
            notifier=notifier,
            config=telegram_config,
            state=self.state,
            mode=str(self.live_config.get("mode", "paper")),
            symbols=self.symbols,
            strategy_names=[str(group["name"]) for group in self.groups],
        )

    def _safe_account_snapshot(self):
        try:
            return self.broker.get_account_snapshot()
        except Exception as exc:
            self.state.metadata.setdefault("notifications", {})["last_account_snapshot_error"] = str(exc)
            return None

    def _submit_order(self, order, price: float, timestamp: str):
        if isinstance(self.broker, SimulatedBroker):
            return self.broker.submit_order_at_price(order, price, timestamp)
        return self.broker.submit_order(order)

    def _update_paper_broker(self, symbol: str, candle: Candle) -> None:
        if isinstance(self.broker, SimulatedBroker):
            self.broker.update_for_bar(symbol, candle.high, candle.low, candle.close, candle.timestamp_utc.isoformat())

    def _validate_gates(self) -> None:
        mode = self.live_config.get("mode", "paper")
        if mode not in {"paper", "demo", "live"}:
            raise RuntimeError("live_config.mode must be paper, demo, or live")
        execution = self.live_config.get("order_execution", {})
        if mode == "demo":
            if self.project["broker"].get("environment") != "demo":
                raise RuntimeError("Demo execution requires broker environment demo")
            if execution.get("allow_demo_orders") is not True or execution.get("enabled") is not True:
                raise RuntimeError("Demo execution requires order_execution.enabled and allow_demo_orders")
        if mode == "live":
            if self.project["broker"].get("environment") != "live":
                raise RuntimeError("Live mode requires broker environment live")
            if self.project["risk"].get("allow_live_trading") is not True:
                raise RuntimeError("Live mode requires risk.allow_live_trading=true")
            if execution.get("allow_live_orders") is not True or execution.get("enabled") is not True:
                raise RuntimeError("Live mode requires order_execution.enabled and allow_live_orders")
        if self.live_config.get("shutdown", {}).get("on_stop") not in {"stop_new_entries", "leave_positions_open"}:
            raise RuntimeError("shutdown.on_stop must be explicit")

    def _reconcile_open_positions(self) -> list[dict[str, Any]]:
        previous = dict(self.state.open_positions)
        positions = self.broker.get_open_positions()
        reconciled: dict[str, dict[str, Any]] = {}
        for position in positions:
            if position.instrument not in self.symbols:
                continue
            key = position.broker_position_id or f"{position.instrument}:{position.average_price}:{position.size}"
            reconciled[key] = {
                "symbol": position.instrument,
                "size": position.size,
                "average_price": position.average_price,
                "unrealized_pnl": position.unrealized_pnl,
                "broker_position_id": position.broker_position_id,
                "reconciled_at": datetime.now(timezone.utc).isoformat(),
                "metadata": position.metadata,
            }
        self.state.open_positions = reconciled
        self.state.metadata["last_reconciled_at"] = datetime.now(timezone.utc).isoformat()
        closed: list[dict[str, Any]] = []
        for key, prior in previous.items():
            if key in reconciled:
                continue
            event = dict(prior)
            event["event"] = "position_closed"
            event["position_key"] = key
            event["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
            closed.append(event)
        return closed

    def _restore_daily_risk_count(self, day: str) -> None:
        key = self.state.global_trade_count_key(day)
        self.risk_manager.current_day = day
        self.risk_manager.trades_today = int(self.state.daily_trade_counts.get(key, 0))

    def _record_trade(self, day: str, symbol: str | None = None) -> None:
        self.risk_manager.record_trade()
        key = self.state.global_trade_count_key(day)
        self.state.daily_trade_counts[key] = self.risk_manager.trades_today
        if symbol is not None:
            symbol_key = self.state.trade_count_key(symbol, day)
            self.state.daily_trade_counts[symbol_key] = int(self.state.daily_trade_counts.get(symbol_key, 0)) + 1

    def _ensure_log_header(self) -> None:
        if self.log_path.exists():
            return
        with self.log_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["timestamp_utc", "group", "strategy_kind", "symbol", "candle_time", "event", "reason"])

    def _log(self, group: dict[str, Any], symbol: str, candle: Candle | None, event: str, reason: str) -> None:
        candle_time = candle.timestamp_utc.isoformat() if candle else ""
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"{group['name']} {symbol} {event}: {reason}"
            f"{f' candle={candle_time}' if candle_time else ''}",
            flush=True,
        )
        with self.log_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                group["name"],
                group["strategy_kind"],
                symbol,
                candle_time,
                event,
                reason,
            ])


def _evaluation_to_signal(evaluation) -> Signal:
    action = TradeAction.BUY if evaluation.direction == TradeDirection.LONG else TradeAction.SELL
    return Signal(
        strategy_id="forex_pullback_london_open_v1",
        instrument=evaluation.symbol,
        action=action,
        entry_type=OrderType.MARKET,
        reason=evaluation.reason or "FOREX_PULLBACK_SIGNAL",
        stop_loss=evaluation.stop_loss,
        take_profit=evaluation.target_price,
        metadata=evaluation.metadata,
    )


def _multi_evaluation_to_signal(group: dict[str, Any], evaluation) -> Signal:
    if group["strategy_kind"] == "forex_pullback":
        return _evaluation_to_signal(evaluation)
    direction = evaluation.direction
    is_long = direction in {MeanReversionDirection.LONG, BreakoutDirection.LONG}
    action = TradeAction.BUY if is_long else TradeAction.SELL
    return Signal(
        strategy_id=str(group["strategy_config"].get("strategy_id", f"asset_{group['name']}")),
        instrument=evaluation.symbol,
        action=action,
        entry_type=OrderType.MARKET,
        reason=evaluation.reason or "ASSET_SIGNAL",
        stop_loss=evaluation.stop_loss,
        take_profit=evaluation.target_price,
        metadata=evaluation.metadata,
    )


def _prepare_strategy_group(root: Path, group: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(group)
    prepared["name"] = str(group.get("name") or group.get("strategy_kind"))
    prepared["strategy_kind"] = str(group["strategy_kind"])
    strategy_config = load_json(resolve_config_path(root, group["strategy_config"]))
    symbols = list(group.get("symbols") or strategy_config.get("symbols", []))
    if isinstance(strategy_config.get("symbols"), dict):
        symbols = list(group.get("symbols") or strategy_config["symbols"].keys())
    prepared["symbols"] = symbols
    prepared["strategy_config"] = strategy_config
    if prepared["strategy_kind"] == "forex_pullback":
        strategy_config["symbols"] = symbols
        if group.get("require_spread", True):
            strategy_config.setdefault("filters", {})["allow_missing_spread"] = False
        prepared["strategy"] = ForexTrendPullbackScalper(strategy_config)
    elif prepared["strategy_kind"] == "asset_hybrid":
        prepared["strategies"] = {}
        for symbol in symbols:
            symbol_config = strategy_config.get("symbols", {}).get(symbol, {})
            strategy_type = symbol_config.get("strategy_type", "mean_reversion")
            if strategy_type == "breakout":
                prepared["strategies"][symbol] = AssetBreakoutStrategy(strategy_config)
            elif strategy_type == "mean_reversion":
                prepared["strategies"][symbol] = AssetMeanReversionStrategy(strategy_config)
            else:
                raise RuntimeError(f"Unsupported strategy_type for {symbol}: {strategy_type}")
    else:
        raise RuntimeError(f"Unsupported strategy_kind: {prepared['strategy_kind']}")
    return prepared


def _symbol_max_trades_per_day(group: dict[str, Any], symbol: str) -> int | None:
    symbols_config = group.get("strategy_config", {}).get("symbols", {})
    if not isinstance(symbols_config, dict):
        return None
    value = symbols_config.get(symbol, {}).get("max_trades_per_day")
    return int(value) if value is not None else None


def _risk_config_for_symbol(base_risk_config: dict[str, Any], group: dict[str, Any], symbol: str) -> dict[str, Any]:
    config = dict(base_risk_config)
    strategy_config = group.get("strategy_config", {})
    fixed_sizes = strategy_config.get("fixed_position_sizes", {})
    if isinstance(fixed_sizes, dict) and symbol in fixed_sizes:
        config["position_sizing_mode"] = "fixed"
        config["fixed_position_size"] = fixed_sizes[symbol]
    symbols_config = strategy_config.get("symbols", {})
    if not isinstance(symbols_config, dict):
        return config
    symbol_config = symbols_config.get(symbol, {})
    if "account_risk_per_trade_pct" in symbol_config:
        config["account_risk_per_trade_pct"] = symbol_config["account_risk_per_trade_pct"]
    if "max_trades_per_day" in symbol_config:
        config["max_trades_per_day"] = symbol_config["max_trades_per_day"]
    if "fixed_position_size" in symbol_config:
        config["position_sizing_mode"] = "fixed"
        config["fixed_position_size"] = symbol_config["fixed_position_size"]
    return config


def _latest_closed_minute(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return value - timedelta(minutes=1)


def _spread_pips(candle: Candle, strategy_config: dict[str, Any], symbol: str) -> float | None:
    spread_points = candle.metadata.get("spread_points")
    if spread_points is None:
        return None
    pip_size = float(strategy_config.get("pip_size", {}).get(symbol, 0.01 if symbol.endswith("JPY") else 0.0001))
    if pip_size <= 0:
        return None
    return float(spread_points) / pip_size


def _aggregate(candles: list[Candle], minutes: int, timeframe: str) -> list[Candle]:
    result: list[Candle] = []
    bucket: list[Candle] = []
    current = None
    for candle in candles:
        start = candle.timestamp_utc.replace(
            minute=(candle.timestamp_utc.minute // minutes) * minutes,
            second=0,
            microsecond=0,
        )
        if current is None:
            current = start
        if start != current:
            if len(bucket) == minutes:
                result.append(_aggregate_bucket(bucket, timeframe, current))
            bucket = []
            current = start
        bucket.append(candle)
    if len(bucket) == minutes and current is not None:
        result.append(_aggregate_bucket(bucket, timeframe, current))
    return result


def _aggregate_bucket(bucket: list[Candle], timeframe: str, timestamp: datetime) -> Candle:
    return Candle(
        provider=bucket[0].provider,
        instrument=bucket[0].instrument,
        timeframe=timeframe,
        timestamp_utc=timestamp,
        open=bucket[0].open,
        high=max(candle.high for candle in bucket),
        low=min(candle.low for candle in bucket),
        close=bucket[-1].close,
        volume=sum(candle.volume or 1.0 for candle in bucket),
    )


def _capital_epic_map(project: dict[str, Any]) -> dict[str, str]:
    instruments = load_instruments(project["instruments"])
    epics: dict[str, str] = {}
    for symbol, instrument in instruments.items():
        try:
            epics[symbol] = str(broker_mapping(instrument, "capital")["epic"])
        except KeyError:
            continue
    return epics


def _fetch_recent_candles_chunked(provider, symbol: str, start: datetime, end: datetime) -> list[Candle]:
    candles: list[Candle] = []
    cursor = start
    chunk_minutes = 700
    while cursor <= end:
        chunk_end = min(cursor + timedelta(minutes=chunk_minutes), end)
        try:
            candles.extend(provider.get_historical_candles(symbol, "MINUTE", cursor, chunk_end))
        except CapitalAPIError as exc:
            if "prices.not-found" not in str(exc):
                raise
        cursor = chunk_end + timedelta(minutes=1)
    return candles
