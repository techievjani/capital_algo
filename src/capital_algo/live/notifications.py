from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from capital_algo.models import AccountSnapshot
from capital_algo.notifications import TelegramNotificationError, TelegramNotifier


class LiveNotificationManager:
    def __init__(
        self,
        notifier: TelegramNotifier | None,
        config: dict[str, Any] | None,
        state: Any,
        mode: str,
        symbols: list[str],
        strategy_names: list[str],
    ) -> None:
        self.notifier = notifier or TelegramNotifier.disabled()
        self.config = config or {}
        self.state = state
        self.mode = mode
        self.symbols = symbols
        self.strategy_names = strategy_names

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False)) and self.notifier.enabled

    def send_startup(self, account: AccountSnapshot | None = None) -> None:
        if not self.enabled:
            return
        lines = [
            "CapitalAlgo started",
            f"Mode: {self.mode}",
            f"Symbols: {', '.join(self.symbols)}",
            f"Strategies: {', '.join(self.strategy_names)}",
        ]
        if account is not None:
            lines.append(_account_line(account))
        if self._safe_send("\n".join(lines)):
            self._notification_state()["last_startup_at"] = datetime.now(timezone.utc).isoformat()

    def maybe_send_heartbeat(
        self,
        iterations: int,
        evaluated: int,
        signals: int,
        submitted: int,
        rejected: int,
        account: AccountSnapshot | None,
        open_positions: dict[str, dict[str, Any]],
    ) -> None:
        if not self.enabled or not bool(self.config.get("send_heartbeat", True)):
            return
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=float(self.config.get("heartbeat_minutes", 60)))
        state = self._notification_state()
        last = _parse_dt(state.get("last_heartbeat_at"))
        if last is not None and now - last < interval:
            return
        lines = [
            "CapitalAlgo heartbeat",
            f"Time UTC: {now.replace(microsecond=0).isoformat()}",
            f"Mode: {self.mode}",
            f"Iterations: {iterations}",
            f"Evaluated: {evaluated} Signals: {signals}",
            f"Submitted: {submitted} Rejected: {rejected}",
            f"Open positions: {len(open_positions)}",
        ]
        if account is not None:
            lines.append(_account_line(account))
        if open_positions:
            lines.append("Positions:")
            for position in open_positions.values():
                lines.append(
                    f"- {position.get('symbol')} size={_fmt(position.get('size'))} "
                    f"avg={_fmt(position.get('average_price'))} upl={_fmt(position.get('unrealized_pnl'))}"
                )
        if self._safe_send("\n".join(lines)):
            state["last_heartbeat_at"] = now.isoformat()

    def notify_trade_open(self, event: dict[str, Any], account: AccountSnapshot | None = None) -> None:
        if not self.enabled or not bool(self.config.get("send_trade_notifications", True)):
            return
        event_id = _event_id("open", event)
        sent = self._sent_event_ids()
        if event_id in sent:
            return
        lines = [
            "Trade opened",
            f"Symbol: {event.get('symbol')}",
            f"Action: {event.get('action')}",
            f"Size: {_fmt(event.get('size'))}",
            f"Entry: {_fmt(event.get('entry_price'))}",
            f"Stop: {_fmt(event.get('stop_loss'))}",
            f"Target: {_fmt(event.get('take_profit'))}",
            f"Broker order: {event.get('broker_order_id') or 'n/a'}",
            f"Time UTC: {event.get('timestamp_utc')}",
        ]
        if account is not None:
            lines.append(_account_line(account))
        if self._safe_send("\n".join(lines)):
            sent.append(event_id)
            self._trim_sent_events()

    def notify_trade_closed(self, event: dict[str, Any]) -> None:
        if not self.enabled or not bool(self.config.get("send_trade_notifications", True)):
            return
        event_id = _event_id("closed", event)
        sent = self._sent_event_ids()
        if event_id in sent:
            return
        realized_pnl = event.get("realized_pnl")
        realized_currency = event.get("realized_currency") or ""
        lines = [
            "Position closed or no longer open",
            f"Symbol: {event.get('symbol')}",
            f"Size: {_fmt(event.get('size'))}",
            f"Average: {_fmt(event.get('average_price'))}",
            f"Broker position: {event.get('broker_position_id') or 'n/a'}",
            f"Detected UTC: {event.get('timestamp_utc')}",
        ]
        if realized_pnl is not None:
            lines.insert(4, f"Realized P&L: {_fmt(realized_pnl)} {realized_currency}".rstrip())
            if event.get("close_transaction_time_utc"):
                lines.append(f"Broker close UTC: {event.get('close_transaction_time_utc')}")
            if event.get("close_transaction_reference"):
                lines.append(f"Close reference: {event.get('close_transaction_reference')}")
        else:
            lines.insert(4, "Realized P&L: unavailable from broker history")
            lines.insert(5, f"Last seen unrealized P&L: {_fmt(event.get('unrealized_pnl'))}")
        if self._safe_send("\n".join(lines)):
            sent.append(event_id)
            self._trim_sent_events()

    def notify_error(self, message: str) -> None:
        if not self.enabled or not bool(self.config.get("send_error_notifications", True)):
            return
        now = datetime.now(timezone.utc)
        state = self._notification_state()
        last_message = state.get("last_error_message")
        last_sent = _parse_dt(state.get("last_error_sent_at"))
        cooldown = timedelta(minutes=float(self.config.get("error_notification_cooldown_minutes", 15)))
        if last_message == message and last_sent is not None and now - last_sent < cooldown:
            return
        if self._safe_send(f"CapitalAlgo warning\n{message}"):
            state["last_error_message"] = message
            state["last_error_sent_at"] = now.isoformat()

    def maybe_send_daily_summary(
        self,
        account: AccountSnapshot | None,
        open_positions: dict[str, dict[str, Any]],
    ) -> None:
        if not self.enabled or not bool(self.config.get("send_daily_summary", True)):
            return
        now = datetime.now(timezone.utc)
        send_time = _parse_time(str(self.config.get("daily_summary_time_utc", "23:59")))
        if now.time() < send_time:
            return
        state = self._notification_state()
        today = now.date().isoformat()
        if state.get("last_daily_summary_date") == today:
            return
        events_today = [
            event
            for event in self.state.order_events
            if str(event.get("timestamp_utc", "")).startswith(today)
        ]
        filled = [event for event in events_today if event.get("event") == "filled"]
        rejected = [event for event in events_today if event.get("event") == "rejected"]
        lines = [
            "CapitalAlgo daily summary",
            f"Date UTC: {today}",
            f"Mode: {self.mode}",
            f"Filled orders: {len(filled)}",
            f"Rejected orders: {len(rejected)}",
            f"Open positions: {len(open_positions)}",
        ]
        if account is not None:
            lines.append(_account_line(account))
        if self._safe_send("\n".join(lines)):
            state["last_daily_summary_date"] = today

    def _safe_send(self, text: str) -> bool:
        try:
            return self.notifier.send(text)
        except TelegramNotificationError as exc:
            self._notification_state()["last_error"] = str(exc)
            print(f"Telegram notification failed: {exc}", flush=True)
            return False

    def _notification_state(self) -> dict[str, Any]:
        notifications = self.state.metadata.setdefault("notifications", {})
        return notifications

    def _sent_event_ids(self) -> list[str]:
        state = self._notification_state()
        sent = state.setdefault("sent_event_ids", [])
        if not isinstance(sent, list):
            state["sent_event_ids"] = []
        return state["sent_event_ids"]

    def _trim_sent_events(self) -> None:
        sent = self._sent_event_ids()
        max_ids = int(self.config.get("max_sent_event_ids", 500))
        if len(sent) > max_ids:
            del sent[:-max_ids]


def _event_id(prefix: str, event: dict[str, Any]) -> str:
    stable = event.get("broker_order_id") or event.get("broker_position_id")
    if stable:
        return f"{prefix}:{stable}"
    return f"{prefix}:{event.get('symbol')}:{event.get('candle_time') or event.get('timestamp_utc')}"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _account_line(account: AccountSnapshot) -> str:
    return (
        f"Account: balance={_fmt(account.balance)} equity={_fmt(account.equity)} "
        f"available={_fmt(account.available_funds)} {account.currency}"
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
