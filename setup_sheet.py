"""
日次やることリスト用のタブ（daily_tasks / settings）を作るためのスクリプト。
アプリ側でも無ければ自動で作るので、事前に確認したいときだけ実行する。

使い方:
    python3 setup_sheet.py
"""
from sheets import TASKS_SHEET, SETTINGS_SHEET, get_report_date, settings_sheet, tasks_sheet

if __name__ == "__main__":
    tasks_sheet()
    settings_sheet()
    print("タブを用意しました:", TASKS_SHEET, SETTINGS_SHEET)
    print("日報の日(report_date):", get_report_date().isoformat())
