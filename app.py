import json
import os
from datetime import date, datetime, timedelta

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
    load_dotenv()
except ImportError:
    pass

from notifier import post_to_discord
from sheets import (
    COUNT_CATEGORY,
    FIXED_CATEGORIES,
    SECTION_IF_TIME,
    SECTION_TODAY,
    SECTION_TOMORROW,
    add_memos,
    add_task,
    build_report_sections,
    build_report_text,
    REVIEW_MARKS,
    ensure_monthly_goal_initialized,
    get_all_settings,
    get_goal_review,
    goal_months,
    has_monthly_goal,
    review_score,
    set_goal_review,
    get_monthly_goal,
    get_reflection,
    get_tomorrow_awareness,
    set_monthly_goal,
    set_reflection,
    set_tomorrow_awareness,
    delete_memo,
    delete_task,
    format_duration,
    MEMOS_SHEET,
    SETTINGS_SHEET,
    TASKS_SHEET,
    get_all_tasks,
    get_memos,
    get_report_date,
    get_task,
    read_tabs,
    organize_tasks,
    reorder_memos,
    reorder_tasks,
    save_fixed_tasks,
    section_of,
    set_memos_done,
    set_tasks_done,
    split_fixed,
    submit_daily_report,
    update_memo,
    update_task,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.add_template_filter(format_duration, "hours")

SECTIONS = [
    (SECTION_TODAY, "今日"),
    (SECTION_TOMORROW, "明日やること（必須）"),
    (SECTION_IF_TIME, "時間があれば"),
]
SECTION_KEYS = [key for key, _ in SECTIONS]
WEEKDAYS = "月火水木金土日"


def _format_date(d):
    return f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）"


def _form_data():
    section = request.form.get("section", SECTION_TODAY)
    if section not in SECTION_KEYS:
        section = SECTION_TODAY
    return {
        "category": request.form.get("category", "").strip(),
        "detail": request.form.get("detail", "").strip(),
        "duration": request.form.get("duration", "").strip(),
        "section": section,
        # 「今日」に後から足すのは、やり終えたことが多いので完了で登録できるようにする
        "done": section == SECTION_TODAY and request.form.get("done") == "on",
    }


def _render_form(mode, task, task_id=None):
    return render_template("form.html", mode=mode, task=task, task_id=task_id, sections=SECTIONS)


@app.route("/")
def index():
    # 3つのタブを1回の読み取りでまとめて取る
    data = read_tabs(SETTINGS_SHEET, TASKS_SHEET, MEMOS_SHEET)
    report_date = get_report_date(get_all_settings(data[SETTINGS_SHEET]))
    today_tasks, tomorrow_tasks, if_time_tasks = organize_tasks(get_all_tasks(data[TASKS_SHEET]), report_date)
    today_fixed, today_others = split_fixed(today_tasks)
    tomorrow_fixed, tomorrow_others = split_fixed(tomorrow_tasks)
    return render_template(
        "index.html",
        report_date_label=_format_date(report_date),
        tomorrow_label=_format_date(report_date + timedelta(days=1)),
        fixed_categories=FIXED_CATEGORIES,
        count_category=COUNT_CATEGORY,
        today_fixed=today_fixed,
        today_tasks=today_others,
        tomorrow_fixed=tomorrow_fixed,
        tomorrow_tasks=tomorrow_others,
        if_time_tasks=if_time_tasks,
        memos=get_memos(report_date, data[MEMOS_SHEET]),
    )


@app.route("/memo/add", methods=["POST"])
def memo_add():
    count = add_memos(request.form.get("text", ""))
    if count == 0:
        flash("メモが空です", "error")
    else:
        flash(f"メモを{count}件追加しました" if count > 1 else "メモを追加しました", "success")
    return redirect(url_for("index"))


@app.route("/memo/<memo_id>/items", methods=["POST"])
def memo_add_items(memo_id):
    count = add_memos(request.form.get("text", ""), parent_id=memo_id)
    if count == 0:
        flash("リストが空です", "error")
    else:
        flash(f"リストに{count}件追加しました", "success")
    return redirect(url_for("index"))


@app.route("/memo/edit/<memo_id>", methods=["POST"])
def memo_edit(memo_id):
    # メモは1行ずつなので、改行が入っていたら空白にする
    text = " ".join(request.form.get("text", "").splitlines()).strip()
    if not text:
        flash("メモが空です", "error")
    elif update_memo(memo_id, text):
        flash("メモを修正しました", "success")
    else:
        flash("そのメモは見つかりませんでした", "error")
    return redirect(url_for("index"))


@app.route("/memo/reorder", methods=["POST"])
def memo_reorder():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"status": "error", "message": "invalid ids"}), 400
    reorder_memos(ids)
    return jsonify({"status": "ok"})


@app.route("/memo/delete/<memo_id>", methods=["POST"])
def memo_delete(memo_id):
    if delete_memo(memo_id):
        flash("メモを削除しました", "success")
    else:
        flash("そのメモは見つかりませんでした", "error")
    return redirect(url_for("index"))


