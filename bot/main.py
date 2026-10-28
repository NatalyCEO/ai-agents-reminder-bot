"""Оркестратор напоминателя: цикл событий MAX + расписание дайджеста.

Запуск:   python -m bot.main            — бот в MAX (нужен MAX_BOT_TOKEN)
Консоль:  python -m bot.main --console  — тот же агент без MAX, для отладки
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from bot import store
from bot.agent import run_agent
from bot.digest import build_digest, render_after_toggle
from bot.max_api import MaxClient, parse_callback, parse_message

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("reminder").info

DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "8"))
CHECKED: dict[int, set[str]] = {}  # что отметили в сегодняшнем дайджесте (для перерисовки)

WELCOME = (
    "Я напоминатель. Пересылайте мне сообщения из чатов или пишите заметки — "
    "я сохраню, что надо не забыть.\n\n"
    f"Каждый день в {DIGEST_HOUR}:00 пришлю список дел с галочками. "
    "Неотмеченное буду напоминать, пока вы его не посмотрите.\n\n"
    "Команды: /digest — список сейчас, /list — что записано."
)


def handle_text(api: MaxClient, user_id: int, text: str, source: str) -> None:
    store.remember_user(user_id)
    if text in {"/start", "/help"}:
        api.send(user_id, WELCOME)
        return
    if text in {"/digest", "/list"}:
        send_digest(api, user_id)
        return
    try:
        reply = run_agent(user_id, text, source, log=log)
    except Exception as exc:  # модель недоступна — честно скажем, ничего не теряя
        logging.exception("agent failed")
        reply = f"Не смог обработать: {exc}. Сообщение не сохранено, попробуйте ещё раз."
    api.send(user_id, reply)


def send_digest(api: MaxClient, user_id: int) -> None:
    text, kb = build_digest(user_id)
    CHECKED[user_id] = set()
    api.send(user_id, text, kb)
    store.mark_digest_sent(user_id)


def handle_callback(api: MaxClient, user_id: int, callback_id: str, payload: str) -> None:
    if not payload.startswith("toggle:"):
        api.answer(callback_id, notification="Неизвестная кнопка")
        return
    item_id = payload.split(":", 1)[1]
    item = store.get_item(user_id, item_id)
    if not item:
        api.answer(callback_id, notification="Пункт не найден")
        return
    store.set_done(user_id, item_id, not item["done"])
    checked = CHECKED.setdefault(user_id, set())
    checked.symmetric_difference_update({item_id})
    text, kb = render_after_toggle(user_id, checked)
    api.answer(callback_id, notification="Отмечено" if not item["done"] else "Снова в списке", text=text, keyboard=kb)


def tick_schedule(api: MaxClient) -> None:
    """Раз в день после DIGEST_HOUR каждому известному пользователю — дайджест."""
    if datetime.now().hour < DIGEST_HOUR:
        return
    for user_id in store.known_users():
        if not store.digest_sent_today(user_id):
            log(f"дайджест по расписанию → {user_id}")
            try:
                send_digest(api, user_id)
            except Exception:
                logging.exception("digest failed")


def run_max() -> None:
    api = MaxClient(os.environ.get("MAX_BOT_TOKEN", ""))
    me = api.get_me()
    log(f"бот запущен: {me.get('name')} (@{me.get('username')})")
    while True:
        try:
            updates = api.get_updates(timeout=25)
        except Exception as exc:
            logging.warning("get_updates: %s — повтор через 3 с", exc)
            time.sleep(3)
            continue
        for update in updates:
            kind = update.get("update_type")
            try:
                if kind == "bot_started":
                    user_id = (update.get("user") or {}).get("user_id")
                    if user_id:
                        store.remember_user(int(user_id))
                        api.send(int(user_id), WELCOME)
                elif kind == "message_created":
                    user_id, text, source = parse_message(update)
                    if user_id and text:
                        handle_text(api, user_id, text, source)
                elif kind == "message_callback":
                    user_id, callback_id, payload = parse_callback(update)
                    if user_id and callback_id:
                        handle_callback(api, user_id, callback_id, payload)
            except Exception:
                logging.exception("update failed: %s", kind)
        tick_schedule(api)


class ConsoleClient:
    """Заглушка вместо MAX: печатает, что бот отправил бы."""

    def send(self, user_id: int, text: str, keyboard: dict | None = None) -> dict:
        print(f"\n[бот → {user_id}]\n{text}")
        if keyboard:
            for row in keyboard["payload"]["buttons"]:
                print("   " + " | ".join(f"[{b['text']}]  payload={b['payload']}" for b in row))
        return {}

    def answer(self, callback_id: str, **kwargs) -> dict:
        print(f"\n[бот редактирует сообщение]\n{kwargs.get('text')}")
        return {}


def run_console() -> None:
    api = ConsoleClient()
    user_id = 1
    print("Консольный режим. Пишите заметки, /digest, toggle:<id> — нажать кнопку, /quit — выход.")
    while True:
        try:
            line = input("\nвы> ").strip()
        except EOFError:
            break
        if not line or line == "/quit":
            break
        if line.startswith("toggle:"):
            handle_callback(api, user_id, "cb", line)
        else:
            handle_text(api, user_id, line, "заметка")


if __name__ == "__main__":
    run_console() if "--console" in sys.argv else run_max()
