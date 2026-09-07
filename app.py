import os

from flask import Flask, flash, redirect, render_template, request, url_for

try:
    from dotenv import load_dotenv

    load_dotenv(".env.local")
    load_dotenv()
except ImportError:
    pass

from notifier import post_to_discord
from sheets import (
    CATEGORIES,
    PROGRESS_STAGES,
    add_todo,
    delete_todo,
    get_all_todos,
    get_todo,
    organize_todos,
    set_done,
    update_todo,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")


@app.route("/")
def index():
    todos = get_all_todos()
    important, month_groups, done = organize_todos(todos)
    return render_template(
        "index.html", important=important, month_groups=month_groups, done=done, has_any=bool(todos)
    )


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        content = request.form.get("content", "").strip()
        due_date = request.form.get("due_date", "").strip()
        category = request.form.get("category", "").strip()
        important = request.form.get("important") == "on"
        progress = request.form.get("progress", "").strip()
        is_test_case = request.form.get("is_test_case") == "on"
        if not client_name:
            flash("クライアント名は必須です", "error")
            todo_data = {
                "client_name": client_name,
                "content": content,
                "due_date": due_date,
                "category": category,
                "important": "TRUE" if important else "FALSE",
                "progress": progress,
                "is_test_case": "TRUE" if is_test_case else "FALSE",
            }
            return render_template(
                "form.html", todo=todo_data, mode="add", categories=CATEGORIES, progress_stages=PROGRESS_STAGES
            )
        add_todo(client_name, content, due_date, category, important, progress, is_test_case)
        flash("登録しました", "success")
        return redirect(url_for("index"))
    return render_template(
        "form.html", todo=None, mode="add", categories=CATEGORIES, progress_stages=PROGRESS_STAGES
    )


@app.route("/toggle/<todo_id>", methods=["POST"])
def toggle(todo_id):
    done = request.form.get("done") == "on"
    set_done(todo_id, done)
    return redirect(url_for("index"))


@app.route("/delete/<todo_id>", methods=["POST"])
def delete(todo_id):
    delete_todo(todo_id)
    flash("削除しました", "success")
    return redirect(url_for("index"))


@app.route("/edit/<todo_id>", methods=["GET", "POST"])
def edit(todo_id):
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        content = request.form.get("content", "").strip()
        due_date = request.form.get("due_date", "").strip()
        category = request.form.get("category", "").strip()
        important = request.form.get("important") == "on"
        progress = request.form.get("progress", "").strip()
        is_test_case = request.form.get("is_test_case") == "on"
        if not client_name:
            flash("クライアント名は必須です", "error")
            todo_data = {
                "client_name": client_name,
                "content": content,
                "due_date": due_date,
                "category": category,
                "important": "TRUE" if important else "FALSE",
                "progress": progress,
                "is_test_case": "TRUE" if is_test_case else "FALSE",
            }
            return render_template(
                "form.html",
                todo=todo_data,
                mode="edit",
                todo_id=todo_id,
                categories=CATEGORIES,
                progress_stages=PROGRESS_STAGES,
            )
        update_todo(todo_id, client_name, content, due_date, category, important, progress, is_test_case)
        flash("更新しました", "success")
        return redirect(url_for("index"))

    todo = get_todo(todo_id)
    if todo is None:
        flash("そのやることは見つかりませんでした", "error")
        return redirect(url_for("index"))
    return render_template(
        "form.html",
        todo=todo,
        mode="edit",
        todo_id=todo_id,
        categories=CATEGORIES,
        progress_stages=PROGRESS_STAGES,
    )


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
