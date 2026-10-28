"""Агент напоминателя: модель + три инструмента + цикл.

Схема та же, что на лекции:
  контекст → модель → (вызов инструмента → результат в контекст → снова модель)* → текст.
Модель ничего не записывает сама: она просит save_item, а запись делает наша функция.
"""

from __future__ import annotations

import json
import os
from datetime import date

from dotenv import load_dotenv
from openai import OpenAI

from bot import store

load_dotenv()

MAX_STEPS = 6  # предохранитель от зацикливания
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

SYSTEM_PROMPT = """Ты — напоминатель учителя. Сегодня {today}, {weekday}.

Тебе пересылают сообщения из школьных чатов (администрация, родители, ученики, посты групп)
или пишут короткие заметки. Твоя работа — ничего не потерять.

Правила:
1. Если в сообщении есть то, к чему пользователю надо вернуться, вызови save_item.
   title — короткий заголовок до 60 знаков: что сделать (глагол + суть).
   due — срок в формате ГГГГ-ММ-ДД, только если он назван или однозначно выводится из текста
   («до пятницы», «завтра») относительно сегодняшней даты. Иначе due не указывай.
2. В одном сообщении может быть несколько дел — сохрани каждое отдельным save_item.
3. Если пользователь спрашивает, что у него в списке, вызови list_items и ответь коротким списком.
4. Если пользователь сообщает, что что-то сделал, сначала list_items, найди подходящий пункт
   и вызови mark_done с его id. Если подходящих несколько или ни одного — спроси.
5. Не выдумывай сроки и факты, которых нет в сообщении.
6. Ответ — одна-две короткие строки: что записал и на какой срок. Без вступлений,
   без вопросов «хотите ещё что-то», без markdown (никаких ** и #). Пример:
   «Записал: сдать отчёты завучу — до 30 окт; заполнить согласия — до 30 окт».
7. Ты пишешь только пользователю. Ничего никому не пересылай и не отправляй."""

# Контракты инструментов — то, что читает модель, выбирая, кого позвать.
TOOLS = [
    {
        "type": "function",
        "name": "save_item",
        "description": "Сохранить дело в список пользователя. Вызывай для каждого отдельного дела.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Короткий заголовок дела, до 60 знаков"},
                "due": {"type": "string", "description": "Срок ГГГГ-ММ-ДД, если он есть в тексте"},
                "details": {"type": "string", "description": "Суть исходного сообщения в одну-две фразы"},
            },
            "required": ["title", "details"],
        },
    },
    {
        "type": "function",
        "name": "list_items",
        "description": "Показать открытые (не отмеченные) дела пользователя с их id и сроками.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "mark_done",
        "description": "Отметить дело выполненным по его id из list_items.",
        "parameters": {
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "id дела"}},
            "required": ["item_id"],
        },
    },
]


def run_tool(user_id: int, name: str, args: dict, source: str) -> str:
    """Исполняет инструмент. Сюда модель не имеет доступа — только через оркестратор."""
    if name == "save_item":
        item = store.add_item(user_id, args.get("title", ""), args.get("due"), source, args.get("details", ""))
        return json.dumps({"saved": True, "id": item["id"], "title": item["title"], "due": item["due"]}, ensure_ascii=False)
    if name == "list_items":
        items = store.list_items(user_id)
        return json.dumps([{"id": i["id"], "title": i["title"], "due": i["due"]} for i in items], ensure_ascii=False)
    if name == "mark_done":
        item = store.set_done(user_id, args.get("item_id", ""))
        return json.dumps({"done": bool(item), "title": item["title"] if item else None}, ensure_ascii=False)
    return json.dumps({"error": f"неизвестный инструмент {name}"}, ensure_ascii=False)


def _client() -> OpenAI:
    folder_id = os.environ["folder_id"].strip()
    return OpenAI(
        base_url="https://ai.api.cloud.yandex.net/v1",
        api_key=os.environ["api_key"].strip(),
        project=folder_id,
        default_headers={"x-folder-id": folder_id},
    )


def _model() -> str:
    name = os.environ.get("YANDEX_MODEL", "deepseek-v4-flash")
    return name if name.startswith("gpt://") else f"gpt://{os.environ['folder_id'].strip()}/{name}"


def run_agent(user_id: int, text: str, source: str = "заметка", log=print) -> str:
    """Один прогон агента: от входящего сообщения до текста ответа."""
    client = _client()
    today = date.today()
    instructions = SYSTEM_PROMPT.format(today=today.isoformat(), weekday=WEEKDAYS[today.weekday()])

    log(f"→ модель: [{source}] {text[:80]!r}")
    response = client.responses.create(
        model=_model(),
        instructions=instructions,
        input=f"[{source}]\n{text}",
        tools=TOOLS,
        temperature=0.2,
        store=True,
    )

    tools_used = 0
    for step in range(1, MAX_STEPS + 1):
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not calls and tools_used == 0 and step == 1:
            log("! модель ответила без инструментов — повтор с tool_choice=required")
            response = client.responses.create(
                model=_model(),
                input=[{"role": "user", "content": "Ты не вызвал ни одного инструмента. Если в сообщении есть дело — save_item, "
                                                   "если вопрос о списке — list_items, если отметка о сделанном — list_items и mark_done."}],
                tools=TOOLS,
                tool_choice="required",
                previous_response_id=response.id,
                store=True,
            )
            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not calls:
            log(f"✓ шаг {step}: ответ без вызовов — стоп")
            break
        tools_used += len(calls)

        outputs = []
        for call in calls:
            args = json.loads(call.arguments or "{}")
            log(f"  шаг {step}: модель просит {call.name}({args})")
            result = run_tool(user_id, call.name, args, source)
            log(f"  шаг {step}: инструмент вернул {result[:120]}")
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": result})

        # результаты инструментов дописываются в контекст, модель вызывается снова
        response = client.responses.create(
            model=_model(),
            input=outputs,
            tools=TOOLS,
            previous_response_id=response.id,
            store=True,
        )
    else:
        log("! лимит шагов исчерпан")

    text = (response.output_text or "").strip().replace("**", "")
    return text or "Записал."
