"""
db.py — PostgreSQL へのアクセスをここに集約する（SQL はこのファイルにだけ書く）

元コードとの違い
  - 接続を毎回作らず、コネクションプールで使い回す（画面表示が速くなる）
  - main.py に直書きされていた集計クエリを、名前つきの関数にした
  - 月の絞り込みを `record_date::text LIKE '2026-09%'` から日付の範囲指定に変更
    （意味は同じ。DATE型のまま比較できるのでインデックスも効く）
  - テーブル定義は元のまま。既存データはそのまま使える
"""

import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

import config

logger = logging.getLogger(__name__)

_MAXCONN = 5
_pool = None
_pool_lock = threading.Lock()
# プールの接続が尽きたとき、エラーにせず順番待ちさせるための整理券
_slots = threading.BoundedSemaphore(_MAXCONN)


# ---------------------------------------------------------------------------
# 接続まわり
# ---------------------------------------------------------------------------

def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            if not config.DATABASE_URL:
                raise RuntimeError("DATABASE_URL が設定されていません")
            # sslmode などは元コードと同じく URL の指定にそのまま従う
            _pool = pg_pool.ThreadedConnectionPool(
                1, _MAXCONN, dsn=config.DATABASE_URL, connect_timeout=10
            )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:  # noqa: BLE001
                pass
            _pool = None


@contextmanager
def get_conn():
    """プールから接続を借り、終わったら返す。

    正常終了なら commit、例外なら rollback。呼び出し側は with で囲むだけでよい。
    借りた直後に SELECT 1 で生死確認するのは、Render / Supabase 側が
    放置された接続を切っていることがあるため（切れていたら繋ぎ直す）。
    """
    if not _slots.acquire(timeout=20):
        raise RuntimeError("DB接続の順番待ちがタイムアウトしました")
    try:
        p = _get_pool()
        conn = p.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            p.putconn(conn, close=True)
            conn = p.getconn()

        broken = False
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                broken = True
            raise
        finally:
            p.putconn(conn, close=broken)
    finally:
        _slots.release()


def query(sql, params=None) -> list[dict]:
    """SELECT 用。結果を dict のリストで返す。"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall() if cur.description else []
            return [dict(r) for r in rows]


def execute(sql, params=None) -> int:
    """INSERT / UPDATE / DELETE 用。影響した行数を返す。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.rowcount


# ---------------------------------------------------------------------------
# テーブル作成（元コードと同じ定義）
# ---------------------------------------------------------------------------

def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.raw_notes (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT DEFAULT 'line',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.money_records (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    record_date DATE NOT NULL,
                    record_type TEXT NOT NULL,  -- 'income' or 'expense'
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'confirmed', -- 'expected' or 'confirmed'
                    detail TEXT,
                    raw_note_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # 月別集計を速くするためのインデックス（無ければ作るだけ。害はない）
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_money_records_user_date "
                "ON public.money_records (user_id, record_date)"
            )


# ---------------------------------------------------------------------------
# 書き込み
# ---------------------------------------------------------------------------

def save_raw_note(user_id, body, source="line"):
    rows = query(
        "INSERT INTO public.raw_notes (user_id, body, source) VALUES (%s, %s, %s) RETURNING id;",
        (user_id, body, source),
    )
    return rows[0]["id"] if rows else None


def insert_money_record(record_date, record_type, category, title, amount,
                        status="confirmed", detail="", raw_note_id=None, user_id="default"):
    rows = query(
        """
        INSERT INTO public.money_records
        (user_id, record_date, record_type, category, title, amount, status, detail, raw_note_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (user_id, record_date, record_type, category, title, amount, status, detail, raw_note_id),
    )
    return rows[0]["id"] if rows else None


def delete_money_record(record_id: int, user_id: str) -> int:
    return execute(
        "DELETE FROM public.money_records WHERE id = %s AND user_id = %s",
        (record_id, user_id),
    )


# ---------------------------------------------------------------------------
# ダッシュボード用の集計
# ---------------------------------------------------------------------------

def fetch_monthly_totals(user_id: str) -> list[dict]:
    """月ごとの収入・支出の合計（全期間）。古い月から順。

    通算残高・年の累計収入・当月の収支・推移グラフは、すべてこの1回のクエリから作れる。
    """
    return query(
        """
        SELECT
            to_char(record_date, 'YYYY-MM') AS ym,
            COALESCE(SUM(CASE WHEN record_type = 'income'  THEN amount ELSE 0 END), 0) AS inc,
            COALESCE(SUM(CASE WHEN record_type = 'expense' THEN amount ELSE 0 END), 0) AS exp
        FROM public.money_records
        WHERE user_id = %s
        GROUP BY 1
        ORDER BY 1 ASC
        """,
        (user_id,),
    )


def fetch_category_breakdown(user_id: str, start, end) -> list[dict]:
    """[start, end) の期間の支出をカテゴリ別に合計（多い順）。"""
    return query(
        """
        SELECT category, COALESCE(SUM(amount), 0) AS cat_total
        FROM public.money_records
        WHERE user_id = %s AND record_type = 'expense'
          AND record_date >= %s AND record_date < %s
        GROUP BY category
        ORDER BY cat_total DESC
        """,
        (user_id, start, end),
    )


def fetch_records(user_id: str, start, end) -> list[dict]:
    """[start, end) の期間の明細（新しい順）。"""
    return query(
        """
        SELECT * FROM public.money_records
        WHERE user_id = %s AND record_date >= %s AND record_date < %s
        ORDER BY record_date DESC, id DESC
        """,
        (user_id, start, end),
    )


def record_exists(user_id, record_date, title, amount, record_type) -> bool:
    rows = query(
        """
        SELECT id FROM public.money_records
        WHERE user_id = %s AND record_date = %s AND title = %s AND amount = %s AND record_type = %s
        LIMIT 1
        """,
        (user_id, record_date, title, amount, record_type),
    )
    return bool(rows)
