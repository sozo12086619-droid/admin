"""
dateparse.py — 日本語の日付表現を実際の日付に変換する

「来週の水曜」→ 2026-09-23 みたいな変換を、Pythonだけで行う。

なんでAIに全部やらせへんの？
  AIは「来週の水曜って何日？」みたいな日付の計算がけっこう苦手で、
  たまに平気で1週間ズレた日付を返してくる。
  そこで「AIには“来週の水曜”という文字列を抜き出させるだけ」にして、
  実際の日付計算はこのファイル（＝絶対に間違えないPythonのコード）が行う。
  これを「AIの出力を検算する」という。AIアプリの品質はここで決まる。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# 曜日の文字 → Python の曜日番号（月曜=0, 日曜=6）
WEEKDAYS = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

# 「今日」「明日」など、今日からの日数がそのまま決まる言葉
OFFSET_WORDS = {
    "一昨日": -2, "おととい": -2, "一昨昨日": -3,
    "昨日": -1, "きのう": -1, "前日": -1,
    "今日": 0, "本日": 0, "きょう": 0,
    "明日": 1, "あした": 1, "あす": 1,
    "明後日": 2, "あさって": 2,
    "明々後日": 3, "しあさって": 3,
}


def week_start(d: date) -> date:
    """その日が属する週の月曜日を返す。"""
    return d - timedelta(days=d.weekday())


def parse_time(text: str) -> str | None:
    """文字列から時刻を取り出して "HH:MM" で返す。無ければ None。"""
    # 18:30 / 18：30 形式
    m = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    # 午後6時半 / 18時 / 18時30分 形式
    m = re.search(r"(午前|午後|朝|夜|昼)?\s*(\d{1,2})\s*時\s*(半|(\d{1,2})\s*分)?", text)
    if m:
        period, h = m.group(1), int(m.group(2))
        minute = 0
        if m.group(3) == "半":
            minute = 30
        elif m.group(4):
            minute = int(m.group(4))

        # 「午後6時」→18時 のように12時間制を24時間制に直す
        if period in ("午後", "夜") and h < 12:
            h += 12
        elif period in ("午前", "朝") and h == 12:
            h = 0

        if 0 <= h <= 23 and 0 <= minute <= 59:
            return f"{h:02d}:{minute:02d}"

    return None


def parse_date(text: str, base: date | None = None) -> date | None:
    """文字列から日付を取り出して date で返す。無ければ None。

    base は「今日」として扱う基準日。省略すると実際の今日。
    （テストしやすいように引数で渡せるようにしてある＝テスタビリティ）
    """
    if not text:
        return None
    base = base or date.today()

    # --- 1. 2026-09-20 / 2026/9/20 のような、そのままの日付 ---
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # --- 2. 今日 / 明日 / 昨日 など ---
    for word, offset in OFFSET_WORDS.items():
        if word in text:
            return base + timedelta(days=offset)

    # --- 3. 「来週の水曜」「今週の金曜」「再来週の月曜」 ---
    m = re.search(r"(今週|来週|再来週|先週)?.{0,2}?([月火水木金土日])曜", text)
    if m:
        week_word, wd_char = m.group(1), m.group(2)
        target_wd = WEEKDAYS[wd_char]
        if week_word == "今週":
            return week_start(base) + timedelta(days=target_wd)
        if week_word == "来週":
            return week_start(base) + timedelta(days=7 + target_wd)
        if week_word == "再来週":
            return week_start(base) + timedelta(days=14 + target_wd)
        if week_word == "先週":
            return week_start(base) + timedelta(days=-7 + target_wd)
        # 週の指定が無い「水曜」→ 次に来る水曜（今日がその曜日なら今日）
        ahead = (target_wd - base.weekday()) % 7
        return base + timedelta(days=ahead)

    # --- 4. 「来週」「来月」など、日の指定が無いざっくり表現 ---
    m = re.search(r"(来月|再来月|今月)\s*(\d{1,2})\s*日", text)
    if m:
        months = {"今月": 0, "来月": 1, "再来月": 2}[m.group(1)]
        day = int(m.group(2))
        year, month = base.year, base.month + months
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # --- 5. 「9月20日」「9/20」 ---
    m = re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?", text)
    if m:
        try:
            return date(base.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None

    # --- 6. 「3日後」「2週間後」 ---
    m = re.search(r"(\d{1,2})\s*(日|週間|ヶ月|か月)\s*後", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "日":
            return base + timedelta(days=n)
        if unit == "週間":
            return base + timedelta(weeks=n)
        return base + timedelta(days=30 * n)  # ヶ月はざっくり30日換算

    # --- 7. 週だけの指定（曜日なし）は、その週の月曜を仮に置く ---
    if "来週" in text:
        return week_start(base) + timedelta(days=7)
    if "再来週" in text:
        return week_start(base) + timedelta(days=14)

    return None


def resolve(date_text: str | None, base: date | None = None) -> tuple[str | None, str | None]:
    """日付表現から (YYYY-MM-DD, HH:MM) を返す。取れへんかったら None。"""
    if not date_text:
        return None, None
    base = base or date.today()
    d = parse_date(date_text, base)
    t = parse_time(date_text)
    # 時刻だけ書いてある（例:「18時から」）場合は今日の予定とみなす
    if d is None and t is not None:
        d = base
    return (d.isoformat() if d else None), t


def label_for(target: str | None, base: date | None = None) -> str:
    """日付の見出し用ラベル。例: "9月18日(金) · 今日" """
    if not target:
        return "日付なし"
    base = base or date.today()
    try:
        d = datetime.strptime(target, "%Y-%m-%d").date()
    except ValueError:
        return "日付なし"

    diff = (d - base).days
    rel = {
        -2: "一昨日", -1: "昨日", 0: "今日", 1: "明日", 2: "明後日",
    }.get(diff)
    if rel is None:
        if diff < 0:
            rel = f"{-diff}日前"
        else:
            rel = f"{diff}日後"

    year = f"{d.year}年" if d.year != base.year else ""
    return f"{year}{d.month}月{d.day}日({WEEKDAY_JA[d.weekday()]}) · {rel}"
