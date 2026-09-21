"""
ai.py — 殴り書きテキストをAIに投げて「項目リスト」に分解・分類させるファイル

【Phase 2 での変更点】
  - AIに「今日の日付」と「曜日」を渡すようにした
  - AIには日付表現の "抜き出し" と "変換案" の両方を出させる
  - そのあと Python(dateparse.py) で検算して、確実な方を採用する
  - 重要度・所要時間の見積もりも一緒に出させる（優先順位づけの下ごしらえ）
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import dateparse
from db import CATEGORIES

CLAUDE_MODEL = "claude-haiku-4-5"      # 精度が欲しいときは "claude-sonnet-5"
GEMINI_MODEL = "gemini-1.5-flash"

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

# ---------------------------------------------------------------------------
# プロンプト（AIへの指示文）
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""あなたは日本語の「殴り書きメモ」を整理する専門アシスタントです。

入力された雑なメモを、意味のまとまりごとに分解し、以下のカテゴリのいずれかに分類してください。

カテゴリの定義:
- 買い物 : 買う必要があるモノ（例: 牛乳買う、シャンプー切れた）
- タスク : 自分がやらないといけない作業。締切があることが多い（例: レポート提出）
- 予定   : 日時が決まっている、これから起きること（例: 18時からバイト、金曜3限 実験）
- メモ   : 覚えておきたい情報・知識・URLなど
- 出来事 : すでに起きたことの記録（例: 今日12時に起きた、昨日車が壊れた）
- やりたいこと : いつかやりたい願望・アイデア（例: アプリ作りたい、旅行行きたい）

出力ルール:
- 必ずJSON配列のみを出力する。説明文やマークダウンの```は一切付けない。
- 配列の各要素は次のキーを持つオブジェクトとする:
  - "title"      : 15文字程度の短い要約
  - "detail"     : 補足。無ければ空文字 ""
  - "category"   : {" / ".join(CATEGORIES)} のいずれか1つ
  - "date_text"  : メモ中の日付・時間表現を **原文のまま** 抜き出す（例: "来週の水曜", "18時から"）。無ければ null
  - "event_date" : date_text を実際の日付に変換したもの "YYYY-MM-DD"。判断できなければ null
  - "event_time" : 時刻があれば "HH:MM"（24時間制）。無ければ null
  - "is_deadline": その日付が「締切」なら true、単なる予定・出来事なら false
  - "importance" : 重要度 1〜5 の整数（5が最重要）。判断材料が無ければ 3
  - "estimated_minutes" : 所要時間の見積もり（分）。見当がつかなければ null
  - "tags"       : 関連キーワードの配列（0〜3個）
  - "confidence" : 分類の自信度 0.0〜1.0
- 1行に複数の用事が書かれている場合は、それぞれ別の要素に分ける。
- すでに起きたことは必ず「出来事」にする。過去の日付になってよい。
- 入力に無い情報を勝手に作らない。曖昧なものは "メモ" にして confidence を下げる。
"""


def build_user_prompt(text: str, today: date) -> str:
    """AIに渡す本文。今日の日付と曜日を明示するのが Phase 2 の肝。"""
    wd = WEEKDAY_JA[today.weekday()]
    return (
        f"今日の日付: {today.isoformat()}（{wd}曜日）\n"
        f"※「来週」は次の月曜から始まる週を指します。\n\n"
        f"--- ここから殴り書きメモ ---\n{text}\n--- ここまで ---"
    )


# ---------------------------------------------------------------------------
# 返ってきた文字列から JSON を取り出す
# ---------------------------------------------------------------------------

def extract_json(raw: str) -> list[dict]:
    """AIの返答から JSON 配列だけを取り出してPythonのリストに変換する。"""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"JSON配列が見つかりませんでした。AIの返答:\n{raw[:500]}")

    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("JSONが配列ではありません")
    return data


