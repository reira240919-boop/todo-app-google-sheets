import os

import requests

from sheets import format_duration, get_all_tasks, get_report_date, organize_tasks


def _format_line(task):
    mark = "✅ " if task["done"] else ""
    duration = f"（{format_duration(task['duration'])}）" if task["duration"] else ""
    return f"・{mark}{task['category']}➡︎{task['detail']}{duration}"


def build_message():
    report_date = get_report_date()
    today_tasks, _tomorrow, if_time_tasks = organize_tasks(get_all_tasks(), report_date)

    lines = [f"📋 **{report_date.month}/{report_date.day} のやること**"]
    if today_tasks:
        lines.extend(_format_line(t) for t in today_tasks)
    else:
        lines.append("今日のタスクはまだありません")

    if if_time_tasks:
        lines.append("\n⏳ **時間があれば**")
        lines.extend(_format_line(t) for t in if_time_tasks)

    return "\n".join(lines)


def post_to_discord():
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    message = build_message()
    response = requests.post(webhook_url, json={"content": message[:2000]}, timeout=10)
    response.raise_for_status()
