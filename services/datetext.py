"""
datetext.py — 文章の中から「日付」を見つける（シフトと支出で共用）

対応する書き方
    9/21   9月21日   2026/9/21   2026年9月21日   2026-09-21

元コードは `[/-年]` と書いていたが、これは「区切り文字の候補」ではなく
「`/` から `年` までの文字コード範囲」という意味になる。数字や `:` やひらがなまで
区切りとして通ってしまい、`18:00-23:00 9/21` のように時刻が先にある行で例外が出ていた。
ここでは区切りを明示し、月日が実在するかまで確かめてから採用する。
"""

import re
from datetime import date

import timeutil

_DATE_RE = re.compile(
    # 9/21, 9月21日, 2026/9/21, 2026年9月21日
    r"(?:(?P<y>\d{4})[/\-年]\s*)?(?P<m>\d{1,2})[/月](?P<d>\d{1,2})日?"
    # 2026-09-21（ハイフンは年つきの完全な形のときだけ。9-21 は時間帯と紛らわしいので対象外）
    r"|(?P<y2>\d{4})-(?P<m2>\d{1,2})-(?P<d2>\d{1,2})"
)


def find_date(text: str, default_year: int | None = None):
    """最初に見つかった実在する日付を (マッチ, date) で返す。無ければ None。"""
    default_year = default_year or timeutil.today_jst().year
    for m in _DATE_RE.finditer(text):
        y = m.group("y") or m.group("y2")
        mo = m.group("m") or m.group("m2")
        d = m.group("d") or m.group("d2")
        try:
            return m, date(int(y) if y else default_year, int(mo), int(d))
        except ValueError:
            continue  # 13/45 のような実在しない日付は読み飛ばす
    return None


def remove_span(text: str, start: int, end: int) -> str:
    """text[start:end] を取り除く。直前の空白も一緒に詰める。"""
    while start > 0 and text[start - 1].isspace():
        start -= 1
    return text[:start] + text[end:]
