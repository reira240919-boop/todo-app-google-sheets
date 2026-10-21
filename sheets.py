import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
JST = ZoneInfo("Asia/Tokyo")

TASKS_SHEET = os.environ.get("TASKS_WORKSHEET_NAME", "daily_tasks")
SETTINGS_SHEET = os.environ.get("SETTINGS_WORKSHEET_NAME", "settings")
MEMOS_SHEET = os.environ.get("MEMOS_WORKSHEET_NAME", "memos")

TASK_HEADERS = [
    "id",
    "task_date",
    "category",
    "detail",
    "duration",
    "done",
    "if_time_allows",
    "sort_order",
    "created_at",
]
SETTINGS_HEADERS = ["key", "value"]
MEMO_HEADERS = ["id", "text", "created_at", "done", "done_on", "sort_order", "parent_id"]

# フォームの「どの欄に入れるか」
SECTION_TODAY = "today"
SECTION_TOMORROW = "tomorrow"
SECTION_IF_TIME = "if_time"

# 今日・明日の欄に毎日いつも出しておく固定のカテゴリ
FIXED_CATEGORIES = ["動画編集", "AIエンジニア", "X投稿"]
COUNT_CATEGORY = "X投稿"  # 内容ではなく件数を入れるカテゴリ


def _get_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


def _open_spreadsheet(retries=3, delay=1):
    """Googleスプレッドシート側の一時的な503エラーに備えて数回リトライする"""
    client = _get_client()
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    last_error = None
    for attempt in range(retries):
        try:
            return client.open_by_key(spreadsheet_id)
        except APIError as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_error


def _get_worksheet(name, headers):
    """タブを開く。まだ無ければ見出し行つきで新しく作る"""
    spreadsheet = _open_spreadsheet()
    try:
        return spreadsheet.worksheet(name)
    except WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=name, rows=200, cols=len(headers))
        sheet.update(values=[headers], range_name="A1")
        return sheet


_TAB_HEADERS = {}  # 下で定義したあとに埋める


def read_tabs(*names):
    """複数のタブを1回の読み取りでまとめて取ってくる（読み取り回数の上限対策）。
    {タブ名: 行のリスト（1行目は見出し）} を返す。タブが無ければ作ってから読み直す"""
    client = _get_client()
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    ranges = [f"'{name}'" for name in names]
    try:
        result = client.http_client.values_batch_get(spreadsheet_id, ranges)
    except APIError as e:
        if e.response.status_code != 400:  # 400 = まだ無いタブがある
            raise
        for name in names:
            _get_worksheet(name, _TAB_HEADERS[name])
        result = client.http_client.values_batch_get(spreadsheet_id, ranges)
    value_ranges = result.get("valueRanges", [])
    return {name: vr.get("values", []) for name, vr in zip(names, value_ranges)}


def _records(rows):
    """1行目を見出しにして、2行目以降を {見出し: 値} の辞書にする"""
    if not rows:
        return []
    headers = rows[0]
    return [{h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)} for row in rows[1:] if any(row)]


def tasks_sheet():
    return _get_worksheet(TASKS_SHEET, TASK_HEADERS)


def settings_sheet():
    return _get_worksheet(SETTINGS_SHEET, SETTINGS_HEADERS)


def format_duration(duration):
    """時間は数字だけ保存する。表示するときに「時間」を付ける（5 → 5時間）"""
    duration = str(duration).strip()
    if not duration:
        return ""
    if duration.endswith("時間"):
        return duration
    return f"{duration}時間"


def memos_sheet():
    sheet = _get_worksheet(MEMOS_SHEET, MEMO_HEADERS)
    # 列を後から増やしたので、古いタブなら列と見出しを足す
    if sheet.row_values(1) != MEMO_HEADERS:
        if sheet.col_count < len(MEMO_HEADERS):
            sheet.add_cols(len(MEMO_HEADERS) - sheet.col_count)
        sheet.update(values=[MEMO_HEADERS], range_name="A1")
    return sheet


# ---------- メモ（日報には載せない） ----------


def _memo_visible(memo, today):
    """チェックしていないメモはずっと出す。チェックしたメモはその日だけ出して、日報の日が進んだら隠す"""
    return not memo["done"] or memo["done_on"] >= today


