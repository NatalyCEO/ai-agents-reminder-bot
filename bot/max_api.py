"""Минимальный клиент MAX Bot API — ровно то, что нужно напоминателю.

Три вызова:
- get_updates  — забрать новые события (long polling)
- send         — отправить пользователю текст и, при желании, клавиатуру
- answer       — ответить на нажатие кнопки и заменить текст сообщения
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://platform-api2.max.ru"
CA_BUNDLE = Path(__file__).resolve().parents[1] / "certs" / "max_ca_bundle.pem"


class MaxClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Пустой MAX_BOT_TOKEN")
        self.session = requests.Session()
        self.session.headers["Authorization"] = token
        # platform-api2.max.ru подписан цепочкой Минцифры, её нет в certifi
        self.session.verify = str(CA_BUNDLE) if CA_BUNDLE.exists() else True
        self.marker: int | None = None  # «докуда прочитали» ленту событий

    def _request(self, method: str, path: str, *, timeout: float = 60, **kwargs: Any) -> dict:
        response = self.session.request(method, BASE_URL + path, timeout=timeout, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}

    def get_me(self) -> dict:
        return self._request("GET", "/me")

    def get_updates(self, timeout: int = 25) -> list[dict]:
        params: dict[str, Any] = {"timeout": timeout, "limit": 100}
        if self.marker is not None:
            params["marker"] = self.marker
        data = self._request("GET", "/updates", params=params, timeout=timeout + 15)
        if data.get("marker") is not None:
            self.marker = data["marker"]
        return [u for u in data.get("updates") or [] if isinstance(u, dict)]

    def send(self, user_id: int, text: str, keyboard: dict | None = None) -> dict:
        body: dict[str, Any] = {"text": text[:4000], "format": "html"}
        if keyboard:
            body["attachments"] = [keyboard]
        return self._request("POST", "/messages", params={"user_id": user_id}, json=body)

    def answer(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        text: str | None = None,
        keyboard: dict | None = None,
    ) -> dict:
        """Ответ на кнопку. Если передан text — MAX заменит исходное сообщение."""
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification[:200]
        if text is not None:
            message: dict[str, Any] = {"text": text[:4000], "format": "html"}
            if keyboard:
                message["attachments"] = [keyboard]
            body["message"] = message
        return self._request("POST", "/answers", params={"callback_id": callback_id}, json=body or {"notification": "OK"})


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """rows = [[(подпись, payload), ...], ...] → вложение inline_keyboard."""
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [[{"type": "callback", "text": text[:64], "payload": payload} for text, payload in row] for row in rows]
        },
    }


def parse_message(update: dict) -> tuple[int | None, str, str]:
    """Из события message_created → (user_id, текст, источник).

    Пересланное сообщение приходит в message.link (type = forward):
    текст берём оттуда, а подпись пользователя (если есть) — из body.
    """
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    user_id = sender.get("user_id") or recipient.get("user_id")
    body = message.get("body") or {}
    text = str(body.get("text") or "").strip()
    source = "заметка"

    link = message.get("link") or {}
    if link.get("type") == "forward":
        forwarded = link.get("message") or {}
        fwd_text = str(forwarded.get("text") or (forwarded.get("body") or {}).get("text") or "").strip()
        who = (link.get("sender") or forwarded.get("sender") or {}).get("name") or "неизвестный отправитель"
        if fwd_text:
            text = f"{text}\n---\n{fwd_text}".strip() if text else fwd_text
            source = f"переслано от: {who}"
    return (int(user_id) if user_id else None), text, source


def parse_callback(update: dict) -> tuple[int | None, str, str]:
    """Из события message_callback → (user_id, callback_id, payload)."""
    callback = update.get("callback") or {}
    user = callback.get("user") or {}
    user_id = user.get("user_id") or update.get("user_id")
    return (int(user_id) if user_id else None), str(callback.get("callback_id") or ""), str(callback.get("payload") or "")
