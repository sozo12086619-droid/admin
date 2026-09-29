# LINE家計簿

LINE に「9/21 セブン 150円」「9/21 すき家 18:00-23:00」と送るだけで、家計簿への記録と
Google カレンダーへのシフト登録ができる FastAPI アプリ。画像（明細・レシート）は Gemini が読み取る。

## ファイル構成

```
main.py                  アプリの入口（ここでは組み立てだけ）
line_bot.py              互換用ラッパー（Start Command が line_bot:app のままでも動く）
config.py                環境変数と定数（設定はここ1か所）
db.py                    SQL はこのファイルだけ
timeutil.py              日本時間の「今」
security.py              ダッシュボードの Basic 認証（任意）

routers/
  dashboard.py           画面（/）と、手動入力・削除 API（/api/records）
  line_webhook.py        LINE の Webhook（/callback）

services/
  message_service.py     LINE のメッセージを「シフト」「支出」に振り分ける司令塔
  shift_service.py       「9/21 18:00-23:00」→ シフト
  expense_service.py     「9/21 セブン 150円」→ 支出（カテゴリ推定つき）
  salary_service.py      昼・深夜の時給計算
  datetext.py            文章から日付を見つける（共用）
  calendar_service.py    Google カレンダー
  gemini_service.py      画像 → 支出
  line_service.py        LINE への返信・画像取得
  dashboard_service.py   画面に出すデータの組み立て

templates/dashboard.html 画面の HTML（Jinja2）
static/css, static/js    画面の見た目と動き
data/past_records.py     過去データのバックアップ（通常運用では読み込まない）
scripts/maintenance.py   DB メンテ用（手動実行）
tests/                   テスト
```

「どこを直せばいい？」の目安

| 直したいこと | 触るファイル |
|---|---|
| 時給・深夜の時間帯 | `config.py`（WAGE_SETTINGS / DAY_START_HOUR / DAY_END_HOUR） |
| カテゴリの判定ワード | `services/expense_service.py`（_CATEGORY_RULES） |
| 画面のデザイン | `static/css/dashboard.css`、`templates/dashboard.html` |
| 画面に出す数字 | `services/dashboard_service.py` |
| LINE の返信文 | `services/message_service.py` |

## 環境変数

`.env.example` を参照。必須は元から設定済みの6つ。追加したのは任意の4つ。

| 名前 | 役割 |
|---|---|
| `DASHBOARD_PASSWORD` | 設定するとダッシュボードと `/api/records` に Basic 認証がかかる（**設定を推奨**） |
| `DASHBOARD_USER` | 認証のユーザー名（既定 `me`） |
| `FUYOU_LIMIT` | 扶養の壁の目安（既定 1030000） |
| `GEMINI_MODEL` | 画像解析のモデル名（既定 `gemini-3.8-flash`） |

## Render での起動

Start Command は今のまま（`uvicorn line_bot:app --host 0.0.0.0 --port $PORT`）で動く。
慣れたら `uvicorn main:app --host 0.0.0.0 --port $PORT` に変えて `line_bot.py` を消してよい。
ヘルスチェック用に `/healthz` がある。

## メンテナンス

```bash
python scripts/maintenance.py seed             # 過去データのうち、DBに無いものだけ追加
python scripts/maintenance.py dedupe           # 重複候補の一覧（削除しない）
python scripts/maintenance.py dedupe --apply   # 重複を削除
```

以前は起動のたびに「重複削除」と「過去データ投入」を自動で走らせていたが、
同じ日に同じ店で同額を2回買った明細が消える／消した過去データが復活する、という副作用があったため手動にした。

## テスト

```bash
pip install -r requirements-dev.txt
pytest                                   # 解析ロジックのテスト（DB不要）
TEST_DATABASE_URL=postgresql://... pytest   # 画面・API・LINE Webhook も（テスト専用DBを指定すること）
```

`TEST_DATABASE_URL` を指定しない限り、テストは本番の `DATABASE_URL` に一切触れない。
