"""
calendar_export.py — 予定データを .ics カレンダーファイルに書き出す

.ics（アイシーエス）とは:
  カレンダーの予定をやり取りするための世界共通のテキスト形式。
  正式名称は iCalendar（RFC 5545 という仕様書で決まってる）。
  Google カレンダー、iPhone標準カレンダー、TimeTree、Outlook、
  だいたい全部これを読める。中身はただのテキストなので、
  Pythonで文字列を組み立てるだけで作れる。

TimeTree は外部からの直接書き込みAPIを終了しているので、
「.icsを作って渡す → スマホで開いて取り込む」が一番確実なルート。
"""

from __future__ import annotations

from datetime import datetime, timedelta

# 予定の長さが分からんときの既定値（分）
DEFAULT_DURATION_MIN = 60

# タイムゾーン定義。日本はサマータイムが無いので +09:00 固定でシンプルに書ける
VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:Asia/Tokyo",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:+0900",
    "TZOFFSETTO:+0900",
    "TZNAME:JST",
    "END:STANDARD",
    "END:VTIMEZONE",
]


def escape(text: str) -> str:
    """.ics の中で特別な意味を持つ文字を無害化する。

    カンマ・セミコロン・バックスラッシュはそのまま書くと区切り記号として
    解釈されてしまうので、前に \\ を付けて「ただの文字やで」と伝える。
    """
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """1行が75バイトを超えたら折り返す（.ics の仕様で決まっているルール）。

    折り返した続きの行は、先頭に半角スペースを1つ付ける約束になっている。
    日本語は1文字3バイトなので、この処理が無いと長いタイトルで壊れる。
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line

    chunks, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not chunks else 74  # 2行目以降は先頭スペースの分だけ減る
        if len(current) + len(b) > limit:
            chunks.append(current)
            current = b""
        current += b
    chunks.append(current)
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def _dt(value: str) -> str:
    """"2026-09-23T19:00" → "20260923T190000" """
    return value.replace("-", "").replace(":", "") + "00"


def build_event(row) -> list[str] | None:
    """items テーブルの1行から VEVENT（予定1件）のブロックを作る。"""
    event_date = row["event_date"]
    if not event_date:
        return None  # 日付が無いものはカレンダーに載せられへん

    lines = ["BEGIN:VEVENT"]

    # UID = 予定を一意に識別するID。
    # 同じUIDで2回取り込むと「新規追加」ではなく「上書き」になるので、
    # うっかり二重登録される事故を防げる。だからDBのidを使って固定する。
    lines.append(f"UID:memo-{row['id']}@memo-organizer.local")
    lines.append(f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}")

    if row["start_at"]:
        # 時刻ありの予定。
        # 終了時刻の決め方は 3段構え:
        #   ① end_at がある（シフト表から読んだ勤務など）→ それをそのまま使う
        #   ② estimated_minutes がある → 開始＋その分数
        #   ③ どちらも無い → 既定の1時間
        start_dt = datetime.strptime(row["start_at"], "%Y-%m-%dT%H:%M")
        if row["end_at"]:
            end_dt = datetime.strptime(row["end_at"], "%Y-%m-%dT%H:%M")
        else:
            minutes = row["estimated_minutes"] or DEFAULT_DURATION_MIN
            end_dt = start_dt + timedelta(minutes=minutes)
        lines.append(f"DTSTART;TZID=Asia/Tokyo:{_dt(row['start_at'])}")
        lines.append(f"DTEND;TZID=Asia/Tokyo:{end_dt.strftime('%Y%m%dT%H%M%S')}")
    else:
        # 終日予定。DTEND は「翌日」を指定するのが .ics のお約束
        d = datetime.strptime(event_date, "%Y-%m-%d").date()
        lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}")

    lines.append(fold(f"SUMMARY:{escape(row['title'])}"))

    desc_parts = []
    if row["detail"]:
        desc_parts.append(row["detail"])
    desc_parts.append(f"カテゴリ: {row['category']}")
    if row["date_text"]:
        desc_parts.append(f"元のメモ: {row['date_text']}")
    desc_parts.append("（殴り書き整理アプリから出力）")
    lines.append(fold(f"DESCRIPTION:{escape(' / '.join(desc_parts))}"))

    lines.append("END:VEVENT")
    return lines


def build_ics(rows, calendar_name: str = "殴り書き整理アプリ") -> tuple[str, list[int]]:
    """複数の予定から .ics 全体を作り、(中身, 出力したidの一覧) を返す。"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//memo-organizer//JP",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold(f"X-WR-CALNAME:{escape(calendar_name)}"),
        "X-WR-TIMEZONE:Asia/Tokyo",
    ]
    lines.extend(VTIMEZONE)

    exported_ids = []
    for row in rows:
        block = build_event(row)
        if block:
            lines.extend(block)
            exported_ids.append(row["id"])

    lines.append("END:VCALENDAR")

    # .ics の改行は \r\n と決まっている（\n だけやと読めんアプリがある）
    return "\r\n".join(lines) + "\r\n", exported_ids


def exportable(rows) -> list:
    """カレンダーに出せる行（日付があるもの）だけを抜き出す。"""
    return [r for r in rows if r["event_date"]]
