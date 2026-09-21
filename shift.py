"""
shift.py — シフト表の画像をAIに読ませて、勤務予定を取り出す
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import date, datetime, timedelta

from PIL import Image

MAX_IMAGE_SIDE = 1568
JPEG_QUALITY = 85


def prepare_image(raw: bytes) -> tuple[str, str]:
    img = Image.open(io.BytesIO(raw))

    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


SHIFT_SYSTEM_PROMPT = """あなたはアルバイトのシフト表を読み取る専門アシスタントです。

画像にはシフト表が写っています。指定された人物の勤務予定だけを抜き出してください。

読み取りのコツ:
- シフト表は「縦に日付、横に従業員名」または「横に日付、縦に従業員名」の表であることが多い。
- 指定された人物の行（または列）を特定し、時間が書かれているマスだけを拾う。
- 空欄・「休」「-」「×」は勤務なしなので無視する。
- 「18-23」「18:00〜23:00」「18時〜23時」などの表記はすべて開始〜終了時刻を意味する。
- 表の上部や隅に書かれた「2026年9月」などの年月を、各日付の年月として使う。
- 年月がどこにも書かれていない場合は、指定された「今日の日付」に最も近くなる年月を選ぶ。

出力ルール:
- 必ずJSON配列のみを出力する。説明文やマークダウンの```は一切付けない。
- 各要素は次のキーを持つ:
  - "date"       : "YYYY-MM-DD"
  - "start"      : "HH:MM"（24時間制）
  - "end"        : "HH:MM"（24時間制）。終了が翌日にまたぐ場合もそのまま時刻を書く
  - "raw"        : そのマスに書かれていた文字をそのまま
  - "confidence" : 読み取りの自信度 0.0〜1.0
- 指定された人物が見つからない場合は、空の配列 [] を返す。
- 読めない文字を推測で埋めない。自信が無いものは confidence を下げる。
"""


def build_shift_prompt(person_name: str, today: date, hint: str = "") -> str:
    lines = [
        f"今日の日付: {today.isoformat()}",
        f"探す人物: 「{person_name}」",
        "この人物の勤務予定だけをJSON配列で出力してください。",
    ]
    if hint:
        lines.append(f"補足情報: {hint}")
    return "\n".join(lines)


def read_with_claude(raw: bytes, person_name: str, model: str, hint: str = "") -> list[dict]:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません（.env を確認）")

    b64, media_type = prepare_image(raw)
    client = Anthropic(api_key=api_key)

    resp = client.messages.create(
        model=model,
        max_tokens=3000,
        system=SHIFT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": build_shift_prompt(person_name, date.today(), hint)},
                ],
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json(text)


def read_with_gemini(raw: bytes, person_name: str, model: str, hint: str = "") -> list[dict]:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません（.env を確認）")

    b64, media_type = prepare_image(raw)
    client = genai.Client(api_key=api_key)

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=base64.b64decode(b64), mime_type=media_type),
            SHIFT_SYSTEM_PROMPT + "\n\n" + build_shift_prompt(person_name, date.today(), hint),
        ],
    )
    return _extract_json(resp.text)


def _extract_json(raw: str) -> list[dict]:
    text = re.sub(r"^```(?:json)?", "", raw.strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"JSON配列が見つかりませんでした。AIの返答:\n{raw[:500]}")
    data = json.loads(text[start : end + 1])
    return data if isinstance(data, list) else []


_LINE_PAT = re.compile(
    r"(?P<month>\d{1,2})\s*[/月]\s*(?P<day>\d{1,2})\s*日?"
    r"[^\d]{0,12}?"
    r"(?P<sh>\d{1,2})\s*[:：時]?\s*(?P<sm>\d{2})?"
    r"\s*[〜~～\-–—ー to]+\s*"
    r"(?P<eh>\d{1,2})\s*[:：時]?\s*(?P<em>\d{2})?"
)


def read_from_text(text: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    results = []
    for line in text.splitlines():
        m = _LINE_PAT.search(line)
        if not m:
            continue
        month, day = int(m.group("month")), int(m.group("day"))
        year = today.year
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if (d - today).days < -180:
            d = d.replace(year=year + 1)
        elif (d - today).days > 200:
            d = d.replace(year=year - 1)

        results.append(
            {
                "date": d.isoformat(),
                "start": f"{int(m.group('sh')):02d}:{m.group('sm') or '00'}",
                "end": f"{int(m.group('eh')):02d}:{m.group('em') or '00'}",
                "raw": line.strip(),
                "confidence": 0.4,
            }
        )
    return results


def _valid_date(s) -> str | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _valid_time(s) -> str | None:
    if not isinstance(s, str):
        return None
    s = s.strip().replace("：", ":")
    if re.fullmatch(r"\d{1,2}", s):
        s = f"{int(s):02d}:00"
    try:
        return datetime.strptime(s, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def to_items(shifts: list[dict], workplace: str = "バイト") -> list[dict]:
    items = []
    for s in shifts:
        if not isinstance(s, dict):
            continue
        d = _valid_date(s.get("date"))
        start = _valid_time(s.get("start"))
        end = _valid_time(s.get("end"))
        if not d or not start:
            continue

        start_dt = datetime.strptime(f"{d} {start}", "%Y-%m-%d %H:%M")
        end_dt = None
        crossed = False
        if end:
            end_dt = datetime.strptime(f"{d} {end}", "%Y-%m-%d %H:%M")
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
                crossed = True

        minutes = int((end_dt - start_dt).total_seconds() // 60) if end_dt else None
        time_label = f"{start}〜{end}" if end else f"{start}〜"

        try:
            conf = float(s.get("confidence", 0.6))
        except (TypeError, ValueError):
            conf = 0.6

        items.append(
            {
                "category": "予定",
                "title": f"{workplace} {time_label}",
                "detail": ("翌日まで／" if crossed else "") + f"読取: {s.get('raw') or ''}",
                "tags": ["バイト", workplace],
                "date_text": s.get("raw") or None,
                "event_date": d,
                "due_date": None,
                "start_at": start_dt.strftime("%Y-%m-%dT%H:%M"),
                "end_at": end_dt.strftime("%Y-%m-%dT%H:%M") if end_dt else None,
                "all_day": 0,
                "importance": 3,
                "estimated_minutes": minutes,
                "confidence": max(0.0, min(1.0, conf)),
            }
        )

    seen, unique = set(), []
    for it in items:
        key = (it["event_date"], it["start_at"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)

    unique.sort(key=lambda x: x["start_at"])
    return unique


def extract(
    image_bytes: bytes | None = None,
    pasted_text: str = "",
    person_name: str = "",
    workplace: str = "バイト",
    provider: str = "claude",
    model: str | None = None,
    hint: str = "",
) -> tuple[list[dict], str]:
    if image_bytes:
        if provider == "claude":
            m = model or "claude-haiku-4-5"
            return to_items(read_with_claude(image_bytes, person_name, m, hint), workplace), m
        if provider == "gemini":
            m = model or "gemini-3.6-flash"
            return to_items(read_with_gemini(image_bytes, person_name, m, hint), workplace), m
        raise RuntimeError(
            "画像の読み取りにはAPIキーが必要やで。"
            ".env に ANTHROPIC_API_KEY か GEMINI_API_KEY を設定してな。"
        )

    if pasted_text.strip():
        return to_items(read_from_text(pasted_text), workplace), "text-rules"

    return [], "none"