@app.route("/save-fixed", methods=["POST"])
def save_fixed():
    # 「今日」「明日」のどちらの保存ボタンを押しても、両方の欄をまとめて保存する
    report_date = get_report_date()
    dates = {
        SECTION_TODAY: report_date,
        SECTION_TOMORROW: report_date + timedelta(days=1),
    }
    entries_by_date = {}
    for section, task_date in dates.items():
        entries = {}
        for i, category in enumerate(FIXED_CATEGORIES):
            detail = request.form.get(f"{section}_detail_{i}")
            if detail is None:  # その欄が送られてこなかったときは触らない
                continue
            duration = request.form.get(f"{section}_duration_{i}", "").strip()
            entries[category] = (detail.strip(), duration)
        if entries:
            entries_by_date[task_date.isoformat()] = entries
    save_fixed_tasks(entries_by_date)
    flash("今日と明日の内容を保存しました", "success")
    return redirect(url_for("index"))


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        data = _form_data()
        if not data["category"] or not data["detail"]:
            flash("カテゴリと内容は必須です", "error")
            return _render_form("add", data)
        add_task(
            data["category"], data["detail"], data["duration"], data["section"], get_report_date(), data["done"]
        )
        flash("追加しました", "success")
        return redirect(url_for("index"))

    section = request.args.get("section", SECTION_IF_TIME)
    if section not in SECTION_KEYS:
        section = SECTION_IF_TIME
    return _render_form("add", {"category": "", "detail": "", "duration": "", "section": section, "done": True})


@app.route("/edit/<task_id>", methods=["GET", "POST"])
def edit(task_id):
    if request.method == "POST":
        data = _form_data()
        if not data["category"] or not data["detail"]:
            flash("カテゴリと内容は必須です", "error")
            return _render_form("edit", data, task_id)
        if update_task(task_id, data["category"], data["detail"], data["duration"], data["section"], get_report_date()):
            flash("保存しました", "success")
        else:
            flash("そのタスクは見つかりませんでした", "error")
        return redirect(url_for("index"))

    task = get_task(task_id)
    if task is None:
        flash("そのタスクは見つかりませんでした", "error")
        return redirect(url_for("index"))
    task["section"] = section_of(task, get_report_date())
    return _render_form("edit", task, task_id)


def _checked_changes(name):
    """画面から送られた {"id": true/false} を受け取る。形がおかしいものは捨てる"""
    try:
        data = json.loads(request.form.get(name) or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): bool(v) for k, v in data.items()}


@app.route("/checks", methods=["POST"])
def save_checks():
    # ホームでチェックしたタスクとメモを、まとめて1回で保存する
    tasks = _checked_changes("tasks")
    memos = _checked_changes("memos")
    count = 0
    if tasks:
        count += set_tasks_done(tasks)
    if memos:
        count += set_memos_done(memos, get_report_date())
    if count:
        flash(f"チェックを{count}件保存しました", "success")
    else:
        flash("保存するチェックがありませんでした", "error")
    return redirect(url_for("index"))


@app.route("/reorder", methods=["POST"])
def reorder():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"status": "error", "message": "invalid ids"}), 400
    reorder_tasks(ids)
    return jsonify({"status": "ok"})


@app.route("/delete/<task_id>", methods=["POST"])
def delete(task_id):
    if delete_task(task_id):
        flash("削除しました", "success")
    else:
        flash("そのタスクは見つかりませんでした", "error")
    return redirect(url_for("index"))


@app.route("/report")
def report():
    data = read_tabs(SETTINGS_SHEET, TASKS_SHEET)
    settings = get_all_settings(data[SETTINGS_SHEET])
    report_date = get_report_date(settings)
    sections = build_report_sections(report_date, get_all_tasks(data[TASKS_SHEET]))
    reflection = get_reflection(report_date, settings)
    report_text = build_report_text(
        sections,
        get_monthly_goal(report_date, settings),
        reflection,
        get_tomorrow_awareness(settings),
    )
    return render_template(
        "report.html",
        report_date_label=_format_date(report_date),
        report_text=report_text,
        reflection=reflection,
    )


