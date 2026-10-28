"""Прогон агента без MAX: пересылка с двумя делами, заметка, список, галочка, отметка словами.

Запуск из корня проекта (нужны folder_id и api_key в .env или в окружении):
    python tests/smoke.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Если .env проекта ещё не заполнен, берём креды модели из соседнего проекта «Кот-аналитик».
if not os.environ.get("folder_id"):
    neighbour = Path(r"D:\information_learning_analytics_system\ai-studio-project\.env")
    if neighbour.exists():
        for line in neighbour.read_text(encoding="utf-8").splitlines():
            if line.startswith(("folder_id=", "api_key=")):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value.strip())

os.environ["DIGEST_HOUR"] = "0"

from bot import store  # noqa: E402
from bot.main import ConsoleClient, handle_callback, handle_text, send_digest  # noqa: E402

store.DATA_FILE = ROOT / "data" / "items.smoke.json"
if store.DATA_FILE.exists():
    store.DATA_FILE.unlink()

api = ConsoleClient()
uid = 1
handle_text(
    api,
    uid,
    "Коллеги, напоминаю: отчёты по успеваемости за четверть сдать завучу до пятницы. "
    "И не забудьте заполнить согласия на экскурсию — собираем до 30 октября.",
    "переслано от: Завуч И.П.",
)
handle_text(api, uid, "посмотреть пост про олимпиаду по информатике в группе школы", "заметка")
handle_text(api, uid, "что у меня в списке?", "заметка")
send_digest(api, uid)
first = store.list_items(uid)[0]["id"]
handle_callback(api, uid, "cb1", f"toggle:{first}")
handle_text(api, uid, "согласия на экскурсию собрал", "заметка")
send_digest(api, uid)
