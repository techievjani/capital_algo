from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from capital_algo.http import default_ssl_context
from capital_algo.models import AccountSnapshot, Candle, OrderRequest, OrderResult, OrderStatus, Position, TradeAction


class CapitalAPIError(RuntimeError):
    """Raised for sanitized Capital.com API failures."""


@dataclass(frozen=True)
class CapitalSession:
    cst: str
    security_token: str
    account_id: str | None
    raw: dict[str, Any]


class CapitalClient:
    def __init__(self, environment: str = "demo", timeout_seconds: int = 20, max_retries: int = 3) -> None:
        self.environment = environment
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_url = (
            "https://api-capital.backend-capital.com/api/v1"
            if environment == "live"
            else "https://demo-api-capital.backend-capital.com/api/v1"
        )
        self.ssl_context = default_ssl_context()
        self.session: CapitalSession | None = None

    def connect(self) -> None:
        api_key = os.environ.get("CAPITAL_API_KEY")
        identifier = os.environ.get("CAPITAL_IDENTIFIER")
        password = os.environ.get("CAPITAL_PASSWORD")
        if not api_key or not identifier or not password:
            raise CapitalAPIError("Missing Capital.com environment variables")

        response, headers = self._request(
            "POST",
            "/session",
            headers={"X-CAP-API-KEY": api_key},
            body={
                "identifier": identifier,
                "password": password,
                "encryptedPassword": False,
            },
            include_session=False,
        )
        cst = headers.get("cst")
        security_token = headers.get("x-security-token")
        if not cst or not security_token:
            raise CapitalAPIError("Capital.com authentication did not return session headers")
        self.session = CapitalSession(
            cst=cst,
            security_token=security_token,
            account_id=response.get("currentAccountId"),
            raw=response,
        )

    def get_account_snapshot(self) -> AccountSnapshot:
        self._ensure_session()
        response, _ = self._request("GET", "/session")
        account_info = response.get("accountInfo", {})
        if not account_info:
            account_info, currency = self._account_info_from_accounts()
        else:
            currency = str(response.get("currencyIsoCode") or response.get("currency") or "")
        return AccountSnapshot(
            account_id=str(response.get("currentAccountId") or response.get("accountId") or self.session.account_id or ""),
            currency=currency,
            balance=float(account_info.get("balance", 0.0)),
            equity=float(account_info.get("balance", 0.0)) + float(account_info.get("profitLoss", 0.0)),
            available_funds=_optional_float(account_info.get("available")),
            metadata={"environment": self.environment},
        )

    def _account_info_from_accounts(self) -> tuple[dict[str, Any], str]:
        response, _ = self._request("GET", "/accounts")
        accounts = response.get("accounts", [])
        selected: dict[str, Any] = {}
        for account in accounts:
            if account.get("accountId") == self.session.account_id:
                selected = account
                break
        if not selected and accounts:
            selected = accounts[0]
        return dict(selected.get("balance", {})), str(selected.get("currency") or "")

    def get_market(self, search_term: str) -> dict[str, Any]:
        params = urllib.parse.urlencode({"searchTerm": search_term})
        response, _ = self._request("GET", f"/markets?{params}")
        return response

    def get_prices(
        self,
        epic: str,
        resolution: str,
        start_utc: datetime,
        end_utc: datetime,
        max_points: int = 1000,
        logical_symbol: str | None = None,
    ) -> list[Candle]:
        self._ensure_session()
        params = urllib.parse.urlencode(
            {
                "resolution": resolution,
                "max": max_points,
                "from": _capital_time(start_utc),
                "to": _capital_time(end_utc),
            }
        )
        response, _ = self._request("GET", f"/prices/{urllib.parse.quote(epic)}?{params}")
        prices = response.get("prices", [])
        candles: list[Candle] = []
        for item in prices:
            timestamp = item.get("snapshotTimeUTC")
            if not timestamp:
                continue
            candles.append(
                Candle(
                    provider="capital",
                    instrument=logical_symbol or epic,
                    timeframe=resolution,
                    timestamp_utc=_parse_capital_time(timestamp),
                    open=_mid_price(item.get("openPrice", {})),
                    high=_mid_price(item.get("highPrice", {})),
                    low=_mid_price(item.get("lowPrice", {})),
                    close=_mid_price(item.get("closePrice", {})),
                    volume=_optional_float(item.get("lastTradedVolume")),
                    metadata={
                        "epic": epic,
                        "spread_points": _spread_points(item.get("closePrice", {})),
                    },
                )
            )
        return candles

    def get_positions(self) -> dict[str, Any]:
        self._ensure_session()
        response, _ = self._request("GET", "/positions")
        return response

    def create_position(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float | None = None,
        profit_level: float | None = None,
        trailing_stop: bool = False,
        stop_distance: float | None = None,
    ) -> dict[str, Any]:
        self._ensure_session()
        body: dict[str, Any] = {
            "epic": epic,
            "direction": direction,
            "size": size,
            "guaranteedStop": False,
        }
        if trailing_stop:
            body["trailingStop"] = True
            if stop_distance is None:
                raise CapitalAPIError("Capital.com trailing stop requires stopDistance")
            body["stopDistance"] = stop_distance
        elif stop_level is not None:
            body["stopLevel"] = stop_level
        if profit_level is not None:
            body["profitLevel"] = profit_level
        response, _ = self._request("POST", "/positions", body=body)
        return response

    def update_position(
        self,
        deal_id: str,
        stop_level: float | None = None,
        profit_level: float | None = None,
        trailing_stop: bool = False,
        stop_distance: float | None = None,
    ) -> dict[str, Any]:
        self._ensure_session()
        body: dict[str, Any] = {"guaranteedStop": False}
        if trailing_stop:
            body["trailingStop"] = True
            if stop_distance is None:
                raise CapitalAPIError("Capital.com trailing stop requires stopDistance")
            body["stopDistance"] = stop_distance
        elif stop_level is not None:
            body["stopLevel"] = stop_level
        if profit_level is not None:
            body["profitLevel"] = profit_level
        response, _ = self._request("PUT", f"/positions/{urllib.parse.quote(deal_id)}", body=body)
        return response

    def close_position(self, deal_id: str) -> dict[str, Any]:
        self._ensure_session()
        response, _ = self._request("DELETE", f"/positions/{urllib.parse.quote(deal_id)}")
        return response

    def confirm(self, deal_reference: str) -> dict[str, Any]:
        self._ensure_session()
        response, _ = self._request("GET", f"/confirms/{urllib.parse.quote(deal_reference)}")
        return response

    def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        include_session: bool = True,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        if include_session:
            self._ensure_session()
            request_headers["CST"] = self.session.cst
            request_headers["X-SECURITY-TOKEN"] = self.session.security_token

        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers=request_headers,
            method=method,
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                    text = response.read().decode("utf-8")
                    parsed = json.loads(text) if text else {}
                    return parsed, {key.lower(): value for key, value in response.headers.items()}
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8")
                try:
                    parsed = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    parsed = {}
                code = parsed.get("errorCode") or exc.reason or exc.code
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise CapitalAPIError(f"Capital.com API error {exc.code}: {code}") from exc
            except urllib.error.URLError as exc:
                raise CapitalAPIError(f"Capital.com API connection failed: {exc.reason}") from exc
        raise CapitalAPIError("Capital.com API request failed after retries")

    def _ensure_session(self) -> None:
        if self.session is None:
            raise CapitalAPIError("Capital.com session is not connected")


