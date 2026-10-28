"""Дайджест — список дел с галочками. Собирается кодом, без модели.

Это сознательное решение: расписание, порядок пунктов и галочки
детерминированы, модель тут не нужна. Модель работает на входе (разобрать
сообщение), код — на выходе (показать список и запомнить отметки).
"""

from __future__ import annotations

from datetime import date
from html import escape

from bot import store
from bot.max_api import keyboard

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _due_label(due: str | None) -> str:
    if not due:
        return ""
    try:
        d = date.fromisoformat(due)
    except ValueError:
        return f" — {due}"
    delta = (d - date.today()).days
    when = f"{d.day} {MONTHS[d.month - 1]}"
    if delta < 0:
        return f" — <b>просрочено</b> ({when})"
    if delta == 0:
        return " — <b>сегодня</b>"
    if delta == 1:
        return " — завтра"
    return f" — до {when}"


def build_digest(user_id: int) -> tuple[str, dict | None]:
    """Текст дайджеста и клавиатура. Пункты живут в списке, пока не отмечены."""
    open_items = store.list_items(user_id)
    if not open_items:
        return "Список пуст — всё просмотрено.", None

    lines = [f"<b>Дела на {date.today().day} {MONTHS[date.today().month - 1]}</b>", ""]
    rows: list[list[tuple[str, str]]] = []
    for n, item in enumerate(open_items, 1):
        lines.append(f"{n}. {escape(item['title'])}{_due_label(item['due'])}")
        rows.append([(f"☐ {n}. {item['title'][:28]}", f"toggle:{item['id']}")])
    lines.append("")
    lines.append("Нажмите на пункт, когда посмотрели. Неотмеченное вернётся завтра.")
    return "\n".join(lines), keyboard(rows)


def render_after_toggle(user_id: int, checked: set[str]) -> tuple[str, dict | None]:
    """Перерисовать тот же дайджест после нажатия: отмеченные — с галочкой."""
    items = [i for i in store.list_items(user_id, include_done=True) if not i["done"] or i["id"] in checked]
    if not items:
        return "Список пуст — всё просмотрено.", None
    lines = [f"<b>Дела на {date.today().day} {MONTHS[date.today().month - 1]}</b>", ""]
    rows: list[list[tuple[str, str]]] = []
    for n, item in enumerate(items, 1):
        done = item["done"]
        mark = "✅" if done else "☐"
        title = escape(item["title"])
        lines.append(f"{n}. {mark} {'<s>' + title + '</s>' if done else title}{'' if done else _due_label(item['due'])}")
        rows.append([(f"{mark} {n}. {item['title'][:28]}", f"toggle:{item['id']}")])
    left = sum(1 for i in items if not i["done"])
    lines.append("")
    lines.append("Всё просмотрено." if left == 0 else f"Осталось: {left}. Неотмеченное вернётся завтра.")
    return "\n".join(lines), keyboard(rows)
