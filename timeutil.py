"""
timeutil.py — 日本時間(JST)の「今」を返すヘルパー

Render のサーバーは UTC で動いている。datetime.now() をそのまま使うと、
日本時間の 0:00〜9:00 のあいだ「昨日」として扱われてしまい、
月初や年明けに、月ずれ・年ずれが起きる。
日本にサマータイムは無いので、UTC+9 の固定オフセットで十分。
"""

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    """日本時間の現在時刻（タイムゾーン情報なし = 素朴な datetime）。"""
    return datetime.now(JST).replace(tzinfo=None)


def today_jst() -> date:
    return now_jst().date()
