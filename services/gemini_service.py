"""gemini_service.py — 明細・レシート画像を Gemini に読ませて支出を取り出す"""

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime

import config
import timeutil
from services.expense_service import EXPENSE_CATEGORIES

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"


class GeminiError(Exception):
    """LINE にそのまま返してよい文面を持つ例外。"""


def _build_prompt(today_str: str) -> str:
    categories = " または ".join(f'"{c}"' for c in EXPENSE_CATEGORIES)
    return (
        "この画像から実際に支払いが完了した【支出】のみをすべて抽出してください。\n"
        "「支払い失敗」「チャージ」「受取」「ポイント付与」「残高」は絶対に除外してください。\n"
        "以下のJSON配列形式のみで出力してください（マークダウン不要）。\n"
        "[\n"
        "  {\n"
        f'    "date": "YYYY-MM-DD形式。不明なら「{today_str}」",\n'
        '    "store": "店名や摘要",\n'
        '    "amount": 金額（正の整数）,\n'
        f'    "category": {categories},\n'
        '    "detail": "品目等"\n'
        "  }\n"
        "]"
    )


def _to_amount(value) -> int:
    """金額を整数にする。"1,234円" や 1234.0 のような揺れも受け入れる。"""
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value or ""))
    return int(digits) if digits else 0


def normalize_items(parsed, today: date | None = None) -> list[dict]:
    """Gemini の出力を、そのまま DB に入れられる形に整える。

    AI の出力は信用せず必ず検証する。日付が読めない・カテゴリが想定外・金額が0以下、
    といったケースでも、他の明細まで巻き込んで落ちないようにする。
    """
    today = today or timeutil.today_jst()
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    items = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        amount = _to_amount(raw.get("amount"))
        if amount <= 0:
            continue

        try:
            day = datetime.strptime(str(raw.get("date") or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            day = today

        category = raw.get("category")
        items.append({
            "date": day.isoformat(),
            "store": (str(raw.get("store") or "").strip() or "店舗")[:100],
            "amount": amount,
            "category": category if category in EXPENSE_CATEGORIES else "その他",
            "detail": str(raw.get("detail") or "")[:200],
        })
    return items


def analyze_expense_image(image_bytes: bytes) -> list[dict]:
    """画像から支出のリストを取り出す。失敗時は GeminiError。"""
    if not config.GEMINI_API_KEY:
        raise GeminiError("Renderの環境変数に GEMINI_API_KEY が設定されていません")

    model = config.GEMINI_MODEL
    if not model.startswith("models/"):
        model = f"models/{model}"

    payload = {
        "contents": [{
            "parts": [
                {"text": _build_prompt(timeutil.today_jst().isoformat())},
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                }},
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    # APIキーは URL に付けず、ヘッダーで渡す（URL はログや例外文に残りやすいため）
    req = urllib.request.Request(
        _ENDPOINT.format(model=model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = json.loads(res.read().decode("utf-8"))
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text.strip())
        return normalize_items(json.loads(text))
    except urllib.error.HTTPError as he:
        if he.code == 429:
            raise GeminiError("⚠️ Google AIの利用制限（1分間に5回まで）に達しました💦 1分ほど待ってからもう一度送信してください！")
        if he.code == 503:
            raise GeminiError("⚠️ Google AIサーバーが一時的に混雑しています💦 30秒ほど待ってからもう一度送信してください！")
        detail = he.read().decode("utf-8", errors="ignore")[:200]
        logger.error("Gemini HTTP %s: %s", he.code, detail)
        raise GeminiError(f"HTTP {he.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        logger.error("Gemini connection error: %s", e)
        raise GeminiError("Google AIに接続できませんでした💦 少し待ってからもう一度送信してください")
    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.error("Gemini response parse error: %r", e)
        raise GeminiError("画像から明細を読み取れませんでした💦 明るい場所でもう一度撮ってみてください")
