import json
import os
import uuid
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["id", "title", "content", "due_date", "created_at"]


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
    return client.open_by_key(spreadsheet_id).sheet1


def get_all_todos():
    sheet = get_sheet()
    records = sheet.get_all_records(expected_headers=HEADERS)
    records.sort(key=lambda r: r.get("due_date") or "9999-99-99")
    return records


def add_todo(title, content, due_date):
    sheet = get_sheet()
    new_id = str(uuid.uuid4())
    sheet.append_row(
        [new_id, title, content, due_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    )
    return new_id


def get_todo(todo_id):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return None
    row = sheet.row_values(cell.row)
    return dict(zip(HEADERS, row))


def update_todo(todo_id, title, content, due_date):
    sheet = get_sheet()
    cell = sheet.find(todo_id, in_column=1)
    if not cell:
        return False
    sheet.update(f"B{cell.row}:D{cell.row}", [[title, content, due_date]])
    return True
