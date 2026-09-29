"""
message_service.py — LINE のメッセージを受け取って、何をするか決める司令塔

ここは「返信する文面」を返すだけで、LINE への送信自体は行わない
（送信は routers/line_webhook.py が担当）。そのおかげで、LINE に繋がなくても
`handle_text_message("9/21 18:00-23:00")` のように単体で動かして確かめられる。
"""

import logging

import config
import db
from services import calendar_service, gemini_service
from services.expense_service import parse_expense_text
from services.shift_service import parse_shift_text

logger = logging.getLogger(__name__)


def _short(e: Exception, limit: int = 80) -> str:
    return str(e).replace("\n", " ")[:limit]


def handle_text_message(text: str) -> str:
    """テキストの各行を「シフト」「支出」として解釈し、登録結果の返信文を返す。"""
    text = text.strip()

    raw_id = None
    try:
        raw_id = db.save_raw_note(user_id=config.APP_USER_ID, body=text, source="line")
    except Exception:
        logger.exception("raw_notes の保存に失敗")

    shift_count, shift_total = 0, 0
    expense_count, expense_total = 0, 0
    errors: list[str] = []

    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue

        # ---- シフト ----
        # 1行の失敗で他の行を巻き込まないよう、行ごとに try で囲む
        try:
            shift = parse_shift_text(line)
        except Exception:
            logger.exception("シフト解析で例外: %r", line)
            shift = None

        if shift:
            try:
                # カレンダー → DB の順。カレンダーに載らなかったシフトは DB にも入れない
                # （元コードと同じ。入れると、直して再送したときに二重登録になる）
                calendar_service.add_event_to_calendar(shift)
                salary = shift["salary"]
                db.insert_money_record(
                    record_date=shift["record_date"],
                    record_type="income",
                    category="バイト",
                    title=shift["summary"],
                    amount=salary["total_pay"],
                    status="expected",
                    detail=f"{shift['time_str']} (昼{salary['day_hours']}h/深夜{salary['night_hours']}h)",
                    raw_note_id=raw_id,
                    user_id=config.APP_USER_ID,
                )
                shift_count += 1
                shift_total += salary["total_pay"]
            except Exception as e:
                logger.exception("シフト登録に失敗: %r", line)
                errors.append(f"{shift['date_str']} のシフトを登録できませんでした（{_short(e)}）")
            continue

        # ---- 支出 ----
        try:
            expense = parse_expense_text(line)
        except Exception:
            logger.exception("支出解析で例外: %r", line)
            expense = None

        if expense:
            try:
                db.insert_money_record(
                    record_date=expense["record_date"],
                    record_type="expense",
                    category=expense["category"],
                    title=expense["title"],
                    amount=expense["amount"],
                    status="confirmed",
                    user_id=config.APP_USER_ID,
                )
                expense_count += 1
                expense_total += expense["amount"]
            except Exception:
                logger.exception("支出登録に失敗: %r", line)
                errors.append(f"「{expense['title']}」を保存できませんでした")

    parts = []
    if shift_count:
        parts.append(f"シフト {shift_count}件 登録 (見込¥{shift_total:,})")
    if expense_count:
        parts.append(f"支出 {expense_count}件 登録 (計¥{expense_total:,})")
    parts.extend(f"⚠️ {e}" for e in errors)
    return "\n".join(parts) if parts else "記録完了！"


def handle_image_message(image_bytes: bytes) -> str:
    """明細画像から支出を読み取って登録し、返信文を返す。"""
    try:
        items = gemini_service.analyze_expense_image(image_bytes)
    except gemini_service.GeminiError as e:
        return f"画像解析エラー: {e}"
    except Exception as e:
        logger.exception("画像解析で予期しない例外")
        return f"画像解析エラー: {_short(e)}"

    if not items:
        return "画像から支出を読み取れなかったよ💦 明細がはっきり写った画像で試してみてね"

    count, failed = 0, 0
    for item in items:
        try:
            db.insert_money_record(
                record_date=item["date"],
                record_type="expense",
                category=item["category"],
                title=item["store"],
                amount=item["amount"],
                detail=item["detail"],
                user_id=config.APP_USER_ID,
            )
            count += 1
        except Exception:
            logger.exception("画像明細の保存に失敗: %r", item)
            failed += 1

    reply = f"画像から支出 {count}件 を登録したよ！"
    if failed:
        reply += f"\n⚠️ {failed}件は保存できませんでした"
    return reply
