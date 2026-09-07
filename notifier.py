import os

import requests

from sheets import get_all_todos, organize_todos


def _format_line(todo):
    due = todo.get("due_date") or "期日未設定"
    category = todo.get("category") or "未分類"
    progress = todo.get("progress") or "進捗未設定"
    mark = "⭐ " if todo.get("important") == "TRUE" else ""
    test_mark = "🧪" if todo.get("is_test_case") == "TRUE" else ""
    return f"・{mark}{todo['client_name']}{test_mark}（{due}／{category}／{progress}）"


def build_message():
    todos = get_all_todos()
    important, month_groups, _done = organize_todos(todos)

    if not important and not any(rows for _, rows in month_groups):
        return "📋 **今日のTodoリスト**\n未完了のやることはありません🎉"

    lines = ["📋 **今日のTodoリスト**"]

    if important:
        lines.append("\n📌 **重要**")
        lines.extend(_format_line(t) for t in important)

    for label, rows in month_groups:
        lines.append(f"\n🗓 **{label}**")
        lines.extend(_format_line(t) for t in rows)

    return "\n".join(lines)


def post_to_discord():
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    message = build_message()
    response = requests.post(webhook_url, json={"content": message[:2000]}, timeout=10)
    response.raise_for_status()