def get_memos(report_date, rows=None):
    """メモの一覧。メモの中のリストは、それぞれのメモの "items" に入れて返す"""
    if rows is None:
        rows = read_tabs(MEMOS_SHEET)[MEMOS_SHEET]
    today = report_date.isoformat()
    all_memos = []
    for r in _records(rows):
        all_memos.append(
            {
                "id": str(r.get("id", "")),
                "text": str(r.get("text", "")),
                "done": _is_true(r.get("done", "")),
                "done_on": str(r.get("done_on", "")).strip(),
                "sort_order": r.get("sort_order", ""),
                "created_at": r.get("created_at", ""),
                "parent_id": str(r.get("parent_id", "")).strip(),
                "items": [],
            }
        )
    all_memos.sort(key=_order_key)

    memos = [m for m in all_memos if not m["parent_id"] and _memo_visible(m, today)]
    by_id = {m["id"]: m for m in memos}
    for m in all_memos:
        parent = by_id.get(m["parent_id"])
        if parent and _memo_visible(m, today):
            parent["items"].append(m)
    return memos


def add_memos(text, parent_id=""):
    """改行で区切って、1行を1つのメモとして追加する（parent_id があれば、そのメモの中のリストに入れる）。
    追加した件数を返す"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    memos_sheet().append_rows([[str(uuid.uuid4()), line, now, "FALSE", "", "", parent_id] for line in lines])
    return len(lines)


def update_memo(memo_id, text):
    sheet = memos_sheet()
    cell = sheet.find(memo_id, in_column=1)
    if not cell:
        return False
    sheet.update(values=[[text]], range_name=f"B{cell.row}")
    return True


def set_memos_done(changes, report_date):
    """{メモのid: チェックしたか} をまとめて保存する。保存できた件数を返す"""
    sheet = memos_sheet()
    id_to_row = {value: i + 1 for i, value in enumerate(sheet.col_values(1)) if i > 0}
    updates = [
        {
            "range": f"D{id_to_row[memo_id]}:E{id_to_row[memo_id]}",
            "values": [[_bool_str(done), report_date.isoformat() if done else ""]],
        }
        for memo_id, done in changes.items()
        if memo_id in id_to_row
    ]
    if updates:
        sheet.batch_update(updates)
    return len(updates)


def reorder_memos(ordered_ids):
    """ドラッグ&ドロップで決めた新しい並び順を sort_order 列にまとめて保存する"""
    sheet = memos_sheet()
    id_to_row = {value: i + 1 for i, value in enumerate(sheet.col_values(1)) if i > 0}
    updates = [
        {"range": f"F{id_to_row[memo_id]}", "values": [[index]]}
        for index, memo_id in enumerate(ordered_ids)
        if memo_id in id_to_row
    ]
    if updates:
        sheet.batch_update(updates)
    return True


def delete_memo(memo_id):
    """メモを消す。中のリストも一緒に消す"""
    sheet = memos_sheet()
    rows = sheet.get_all_values()
    targets = [
        i + 1
        for i, row in enumerate(rows)
        if i > 0 and row and (row[0] == memo_id or (len(row) > 6 and row[6] == memo_id))
    ]
    if not targets:
        return False
    # 下の行から消すと、上の行の番号がずれない
    for row_number in sorted(targets, reverse=True):
        sheet.delete_rows(row_number)
    return True


def _is_true(value):
    return str(value).strip().upper() == "TRUE"


def _bool_str(value):
    return "TRUE" if value else "FALSE"


# ---------- settings（report_date など） ----------


def get_setting(key):
    sheet = settings_sheet()
    cell = sheet.find(key, in_column=1)
    if not cell:
        return None
    row = sheet.row_values(cell.row)
    return row[1] if len(row) > 1 else ""


def set_setting(key, value):
    sheet = settings_sheet()
    cell = sheet.find(key, in_column=1)
    if cell:
        sheet.update(values=[[value]], range_name=f"B{cell.row}")
    else:
        sheet.append_row([key, value])


def get_all_settings(rows=None):
    """settings タブを {key: value} にする。rows を渡せば読み直さない"""
    if rows is None:
        rows = read_tabs(SETTINGS_SHEET)[SETTINGS_SHEET]
    return {row[0]: (row[1] if len(row) > 1 else "") for row in rows[1:] if row and row[0]}


# ---------- 今月の目標・1日の振り返り・明日意識すること ----------


def _goal_key(report_date):
    return f"monthly_goal_{report_date:%Y-%m}"


def _reflection_key(report_date):
    return f"reflection_{report_date.isoformat()}"


AWARENESS_KEY = "tomorrow_awareness"


def _latest_previous_goal(settings, report_date):
    """当月より前で、いちばん新しい月の目標（空でないもの）"""
    current = _goal_key(report_date)
    previous = sorted(
        (k for k, v in settings.items() if k.startswith("monthly_goal_") and k < current and str(v).strip()),
        reverse=True,
    )
    return settings[previous[0]] if previous else ""


def get_monthly_goal(report_date, settings=None):
    """当月の目標。まだ無ければ前月の本文を返す（新しい月でも空にしない）"""
    if settings is None:
        settings = get_all_settings()
    key = _goal_key(report_date)
    if key in settings:
        return settings[key]
    return _latest_previous_goal(settings, report_date)


def set_monthly_goal(report_date, text):
    set_setting(_goal_key(report_date), text)


def ensure_monthly_goal_initialized(report_date, settings=None):
    """当月のキーが無いときだけ、前月の本文をコピーして保存する。画面の初期表示用に本文を返す"""
    if settings is None:
        settings = get_all_settings()
    key = _goal_key(report_date)
    if key in settings:
        return settings[key]
    previous = _latest_previous_goal(settings, report_date)
    if previous:
        set_setting(key, previous)
    return previous


# ---------- 月ごとの目標と、月末の振り返り ----------

REVIEW_MARKS = {"o": "⭕️", "t": "🔺", "x": "❌"}


def _review_key(month):
    return f"goal_review_{month:%Y-%m}"


def goal_months(settings):
    """目標か振り返りが保存されている月（各月の1日）を古い順に返す"""
    months = set()
    for key in settings:
        for prefix in ("monthly_goal_", "goal_review_"):
            if key.startswith(prefix):
                try:
                    months.add(datetime.strptime(key[len(prefix):], "%Y-%m").date())
                except ValueError:
                    pass
    return sorted(months)


def has_monthly_goal(month, settings):
    return _goal_key(month) in settings


def get_goal_review(month, settings):
    """その月の振り返り。{"marks": [[目標の行, "o"/"t"/"x"/""], ...], "comment": ""}。無ければ None"""
    raw = settings.get(_review_key(month))
    if not raw:
        return None
    try:
        review = json.loads(raw)
    except ValueError:
        return None
    return {"marks": review.get("marks") or [], "comment": review.get("comment") or ""}


def set_goal_review(month, marks, comment):
    value = json.dumps({"marks": marks, "comment": comment}, ensure_ascii=False)
    set_setting(_review_key(month), value)


def review_score(review):
    """一覧に出す「⭕️2 🔺1 ❌1」"""
    counts = {key: 0 for key in REVIEW_MARKS}
    for _, mark in review["marks"]:
        if mark in counts:
            counts[mark] += 1
    return " ".join(f"{symbol}{counts[key]}" for key, symbol in REVIEW_MARKS.items())


def get_reflection(report_date, settings=None):
    if settings is None:
        settings = get_all_settings()
    return settings.get(_reflection_key(report_date), "")


def set_reflection(report_date, text):
    set_setting(_reflection_key(report_date), text)


def get_tomorrow_awareness(settings=None):
    if settings is None:
        settings = get_all_settings()
    return settings.get(AWARENESS_KEY, "")


def set_tomorrow_awareness(text):
    set_setting(AWARENESS_KEY, text)


def get_report_date(settings=None):
    """日報の対象日。提出（Phase 2）まで壁時計が日付を跨いでも進めない。
    まだ保存されていなければ、日本時間の今日で初期化して保存する"""
    if settings is None:
        settings = get_all_settings()
    value = settings.get("report_date")
    if value:
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError:
            pass
    today = datetime.now(JST).date()
    set_setting("report_date", today.isoformat())
    return today


# ---------- タスク ----------


def _normalize(record):
    task = {h: record.get(h, "") for h in TASK_HEADERS}
    task["id"] = str(task["id"])
    task["category"] = str(task["category"]).strip()
    task["detail"] = str(task["detail"]).strip()
    task["task_date"] = str(task["task_date"]).strip()
    task["duration"] = str(task["duration"]).strip()
    task["done"] = _is_true(task["done"])
    task["if_time_allows"] = _is_true(task["if_time_allows"])
    return task


def get_all_tasks(rows=None):
    if rows is None:
        rows = read_tabs(TASKS_SHEET)[TASKS_SHEET]
    return [_normalize(r) for r in _records(rows)]


def _order_key(t):
    """手動並び替え(sort_order)があれば優先し、なければ作成順にする"""
    order = str(t.get("sort_order", "")).strip()
    if order:
        try:
            return (0, float(order), t.get("created_at", ""))
        except ValueError:
            pass
    return (1, 0, str(t.get("created_at", "")))


def organize_tasks(tasks, report_date):
    """今日 / 明日やること（必須） / 時間があれば の3つに分ける"""
    today = report_date.isoformat()
    tomorrow = (report_date + timedelta(days=1)).isoformat()

    today_tasks, tomorrow_tasks, if_time_tasks = [], [], []
    for t in tasks:
        if t["if_time_allows"]:
            # 未完了なら task_date に関係なく毎日この欄に出す
            if not t["done"]:
                if_time_tasks.append(t)
        elif t["task_date"] == today:
            today_tasks.append(t)
        elif t["task_date"] == tomorrow:
            tomorrow_tasks.append(t)

    for rows in (today_tasks, tomorrow_tasks, if_time_tasks):
        rows.sort(key=_order_key)
    return today_tasks, tomorrow_tasks, if_time_tasks


def split_fixed(tasks):
    """固定カテゴリの行（カテゴリごとに1つ）と、それ以外のタスクに分ける"""
    fixed, others = {}, []
    for t in tasks:
        if t["category"] in FIXED_CATEGORIES and t["category"] not in fixed:
            fixed[t["category"]] = t
        else:
            others.append(t)
    return fixed, others


def section_of(task, report_date):
    """編集フォームで、いまどの欄のタスクかを初期選択するため"""
    if task["if_time_allows"]:
        return SECTION_IF_TIME
    if task["task_date"] == (report_date + timedelta(days=1)).isoformat():
        return SECTION_TOMORROW
    return SECTION_TODAY


def _date_and_flag(section, report_date):
    if section == SECTION_TOMORROW:
        return (report_date + timedelta(days=1)).isoformat(), False
    if section == SECTION_IF_TIME:
        return report_date.isoformat(), True
    return report_date.isoformat(), False


def add_task(category, detail, duration, section, report_date, done=False):
    sheet = tasks_sheet()
    task_date, if_time = _date_and_flag(section, report_date)
    new_id = str(uuid.uuid4())
    sheet.append_row(
        [
            new_id,
            task_date,
            category,
            detail,
            duration,
            _bool_str(done),
            _bool_str(if_time),
            "",
            datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        ]
    )
    return new_id


def get_task(task_id):
    sheet = tasks_sheet()
    cell = sheet.find(task_id, in_column=1)
    if not cell:
        return None
    row = sheet.row_values(cell.row)
    return _normalize({h: (row[i] if i < len(row) else "") for i, h in enumerate(TASK_HEADERS)})


def update_task(task_id, category, detail, duration, section, report_date):
    sheet = tasks_sheet()
    cell = sheet.find(task_id, in_column=1)
    if not cell:
        return False
    row = cell.row
    task_date, if_time = _date_and_flag(section, report_date)
    sheet.batch_update(
        [
            {"range": f"B{row}:E{row}", "values": [[task_date, category, detail, duration]]},
            {"range": f"G{row}", "values": [[_bool_str(if_time)]]},
        ]
    )
    return True


def save_fixed_tasks(entries_by_date):
    """固定カテゴリの行をまとめて保存する（今日と明日を一度に保存できる）。
    entries_by_date は {日付: {カテゴリ: (内容, 時間)}}。内容が空なら、その日のその行は消す"""
    sheet = tasks_sheet()
    existing = {}  # (日付, カテゴリ) -> 行番号
    for i, record in enumerate(sheet.get_all_records()):
        t = _normalize(record)
        key = (t["task_date"], t["category"])
        if (
            t["task_date"] in entries_by_date
            and not t["if_time_allows"]
            and t["category"] in entries_by_date[t["task_date"]]
            and key not in existing
        ):
            existing[key] = i + 2  # 1行目は見出し

    updates, delete_rows, new_rows = [], [], []
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    for task_date, entries in entries_by_date.items():
        for order, category in enumerate(FIXED_CATEGORIES):
            if category not in entries:
                continue
            detail, duration = entries[category]
            row = existing.get((task_date, category))
            if row and detail:
                updates.append({"range": f"D{row}:E{row}", "values": [[detail, duration]]})
            elif row:
                delete_rows.append(row)
            elif detail:
                new_rows.append(
                    [str(uuid.uuid4()), task_date, category, detail, duration, "FALSE", "FALSE", order, now]
                )

    if updates:
        sheet.batch_update(updates)
    # 下の行から消すと、上の行番号がずれない
    for row in sorted(delete_rows, reverse=True):
        sheet.delete_rows(row)
    if new_rows:
        sheet.append_rows(new_rows)
    return True


def set_tasks_done(changes):
    """{タスクのid: 完了したか} をまとめて保存する。保存できた件数を返す"""
    sheet = tasks_sheet()
    id_to_row = {value: i + 1 for i, value in enumerate(sheet.col_values(1)) if i > 0}
    updates = [
        {"range": f"F{id_to_row[task_id]}", "values": [[_bool_str(done)]]}
        for task_id, done in changes.items()
        if task_id in id_to_row
    ]
    if updates:
        sheet.batch_update(updates)
    return len(updates)


def reorder_tasks(ordered_ids):
    """ドラッグ&ドロップで決めた新しい並び順を sort_order 列にまとめて保存する"""
    sheet = tasks_sheet()
    id_column = sheet.col_values(1)
    id_to_row = {value: i + 1 for i, value in enumerate(id_column) if i > 0}

    updates = []
    for index, task_id in enumerate(ordered_ids):
        row = id_to_row.get(task_id)
        if row:
            updates.append({"range": f"H{row}", "values": [[index]]})
    if updates:
        sheet.batch_update(updates)
    return True


def delete_task(task_id):
    sheet = tasks_sheet()
    cell = sheet.find(task_id, in_column=1)
    if not cell:
        return False
    sheet.delete_rows(cell.row)
    return True


# ---------- 日報 ----------

NONE_LINE = "・なし"


def format_task_line(task):
    """日報の1行。X投稿は件数、それ以外は ・カテゴリ➡︎内容（N時間）"""
    detail = task["detail"]
    if task["category"] == COUNT_CATEGORY:
        return f"・{COUNT_CATEGORY}{detail}件" if detail else ""
    line = f"・{task['category']}➡︎{detail}"
    if task["duration"]:
        line += f"（{format_duration(task['duration'])}）"
    return line


def _fixed_then_others(fixed, others):
    return [fixed[c] for c in FIXED_CATEGORIES if c in fixed] + others


def build_report_sections(report_date, tasks):
    """日報に載せる行を集める。「時間があれば」はどちらにも入れない。
    固定3行は書いてあれば「やった」とみなし、それ以外は完了チェックが付いたものだけ"""
    today_tasks, tomorrow_tasks, _if_time = organize_tasks(tasks, report_date)

    today_fixed, today_others = split_fixed(today_tasks)
    today_done = _fixed_then_others(today_fixed, [t for t in today_others if t["done"]])
    tomorrow_fixed, tomorrow_others = split_fixed(tomorrow_tasks)
    tomorrow_all = _fixed_then_others(tomorrow_fixed, tomorrow_others)

    return {
        "header_label": f"{report_date.month}/{report_date.day}",
        "today_done_lines": [line for line in map(format_task_line, today_done) if line],
        "tomorrow_lines": [line for line in map(format_task_line, tomorrow_all) if line],
    }


def build_report_text(sections, monthly_goal, reflection, awareness):
    today_lines = sections["today_done_lines"] or [NONE_LINE]
    tomorrow_lines = sections["tomorrow_lines"] or [NONE_LINE]
    parts = [
        f"【{sections['header_label']}日報】",
        "◼️今月の目標",
        monthly_goal.strip() or NONE_LINE,
        "",
        "◎進捗状況",
        "◼️今日したこと",
        *today_lines,
        "",
        "◼️1日の振り返り",
        reflection.strip() or "（振り返りを入力してください）",
        "",
        "◼️明日やること",
        *tomorrow_lines,
        "",
        "◼️明日意識すること",
        awareness.strip() or "（設定で入力してください）",
    ]
    return "\n".join(parts)


def submit_daily_report():
    """日報を提出して、日報の日を1日進める。新しい report_date を返す。
    途中で失敗したときは report_date を変えない（最後に書き換える）"""
    data = read_tabs(SETTINGS_SHEET, TASKS_SHEET)
    report_date = get_report_date(get_all_settings(data[SETTINGS_SHEET]))
    next_date = report_date + timedelta(days=1)
    tasks = get_all_tasks(data[TASKS_SHEET])

    today_tasks, _tomorrow, _if_time = organize_tasks(tasks, report_date)
    _fixed, today_others = split_fixed(today_tasks)

    # 今日の必須タスクで未完了のものを、新しい「今日」へコピーする（元の行は履歴として残す）
    # 固定3行は明日の欄がそのまま新しい「今日」になるのでコピーしない
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    new_rows = [
        [
            str(uuid.uuid4()),
            next_date.isoformat(),
            t["category"],
            t["detail"],
            t["duration"],
            "FALSE",
            "FALSE",
            t["sort_order"],
            now,
        ]
        for t in today_others
        if not t["done"]
    ]
    if new_rows:
        tasks_sheet().append_rows(new_rows)

    set_setting("report_date", next_date.isoformat())
    return next_date


_TAB_HEADERS.update(
    {TASKS_SHEET: TASK_HEADERS, SETTINGS_SHEET: SETTINGS_HEADERS, MEMOS_SHEET: MEMO_HEADERS}
)
