"""
画面・API・LINE Webhook の結合テスト。
本物のPostgreSQLが必要なので、TEST_DATABASE_URL を指定したときだけ動く（無ければ skip）:

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/kakeibo_test pytest
"""
import base64
import hashlib
import hmac
import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL が未設定"
)

import config  # noqa: E402
import db  # noqa: E402
import timeutil  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from services import calendar_service, gemini_service, line_service  # noqa: E402

from main import app  # noqa: E402

TODAY = timeutil.today_jst()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # with を使うと起動時の init_db も実行される
        yield c
    db.execute("DELETE FROM public.money_records WHERE user_id = %s", (config.APP_USER_ID,))
    db.execute("DELETE FROM public.raw_notes WHERE user_id = %s", (config.APP_USER_ID,))


def _rows(title=None):
    sql = "SELECT * FROM public.money_records WHERE user_id = %s"
    params = [config.APP_USER_ID]
    if title:
        sql += " AND title = %s"
        params.append(title)
    return db.query(sql + " ORDER BY id", params)


# ---------------- ダッシュボード ----------------

def test_dashboard_shows_totals_and_escapes_html(client):
    client.post("/api/records", json={"record_date": TODAY.isoformat(), "record_type": "income",
                                      "category": "給料", "title": "テスト収入", "amount": 100000})
    client.post("/api/records", json={"record_date": TODAY.isoformat(), "record_type": "expense",
                                      "category": "食費", "title": "<script>alert(1)</script>", "amount": 30000})
    html = client.get("/").text
    assert "¥70,000" in html                                   # 収支
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html      # タイトルはエスケープされる
    assert "<script>alert(1)</script>" not in html


def test_invalid_month_falls_back_to_current(client):
    assert client.get("/?month=abc").status_code == 200
    assert client.get("/?month=2999-13").status_code == 200


def test_other_month_is_empty(client):
    r = client.get("/?month=2001-01")
    assert r.status_code == 200 and "記録はまだありません" in r.text


def test_add_validation_and_delete(client):
    assert client.post("/api/records", json={"record_date": TODAY.isoformat(), "amount": 0}).status_code == 422
    assert client.post("/api/records", json={"record_date": "2026-13-40", "amount": 5}).status_code == 422
    new_id = client.post("/api/records", json={"record_date": TODAY.isoformat(), "amount": 500,
                                                "title": "消すやつ"}).json()["id"]
    assert client.delete(f"/api/records/{new_id}").json()["deleted"] == 1
    assert client.delete(f"/api/records/{new_id}").json()["deleted"] == 0     # 2回目は何も消えない
    assert not _rows("消すやつ")


def test_healthz_and_static(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/static/css/dashboard.css").status_code == 200
    assert client.get("/static/js/dashboard.js").status_code == 200


# ---------------- 認証（任意機能） ----------------

def test_basic_auth_when_password_set(client, monkeypatch):
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "secret-pw")
    assert client.get("/").status_code == 401
    assert client.post("/api/records", json={"record_date": TODAY.isoformat(), "amount": 1}).status_code == 401
    assert client.delete("/api/records/1").status_code == 401
    assert client.get("/", auth=("me", "wrong")).status_code == 401
    assert client.get("/", auth=("me", "secret-pw")).status_code == 200
    assert client.get("/healthz").status_code == 200              # ヘルスチェックは開放
    # LINE 管理画面の「検証」ボタンは events が空の署名つきリクエストを送ってくる。認証なしで通ること
    body = b'{"destination": "U0", "events": []}'
    assert _post(client, body).status_code == 200


# ---------------- LINE Webhook ----------------

def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(config.LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()).decode()


def _event(message: dict) -> bytes:
    return json.dumps({
        "destination": "U0", "events": [{
            "type": "message", "mode": "active", "timestamp": 1700000000000,
            "source": {"type": "user", "userId": "U1"}, "webhookEventId": "01ABC",
            "deliveryContext": {"isRedelivery": False}, "replyToken": "reply-tok", "message": message,
        }],
    }).encode()


