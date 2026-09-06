import os

from flask import Flask, flash, redirect, render_template, request, url_for

from sheets import add_todo, get_all_todos, get_todo, update_todo

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")


@app.route("/")
def index():
    todos = get_all_todos()
    return render_template("index.html", todos=todos)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        due_date = request.form.get("due_date", "").strip()
        if not title:
            flash("タイトルは必須です", "error")
            return render_template("form.html", todo=request.form, mode="add")
        add_todo(title, content, due_date)
        flash("登録しました", "success")
        return redirect(url_for("index"))
    return render_template("form.html", todo=None, mode="add")


@app.route("/edit/<todo_id>", methods=["GET", "POST"])
def edit(todo_id):
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        due_date = request.form.get("due_date", "").strip()
        if not title:
            flash("タイトルは必須です", "error")
            return render_template("form.html", todo=request.form, mode="edit", todo_id=todo_id)
        update_todo(todo_id, title, content, due_date)
        flash("更新しました", "success")
        return redirect(url_for("index"))

    todo = get_todo(todo_id)
    if todo is None:
        flash("そのやることは見つかりませんでした", "error")
        return redirect(url_for("index"))
    return render_template("form.html", todo=todo, mode="edit", todo_id=todo_id)


if __name__ == "__main__":
    app.run(debug=True)
