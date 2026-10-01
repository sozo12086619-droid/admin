"""
db.py — 家計簿アプリ ＆ 初代admin（シフト・予定管理）統合版DBモジュール
"""

import json
import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

import config

logger = logging.getLogger(__name__)

# --- 初代admin用の定数 ---------------------------------------------------
CATEGORIES = ["買い物", "タスク", "予定", "メモ", "出来事", "やりたいこと"]
STATUSES = ["未着手", "完了"]

# --- コネクションプール設定 -----------------------------------------------
_MAXCONN = 5
_pool = None
_pool_lock = threading.Lock()
_slots = threading.BoundedSemaphore(_MAXCONN)


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            if not config.DATABASE_URL:
                raise RuntimeError("DATABASE_URL が設定されていません")
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
            except Exception:
                pass
            _pool = None


@contextmanager
def get_conn():
    """プールから接続を借り、終わったら返す。"""
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
            except Exception:
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
# テーブル初期化（家計簿用 ＋ 初代admin用）
# ---------------------------------------------------------------------------

def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. 家計簿・共通 原文ログテーブル
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.raw_notes (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT DEFAULT 'default',
                    body TEXT NOT NULL,
                    source TEXT DEFAULT 'line',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # 2. 家計簿データテーブル
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.money_records (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    record_date DATE NOT NULL,
                    record_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT DEFAULT 'confirmed',
                    detail TEXT,
                    raw_note_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_money_records_user_date "
                "ON public.money_records (user_id, record_date)"
            )
            # 3. 初代admin（シフト・予定・メモ）用テーブル
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.items (
                    id SERIAL PRIMARY KEY,
                    raw_note_id INTEGER,
                    category TEXT,
                    title TEXT,
                    detail TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    event_date DATE,
                    start_at TEXT,
                    end_at TEXT,
                    due_date DATE,
                    date_text TEXT,
                    all_day INTEGER DEFAULT 1,
                    estimated_minutes INTEGER,
                    importance INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT '未着手',
                    calendar_synced INTEGER DEFAULT 0,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)


# ---------------------------------------------------------------------------
# 初代admin（Streamlit）用の関数群
# ---------------------------------------------------------------------------

def count_by_category() -> dict[str, int]:
    rows = query("SELECT category, COUNT(*) as cnt FROM public.items GROUP BY category;")
    return {r["category"]: r["cnt"] for r in rows}


def insert_raw_note(body: str, source: str = "web", user_id: str = "default") -> int:
    rows = query(
        "INSERT INTO public.raw_notes (user_id, body, source) VALUES (%s, %s, %s) RETURNING id;",
        (user_id, body, source),
    )
    return rows[0]["id"] if rows else None


def insert_items(items: list[dict], raw_note_id: int, model: str = "") -> int:
    count = 0
    for it in items:
        tags = it.get("tags", [])
        tags_str = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else str(tags or "[]")
        execute(
            """
            INSERT INTO public.items
            (raw_note_id, category, title, detail, tags, event_date, start_at, end_at,
             due_date, date_text, all_day, estimated_minutes, importance, confidence, status, calendar_synced, model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                raw_note_id,
                it.get("category", "メモ"),
                it.get("title", ""),
                it.get("detail", ""),
                tags_str,
                it.get("event_date") or None,
                it.get("start_at") or None,
                it.get("end_at") or None,
                it.get("due_date") or None,
                it.get("date_text", ""),
                it.get("all_day", 1),
                it.get("estimated_minutes"),
                it.get("importance", 1),
                float(it.get("confidence") or 1.0),
                it.get("status", "未着手"),
                it.get("calendar_synced", 0),
                model,
            ),
        )
        count += 1
    return count


def existing_schedule_keys() -> set[tuple]:
    rows = query("SELECT event_date::text AS ed, start_at FROM public.items WHERE event_date IS NOT NULL;")
    return {(r["ed"], r["start_at"]) for r in rows}


def fetch_items(sel_cats=None, statuses=None, keyword="", order="timeline", descending=True) -> list[dict]:
    clauses = []
    params = []
    if sel_cats:
        clauses.append("category = ANY(%s)")
        params.append(sel_cats)
    if statuses:
        clauses.append("status = ANY(%s)")
        params.append(statuses)
    if keyword:
        clauses.append("(title ILIKE %s OR detail ILIKE %s)")
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    if order == "created":
        order_sql = "ORDER BY id DESC" if descending else "ORDER BY id ASC"
    else:
        direction = "DESC" if descending else "ASC"
        order_sql = f"ORDER BY event_date {direction} NULLS LAST, start_at {direction} NULLS LAST, id {direction}"

    sql = f"""
        SELECT id, raw_note_id, category, title, detail, tags,
               event_date::text AS event_date,
               start_at, end_at,
               due_date::text AS due_date,
               date_text, all_day, estimated_minutes, importance, confidence,
               status, calendar_synced, model, created_at
        FROM public.items
        {where_sql}
        {order_sql};
    """
    return query(sql, params)


def update_item(item_id: int, **kwargs) -> int:
    if not kwargs:
        return 0
    set_parts = [f"{k} = %s" for k in kwargs.keys()]
    vals = list(kwargs.values()) + [item_id]
    return execute(f"UPDATE public.items SET {', '.join(set_parts)} WHERE id = %s", vals)


def delete_item(item_id: int) -> int:
    return execute("DELETE FROM public.items WHERE id = %s", (item_id,))


def fetch_raw_notes() -> list[dict]:
    return query(
        "SELECT id, body, source, to_char(created_at, 'YYYY-MM-DD HH24:MI') as created_at "
        "FROM public.raw_notes ORDER BY id DESC LIMIT 100;"
    )


# ---------------------------------------------------------------------------
# 家計簿アプリ（Render）用の関数群
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


def fetch_monthly_totals(user_id: str) -> list[dict]:
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
