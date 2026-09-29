import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# テスト用の環境変数（config.py が import される前に決めておく必要がある）
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token"
os.environ["GEMINI_API_KEY"] = "test-gemini"
os.environ["APP_USER_ID"] = f"pytest-{uuid.uuid4().hex[:8]}"   # 本物のデータと混ざらないよう毎回別ID
os.environ.pop("DASHBOARD_PASSWORD", None)

# ★安全装置★ 本番の DATABASE_URL が環境変数に入っていても、テストでは絶対に使わない。
# DBを使うテストは TEST_DATABASE_URL を明示したときだけ実行される。
os.environ.pop("DATABASE_URL", None)
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