@app.route("/report/reflection", methods=["POST"])
def report_reflection():
    set_reflection(get_report_date(), request.form.get("reflection", "").strip())
    flash("振り返りを保存しました", "success")
    return redirect(url_for("report"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        set_tomorrow_awareness(request.form.get("tomorrow_awareness", "").strip())
        flash("保存しました", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", tomorrow_awareness=get_tomorrow_awareness())


def _add_month(month, n):
    total = month.year * 12 + month.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


def _parse_month(text):
    try:
        return datetime.strptime(text or "", "%Y-%m").date()
    except ValueError:
        return None


def _goal_month_or_none(text, this_month):
    """URL の月を確かめる。先に進めるのは来月まで"""
    month = _parse_month(text)
    if month is None or month > _add_month(this_month, 1):
        return None
    return month


def _month_status(month, this_month, review):
    if month > this_month:
        return "来月"
    if review:
        return "振り返り済み"
    return "今月" if month == this_month else "振り返りまだ"


@app.route("/goals")
def goals():
    all_settings = get_all_settings()
    this_month = get_report_date(all_settings).replace(day=1)
    next_month = _add_month(this_month, 1)
    month = _goal_month_or_none(request.args.get("month"), this_month) or this_month

    if month == this_month:
        goal = ensure_monthly_goal_initialized(month, all_settings)
    else:
        # 来月でまだ保存していなければ、今月の目標を入れておく（保存するまでは書き込まない）
        goal = get_monthly_goal(month, all_settings)
    goal_saved = has_monthly_goal(month, all_settings) or month == this_month
    review = get_goal_review(month, all_settings)

    # 目標の行ごとに、前に選んだ ⭕️🔺❌ を付ける（目標の文を直した行は未選択に戻る）
    saved_marks = dict((line, mark) for line, mark in review["marks"]) if review else {}
    goal_lines = [
        {"text": line, "mark": saved_marks.get(line, ""), "sub": line.startswith("⭐")}
        for line in (l.strip() for l in goal.splitlines())
        if line
    ]

    months = set(goal_months(all_settings)) | {this_month}
    months = {m for m in months if m <= next_month}
    if month == next_month:
        months.add(next_month)
    earliest = min(months)
    history = []
    for m in sorted(months, reverse=True):
        r = get_goal_review(m, all_settings)
        history.append({
            "key": f"{m:%Y-%m}",
            "label": f"{m.year}年{m.month}月",
            "status": _month_status(m, this_month, r),
            "score": review_score(r) if r else "",
            "current": m == month,
        })

    return render_template(
        "goals.html",
        month_key=f"{month:%Y-%m}",
        month_label=f"{month.year}年{month.month}月",
        month_num=month.month,
        status=_month_status(month, this_month, review),
        reviewed=review is not None,
        is_future=month > this_month,
        is_this_month=month == this_month,
        goal=goal,
        goal_saved=goal_saved,
        goal_lines=goal_lines,
        comment=review["comment"] if review else "",
        marks=REVIEW_MARKS,
        prev_key=f"{_add_month(month, -1):%Y-%m}" if month > earliest else None,
        next_key=f"{_add_month(month, 1):%Y-%m}" if month < next_month else None,
        next_num=next_month.month,
        next_month_key=f"{next_month:%Y-%m}",
        history=history,
    )


@app.route("/goals/<month_key>", methods=["POST"])
def goals_save(month_key):
    this_month = get_report_date().replace(day=1)
    month = _goal_month_or_none(month_key, this_month)
    if month is None:
        flash("その月の目標は保存できません", "error")
        return redirect(url_for("goals"))
    set_monthly_goal(month, request.form.get("monthly_goal", "").strip())
    flash(f"{month.month}月の目標を保存しました", "success")
    return redirect(url_for("goals", month=month_key))


@app.route("/goals/<month_key>/review", methods=["POST"])
def goals_review(month_key):
    all_settings = get_all_settings()
    this_month = get_report_date(all_settings).replace(day=1)
    month = _goal_month_or_none(month_key, this_month)
    if month is None or month > this_month:
        flash("まだ始まっていない月は振り返れません", "error")
        return redirect(url_for("goals"))
    goal = get_monthly_goal(month, all_settings)
    lines = [line.strip() for line in goal.splitlines() if line.strip()]
    marks = []
    for i, line in enumerate(lines):
        mark = request.form.get(f"mark_{i}", "")
        marks.append([line, mark if mark in REVIEW_MARKS else ""])
    set_goal_review(month, marks, request.form.get("comment", "").strip())
    flash(f"{month.month}月の振り返りを保存しました", "success")
    return redirect(url_for("goals", month=month_key) + "#review")


@app.route("/report/submit", methods=["POST"])
def report_submit():
    try:
        new_date = submit_daily_report()
    except Exception:
        app.logger.exception("日報の提出に失敗しました")
        flash("提出できませんでした。日報の日はそのままです。少し待ってからもう一度お試しください", "error")
        return redirect(url_for("report"))
    flash(f"日報を提出しました。日報の日を {_format_date(new_date)} に進めました", "success")
    return redirect(url_for("index"))


@app.route("/cron/notify-discord", methods=["GET", "POST"])
def cron_notify_discord():
    secret = os.environ.get("CRON_SECRET")
    if secret and request.headers.get("Authorization") != f"Bearer {secret}":
        return {"error": "unauthorized"}, 401
    post_to_discord()
    return {"status": "ok"}


if __name__ == "__main__":
    # ポート5000はmacOSのAirPlayレシーバーと衝突しやすいため5001を使用
    app.run(debug=True, port=5001)
