"""
config.py — 環境変数と定数の置き場

設定値はここ1か所で読み込み、他のファイルは `import config` して使う。
os.environ を各ファイルで直接読まないこと（どこで何を読んでいるか追えなくなるため）。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env(name: str, default: str = "") -> str:
    # Render の Environment に貼り付けた値へ [] や引用符・空白が混ざっても動くよう、
    # 元コードと同じ掃除をしている。
    return os.environ.get(name, default).strip("[] \t\r\n'\"")


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# --- 外部サービス --------------------------------------------------------
LINE_CHANNEL_SECRET = _env("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = _env("LINE_CHANNEL_ACCESS_TOKEN")
GOOGLE_CALENDAR_ID = _env("GOOGLE_CALENDAR_ID")
GEMINI_API_KEY = _env("GEMINI_API_KEY")
# 元コードで使っていたモデル名を既定値にしてある。変えたいときは環境変数 GEMINI_MODEL で。
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.8-flash")
DATABASE_URL = _env("DATABASE_URL")
APP_USER_ID = _env("APP_USER_ID", "default") or "default"

# --- ダッシュボードの保護（任意・新規） -----------------------------------
# DASHBOARD_PASSWORD を設定するとダッシュボードと /api/records に Basic認証がかかる。
# 未設定なら元コードと同じく認証なし（起動時に警告ログが出る）。
DASHBOARD_USER = _env("DASHBOARD_USER", "me") or "me"
DASHBOARD_PASSWORD = _env("DASHBOARD_PASSWORD")

# --- 扶養の壁（元コードは 1030000 固定だった） ------------------------------
# 制度改正で数字が動くので、環境変数 FUYOU_LIMIT で変えられるようにした。
FUYOU_LIMIT = max(1, _env_int("FUYOU_LIMIT", 1_030_000))

# --- Google サービスアカウントの鍵ファイル ---------------------------------
CREDENTIALS_PATH = "/etc/secrets/google-credentials.json"
if not os.path.exists(CREDENTIALS_PATH):
    CREDENTIALS_PATH = str(BASE_DIR / "google-credentials.json")

# --- 時給設定 ------------------------------------------------------------
WAGE_SETTINGS = {
    "すき家": {"day": 1150, "night": 1438},
    "default": {"day": 1150, "night": 1438},
}
# 「昼」とみなす時間帯（9時〜22時）。それ以外はすべて深夜単価で計算する。
DAY_START_HOUR = 9
DAY_END_HOUR = 22
