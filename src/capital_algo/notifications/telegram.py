from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from capital_algo.http import default_ssl_context


class TelegramNotificationError(RuntimeError):
    """Raised when Telegram rejects or cannot receive a message."""


class TelegramNotifier:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.token_env = str(self.config.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
        self.chat_id_env = str(self.config.get("chat_id_env", "TELEGRAM_CHAT_ID"))
        self.timeout_seconds = int(self.config.get("timeout_seconds", 20))
        self.ssl_context = default_ssl_context()

    @classmethod
    def disabled(cls) -> "TelegramNotifier":
        return cls({"enabled": False})

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        token = os.environ.get(self.token_env)
        chat_id = os.environ.get(self.chat_id_env)
        if not token or not chat_id:
            raise TelegramNotificationError("Telegram token or chat id environment variable is missing")

        payload = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = _read_telegram_error(exc)
            raise TelegramNotificationError(f"Telegram API error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise TelegramNotificationError(f"Telegram connection failed: {exc.reason}") from exc

        if not parsed.get("ok"):
            raise TelegramNotificationError(str(parsed.get("description") or "Telegram send failed"))
        return True

    def send_test(self) -> bool:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return self.send(f"CapitalAlgo Telegram test OK\nTime UTC: {now}")


def _read_telegram_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return str(exc.reason)
    return str(payload.get("description") or payload.get("error_code") or exc.reason)
