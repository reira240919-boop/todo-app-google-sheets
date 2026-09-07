import json
import os
import uuid
from collections import OrderedDict
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "id",
    "client_name",
    "content",
    "due_date",
    "created_at",
    "done",
    "category",
    "important",
    "progress",
    "is_test_case",
]
CATEGORIES = ["ショート", "ロング"]
PROGRESS_STAGES = ["初稿編集中", "初稿提出済み", "修正依頼", "修正分提出済み"]
NO_DATE_LABEL = "期日未設定"


def _get_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet():
    client = _get_client()
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet_name = os.environ.get("WORKSHEET_NAME")
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    return spreadsheet.sheet1


def get_all_todos():
    sheet = get_sheet()
    raw_records = sheet.get_all_records()
    records = [{h: r.get(h, "") for h in HEADERS} for r in raw_records]
    return records


def organize_todos(todos):
    """重要(未完了) / 月ごと(未完了) / 完了 の3グループに分ける"""
    important, others, done = [], [], []
    for t in todos:
        if t.get("done") == "TRUE":
            done.append(t)
        elif t.get("important") == "TRUE":
            important.append(t)
        else:
            others.append(t)

    important.sort(key=lambda t: t.get("due_date") or "9999-99-99")
    done.sort(key=lambda t: t.get("due_date") or "9999-99-99")

    groups = OrderedDict()
    for t in sorted(others, key=lambda t: t.get("due_date") or "9999-99-99"):
        due = t.get("due_date")
        key = due[:7] if due else NO_DATE_LABEL
        groups.setdefault(key, []).append(t)

    month_groups = []
    for key in sorted(k for k in groups if k != NO_DATE_LABEL):
        year, month = key.split("-")
        month_groups.append((f"{year}年{int(month)}月", groups[key]))
    if NO_DATE_LABEL in groups:
        month_groups.append((NO_DATE_LABEL, groups[NO_DATE_LABEL]))

    return important, month_groups, done


def add_todo(client_name, content, due_date, category, important, progress, is_test_case):
    sheet = get_sheet()
    new_id = str(uuid.uuid4())
    sheet.append_row(
        [
            new_id,
            client_name,
            content,
            due_date,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "FALSE",
            category,
            "TRUE" if important else "FALSE",
            progress,
            "TRUE" if is_test_case else "FALSE",
        ]
    )
    return new_id


def get_todo(todo_id):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return None
    row = sheet.row_values(cell.row)
    return {h: (row[i] if i < len(row) else "") for i, h in enumerate(HEADERS)}


def update_todo(todo_id, client_name, content, due_date, category, important, progress, is_test_case):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return False
    row = cell.row
    sheet.update(f"B{row}:D{row}", [[client_name, content, due_date]])
    sheet.update(
        f"G{row}:J{row}",
        [[category, "TRUE" if important else "FALSE", progress, "TRUE" if is_test_case else "FALSE"]],
    )
    return True


def set_done(todo_id, done):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return False
    sheet.update(f"F{cell.row}", [["TRUE" if done else "FALSE"]])
    return True


def delete_todo(todo_id):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return False
    sheet.delete_rows(cell.row)
    return True
