import os
from datetime import timedelta

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
    add_memo,
    add_task,
    build_report_sections,
    build_report_text,
    ensure_monthly_goal_initialized,
    get_all_settings,
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
    reorder_tasks,
    save_fixed_tasks,
    section_of,
    set_done,
    set_memo_done,
    split_fixed,
    submit_daily_report,
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
    text = request.form.get("text", "").strip()
    if not text:
        flash("メモが空です", "error")
    else:
        add_memo(text)
        flash("メモを追加しました", "success")
    return redirect(url_for("index"))


@app.route("/memo/toggle/<memo_id>", methods=["POST"])
def memo_toggle(memo_id):
    done = request.form.get("done") == "on"
    set_memo_done(memo_id, done, get_report_date())
    return redirect(url_for("index"))


@app.route("/memo/delete/<memo_id>", methods=["POST"])
def memo_delete(memo_id):
    if delete_memo(memo_id):
        flash("メモを削除しました", "success")
    else:
        flash("そのメモは見つかりませんでした", "error")
    return redirect(url_for("index"))


@app.route("/save-fixed/<section>", methods=["POST"])
def save_fixed(section):
    report_date = get_report_date()
    if section == SECTION_TODAY:
        task_date = report_date
    elif section == SECTION_TOMORROW:
        task_date = report_date + timedelta(days=1)
    else:
        flash("保存先が正しくありません", "error")
        return redirect(url_for("index"))

    entries = {}
    for i, category in enumerate(FIXED_CATEGORIES):
        detail = request.form.get(f"detail_{i}", "").strip()
        duration = request.form.get(f"duration_{i}", "").strip()
        entries[category] = (detail, duration)
    save_fixed_tasks(task_date.isoformat(), entries)
    flash("保存しました", "success")
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


@app.route("/toggle/<task_id>", methods=["POST"])
def toggle(task_id):
    done = request.form.get("done") == "on"
    set_done(task_id, done)
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
    all_settings = get_all_settings()
    report_date = get_report_date(all_settings)
    if request.method == "POST":
        set_monthly_goal(report_date, request.form.get("monthly_goal", "").strip())
        set_tomorrow_awareness(request.form.get("tomorrow_awareness", "").strip())
        flash("保存しました", "success")
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        month_label=f"{report_date.year}年{report_date.month}月",
        monthly_goal=ensure_monthly_goal_initialized(report_date, all_settings),
        tomorrow_awareness=get_tomorrow_awareness(all_settings),
    )


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
