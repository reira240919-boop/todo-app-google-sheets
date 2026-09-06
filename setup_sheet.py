"""
スプレッドシートの1行目（見出し行）を作るための、最初に1回だけ実行するスクリプト。

使い方:
    python3 setup_sheet.py
"""
from sheets import HEADERS, get_sheet

if __name__ == "__main__":
    sheet = get_sheet()
    sheet.update(values=[HEADERS], range_name="A1")
    print("見出し行を作成しました:", HEADERS)