def _valid_date(s) -> str | None:
    """"YYYY-MM-DD" として正しい文字列だけを通す門番。"""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _valid_time(s) -> str | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def _to_int(v, lo: int, hi: int, default=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def normalize(items: list[dict], today: date | None = None) -> list[dict]:
    """AIの出力を安全な形に整える + 日付をPythonで検算する。

    ★ここがPhase 2の心臓部★
    日付の決め方の優先順位:
      1. dateparse.py が date_text から計算できた日付（Pythonの計算なので絶対にズレない）
      2. AIが出してきた event_date（1が取れなかった複雑な表現用の保険）
    """
    today = today or date.today()
    cleaned = []

    for it in items:
        if not isinstance(it, dict):
            continue

        category = it.get("category")
        if category not in CATEGORIES:
            category = "メモ"

        try:
            conf = float(it.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5

        tags = it.get("tags")
        if not isinstance(tags, list):
            tags = []

        date_text = it.get("date_text") or None

        # --- 日付の検算 ---
        py_date, py_time = dateparse.resolve(date_text, today)
        ai_date = _valid_date(it.get("event_date"))
        ai_time = _valid_time(it.get("event_time"))

        event_date = py_date or ai_date          # Pythonの計算を優先
        event_time = py_time or ai_time

        # 時刻があれば "2026-09-23T19:00" の形の開始日時も作っておく
        start_at = f"{event_date}T{event_time}" if (event_date and event_time) else None
        due_date = event_date if it.get("is_deadline") else None

        cleaned.append(
            {
                "title": str(it.get("title") or "").strip() or "（無題）",
                "detail": str(it.get("detail") or ""),
                "category": category,
                "date_text": date_text,
                "event_date": event_date,
                "due_date": due_date,
                "start_at": start_at,
                "all_day": 0 if event_time else 1,
                "importance": _to_int(it.get("importance"), 1, 5, 3),
                "estimated_minutes": _to_int(it.get("estimated_minutes"), 1, 100000, None),
                "tags": [str(t) for t in tags][:3],
                "confidence": max(0.0, min(1.0, conf)),
            }
        )
    return cleaned


# ---------------------------------------------------------------------------
# 各プロバイダの呼び出し
# ---------------------------------------------------------------------------

def classify_with_claude(text: str, model: str = CLAUDE_MODEL) -> list[dict]:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません（.env を確認）")

    today = date.today()
    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(text, today)}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    return normalize(extract_json(raw), today)


def classify_with_gemini(text: str, model: str = GEMINI_MODEL) -> list[dict]:
    from google import genai  # pip install google-genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません（.env を確認）")

    today = date.today()
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=SYSTEM_PROMPT + "\n\n" + build_user_prompt(text, today),
    )
    return normalize(extract_json(resp.text), today)


# ---------------------------------------------------------------------------
# オフライン用の簡易分類（APIキーが無くても動く）
# ---------------------------------------------------------------------------

_RULES = [
    ("出来事", ["した", "行った", "だった", "できた", "会った", "壊れた", "起きた", "終わった"]),
    ("買い物", ["買う", "買い", "購入", "切れた", "補充", "ストック"]),
    # 「ライブ」は「ドライブ」の一部にもなってしまうので入れてない。
    # こういう部分一致の事故が起きへんのが、AI分類の強み。
    ("予定", ["時から", "限", "集合", "バイト", "シフト", "会議", "予約", "面接"]),
    ("タスク", ["までに", "提出", "締切", "しめきり", "やる", "やらな", "返信", "申請", "課題", "レポート"]),
    ("やりたいこと", ["たい", "いつか", "興味", "挑戦"]),
]

_DATE_PAT = re.compile(
    r"((今週|来週|再来週|先週)?の?[月火水木金土日]曜日?"
    r"|一昨日|おととい|昨日|今日|本日|明日|明後日|しあさって"
    r"|来月\d{1,2}日|今月\d{1,2}日|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"
    r"|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{1,2}日後|\d{1,2}週間後"
    r"|来週|再来週"
    r"|(午前|午後|朝|夜)?\d{1,2}[:：]\d{2}|(午前|午後|朝|夜)?\d{1,2}時(半|\d{1,2}分)?)"
)

_DEADLINE_PAT = re.compile(r"までに|締切|しめきり|期限")


def classify_offline(text: str) -> list[dict]:
    """行ごとに分割してキーワードで分類する簡易版（日付変換はちゃんと動く）。"""
    today = date.today()
    items = []

    for line in text.splitlines():
        # 行頭の箇条書き記号を取る。ただし「18時」の 18 まで消さんように、
        # 数字は "1." "2、" のような番号付きリストの形のときだけ取り除く
        line = re.sub(r"^[\s・\-*●○▪◆]+", "", line)
        line = re.sub(r"^\d{1,2}[\.、)）]\s*", "", line).strip()
        if not line:
            continue

        category = "メモ"
        for cat, keywords in _RULES:
            if any(k in line for k in keywords):
                category = cat
                break

        # 行の中から日付表現になりそうな部分を全部つなげて渡す
        found = [m.group(0) for m in _DATE_PAT.finditer(line)]
        date_text = " ".join(found) if found else None

        items.append(
            {
                "title": line[:20],
                "detail": line if len(line) > 20 else "",
                "category": category,
                "date_text": date_text,
                "event_date": None,          # normalize() の中で dateparse が埋める
                "event_time": None,
                "is_deadline": bool(_DEADLINE_PAT.search(line)),
                "importance": 3,
                "estimated_minutes": None,
                "tags": [],
                "confidence": 0.3,
            }
        )
    return normalize(items, today)


# ---------------------------------------------------------------------------
# 外から呼ぶのはこの関数だけ
# ---------------------------------------------------------------------------

def classify(text: str, provider: str = "claude", model: str | None = None) -> tuple[list[dict], str]:
    """テキストを分類して (項目リスト, 使ったモデル名) を返す。"""
    if provider == "claude":
        m = model or CLAUDE_MODEL
        return classify_with_claude(text, m), m
    if provider == "gemini":
        m = model or GEMINI_MODEL
        return classify_with_gemini(text, m), m
    return classify_offline(text), "offline-rules"