def _post(client, body: bytes, signature: str | None = None):
    return client.post("/callback", content=body,
                       headers={"X-Line-Signature": signature or _sign(body), "Content-Type": "application/json"})


@pytest.fixture
def replies(monkeypatch):
    sent = []
    monkeypatch.setattr(line_service, "reply_text", lambda token, text: sent.append((token, text)))
    return sent


def test_webhook_rejects_bad_signature(client):
    assert _post(client, _event({"type": "text", "id": "1", "text": "hi", "quoteToken": "q"}),
                 signature="bogus").status_code == 400


def test_webhook_text_registers_shift_and_expense(client, replies, monkeypatch):
    calls = []
    monkeypatch.setattr(calendar_service, "add_event_to_calendar", lambda parsed: calls.append(parsed))
    text = "9/21 すき家 18:00-23:00\n9/22 セブン 150円\n\nよくわからない行"
    r = _post(client, _event({"type": "text", "id": "1", "text": text, "quoteToken": "q"}))
    assert r.status_code == 200
    assert len(calls) == 1 and calls[0]["summary"] == "すき家"
    assert _rows("すき家") and _rows("セブン")
    assert _rows("すき家")[0]["amount"] == 6038 and _rows("すき家")[0]["status"] == "expected"
    (_, reply), = replies
    assert "シフト 1件 登録 (見込¥6,038)" in reply and "支出 1件 登録 (計¥150)" in reply   # 両方報告される


def test_webhook_reports_calendar_failure(client, replies, monkeypatch):
    def boom(parsed):
        raise RuntimeError("カレンダー認証情報またはCALENDAR_IDが未設定です")
    monkeypatch.setattr(calendar_service, "add_event_to_calendar", boom)
    _post(client, _event({"type": "text", "id": "2", "text": "9/23 ホール 17:00-22:00", "quoteToken": "q"}))
    (_, reply), = replies
    assert reply.startswith("⚠️") and "9/23" in reply            # 元コードは黙って「記録完了！」と返していた
    assert not _rows("ホール")                                    # カレンダーに載らなかったシフトは保存しない


def test_webhook_unrecognized_text_replies_default(client, replies):
    _post(client, _event({"type": "text", "id": "3", "text": "牛乳買う", "quoteToken": "q"}))
    assert replies[0][1] == "記録完了！"


def test_webhook_image(client, replies, monkeypatch):
    monkeypatch.setattr(line_service, "download_image", lambda mid: b"fake-jpeg")
    monkeypatch.setattr(gemini_service, "analyze_expense_image", lambda b: gemini_service.normalize_items([
        {"date": TODAY.isoformat(), "store": "ドラッグ", "amount": 980, "category": "日用品"},
        {"date": "壊れた日付", "store": None, "amount": "1,500円", "category": "???"},
    ]))
    _post(client, _event({"type": "image", "id": "9", "contentProvider": {"type": "line"}, "quoteToken": "q"}))
    assert "支出 2件" in replies[0][1]
    assert _rows("ドラッグ")[0]["amount"] == 980
    assert _rows("店舗")[0]["amount"] == 1500 and _rows("店舗")[0]["category"] == "その他"


def test_webhook_image_gemini_error_is_shown(client, replies, monkeypatch):
    def limited(_):
        raise gemini_service.GeminiError("⚠️ Google AIの利用制限に達しました")
    monkeypatch.setattr(line_service, "download_image", lambda mid: b"x")
    monkeypatch.setattr(gemini_service, "analyze_expense_image", limited)
    _post(client, _event({"type": "image", "id": "10", "contentProvider": {"type": "line"}, "quoteToken": "q"}))
    assert replies[0][1] == "画像解析エラー: ⚠️ Google AIの利用制限に達しました"
