"""Хранилище списка дел — один JSON-файл. Это «долгая память» бота.

Модель её не видит целиком: в контекст попадает только то,
что вернул инструмент list_items. Так устроена любая внешняя память агента.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "items.json"


def _load() -> dict:
    if not DATA_FILE.exists():
        return {"items": [], "users": {}}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_user(user_id: int) -> None:
    data = _load()
    data["users"].setdefault(str(user_id), {"last_digest": None})
    _save(data)


def known_users() -> list[int]:
    return [int(uid) for uid in _load()["users"]]


def digest_sent_today(user_id: int) -> bool:
    return _load()["users"].get(str(user_id), {}).get("last_digest") == date.today().isoformat()


def mark_digest_sent(user_id: int) -> None:
    data = _load()
    data["users"].setdefault(str(user_id), {})["last_digest"] = date.today().isoformat()
    _save(data)


def add_item(user_id: int, title: str, due: str | None, source: str, details: str) -> dict:
    data = _load()
    item = {
        "id": secrets.token_hex(3),
        "user_id": user_id,
        "title": title.strip()[:80],
        "due": due or None,
        "source": source,
        "details": details.strip()[:500],
        "created": datetime.now().isoformat(timespec="minutes"),
        "done": False,
    }
    data["items"].append(item)
    data["users"].setdefault(str(user_id), {"last_digest": None})
    _save(data)
    return item


def list_items(user_id: int, include_done: bool = False) -> list[dict]:
    items = [i for i in _load()["items"] if i["user_id"] == user_id and (include_done or not i["done"])]
    # сначала с ближайшим сроком, без срока — в конец
    return sorted(items, key=lambda i: (i["due"] is None, i["due"] or "", i["created"]))


def get_item(user_id: int, item_id: str) -> dict | None:
    return next((i for i in _load()["items"] if i["user_id"] == user_id and i["id"] == item_id), None)


def set_done(user_id: int, item_id: str, done: bool = True) -> dict | None:
    data = _load()
    for item in data["items"]:
        if item["user_id"] == user_id and item["id"] == item_id:
            item["done"] = done
            _save(data)
            return item
    return None