class CapitalBroker:
    """Capital.com execution adapter."""

    def __init__(
        self,
        client: CapitalClient,
        epic_by_symbol: dict[str, str] | None = None,
        enable_order_placement: bool = False,
        trailing_stop_config: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.epic_by_symbol = epic_by_symbol or {}
        self.enable_order_placement = enable_order_placement
        self.trailing_stop_config = trailing_stop_config or {}

    def connect(self) -> None:
        self.client.connect()

    def get_account_snapshot(self) -> AccountSnapshot:
        return self.client.get_account_snapshot()

    def get_open_positions(self) -> list[Position]:
        response = self.client.get_positions()
        positions = response.get("positions", [])
        parsed: list[Position] = []
        for item in positions:
            market = item.get("market", {})
            position = item.get("position", {})
            symbol = _symbol_from_epic(str(market.get("epic") or position.get("epic") or ""), self.epic_by_symbol)
            size = _optional_float(position.get("size")) or 0.0
            direction = str(position.get("direction") or "").upper()
            parsed.append(
                Position(
                    instrument=symbol,
                    size=size if direction == "BUY" else -size,
                    average_price=_optional_float(position.get("level")) or 0.0,
                    unrealized_pnl=_optional_float(position.get("upl")) or 0.0,
                    broker_position_id=str(position.get("dealId") or ""),
                    metadata={"market": market, "position": position},
                )
            )
        return parsed

    def submit_order(self, order: OrderRequest) -> OrderResult:
        if not self.enable_order_placement:
            return OrderResult(OrderStatus.REJECTED, rejection_reason="Capital.com order placement is disabled by config")
        epic = self.epic_by_symbol.get(order.instrument, order.instrument)
        direction = "BUY" if order.action == TradeAction.BUY else "SELL"
        trailing_enabled = bool(self.trailing_stop_config.get("enabled", False))
        entry_price = _optional_float(order.metadata.get("entry_price"))
        stop_distance = abs(entry_price - order.stop_loss) if trailing_enabled and entry_price is not None and order.stop_loss is not None else None
        try:
            response = self.client.create_position(
                epic=epic,
                direction=direction,
                size=order.size,
                stop_level=None if trailing_enabled else order.stop_loss,
                profit_level=order.take_profit,
                trailing_stop=trailing_enabled,
                stop_distance=stop_distance,
            )
            deal_reference = response.get("dealReference")
            confirmation = self.client.confirm(str(deal_reference)) if deal_reference else {}
        except CapitalAPIError as exc:
            return OrderResult(OrderStatus.REJECTED, rejection_reason=str(exc))
        deal_id = _confirmed_deal_id(confirmation)
        return OrderResult(
            status=OrderStatus.FILLED if deal_id or deal_reference else OrderStatus.ACCEPTED,
            broker_order_id=deal_id or str(deal_reference or ""),
            metadata={"response": response, "confirmation": confirmation},
        )

    def close_position(self, position_id: str) -> OrderResult:
        if not self.enable_order_placement:
            return OrderResult(OrderStatus.REJECTED, rejection_reason="Capital.com order placement is disabled by config")
        try:
            response = self.client.close_position(position_id)
            deal_reference = response.get("dealReference")
            confirmation = self.client.confirm(str(deal_reference)) if deal_reference else {}
        except CapitalAPIError as exc:
            return OrderResult(OrderStatus.REJECTED, rejection_reason=str(exc))
        return OrderResult(
            status=OrderStatus.FILLED if deal_reference else OrderStatus.ACCEPTED,
            broker_order_id=str(deal_reference or position_id),
            metadata={"response": response, "confirmation": confirmation},
        )

    def update_position(
        self,
        position_id: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> OrderResult:
        if not self.enable_order_placement:
            return OrderResult(OrderStatus.REJECTED, rejection_reason="Capital.com order placement is disabled by config")
        try:
            response = self.client.update_position(position_id, stop_level=stop_loss, profit_level=take_profit)
            deal_reference = response.get("dealReference")
            confirmation = self.client.confirm(str(deal_reference)) if deal_reference else {}
        except CapitalAPIError as exc:
            return OrderResult(OrderStatus.REJECTED, rejection_reason=str(exc))
        return OrderResult(
            status=OrderStatus.ACCEPTED,
            broker_order_id=str(deal_reference or position_id),
            metadata={"response": response, "confirmation": confirmation},
        )


def _capital_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_capital_time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _mid_price(value: dict[str, Any]) -> float:
    bid = _optional_float(value.get("bid"))
    ask = _optional_float(value.get("ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    if bid is not None:
        return bid
    if ask is not None:
        return ask
    raise CapitalAPIError("Capital.com price payload missing bid/ask")


def _spread_points(value: dict[str, Any]) -> float | None:
    bid = _optional_float(value.get("bid"))
    ask = _optional_float(value.get("ask"))
    if bid is None or ask is None:
        return None
    return ask - bid


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _symbol_from_epic(epic: str, epic_by_symbol: dict[str, str]) -> str:
    for symbol, mapped_epic in epic_by_symbol.items():
        if mapped_epic == epic:
            return symbol
    return epic


def _confirmed_deal_id(confirmation: dict[str, Any]) -> str | None:
    affected = confirmation.get("affectedDeals")
    if isinstance(affected, list) and affected:
        first = affected[0]
        if isinstance(first, dict) and first.get("dealId"):
            return str(first["dealId"])
    deal_id = confirmation.get("dealId")
    if deal_id:
        return str(deal_id)
    return None
