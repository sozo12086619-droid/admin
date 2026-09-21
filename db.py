"""
db.py — データの保存・読み出しを担当するファイル（SQLite）

【Phase 2 での変更点】
  - event_date 列を追加（その項目が紐づく日付。並び替えの軸になる）
  - 既に memo.db を作ってしまった人のために「マイグレーション」を用意
  - 日付順（タイムライン）で取り出せるようにした
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "memo.db"

CATEGORIES = ["買い物", "タスク", "予定", "メモ", "出来事", "やりたいこと"]
STATUSES = ["未着手", "進行中", "完了", "保留"]

# Phase 2 で増えた列。あとから追加する用の定義表
LATER_COLUMNS = {
    "event_date": "TEXT",
    "due_date": "TEXT",
    "start_at": "TEXT",
    "end_at": "TEXT",
    "all_day": "INTEGER DEFAULT 1",
    "importance": "INTEGER",
    "estimated_minutes": "INTEGER",
    "priority_score": "REAL",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブルが無ければ作り、足りない列があれば足す。"""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                body        TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT 'manual'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_note_id       INTEGER,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,

                category          TEXT NOT NULL,
                title             TEXT NOT NULL,
                detail            TEXT DEFAULT '',
                tags              TEXT DEFAULT '[]',

                date_text         TEXT,
                event_date        TEXT,
                due_date          TEXT,
                start_at          TEXT,
                end_at            TEXT,
                all_day           INTEGER DEFAULT 1,

                importance        INTEGER,
                estimated_minutes INTEGER,
                priority_score    REAL,

                status            TEXT NOT NULL DEFAULT '未着手',
                calendar_synced   INTEGER NOT NULL DEFAULT 0,

                ai_model          TEXT,
                confidence        REAL,

                FOREIGN KEY (raw_note_id) REFERENCES raw_notes(id)
            )
            """
        )
    # ★順番が大事★
    # Phase 1 で作った古い memo.db には event_date 列が無い。
    # 先に列を足してからでないと、その列にインデックスを張れずエラーになる。
    migrate()

    with get_conn() as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_event_date ON items(event_date)")


def migrate() -> None:
    """既存のDBに、後から増えた列を足す（マイグレーション）。

    「マイグレーション」＝ 中のデータを消さずにテーブルの形を変えること。
    Phase 1 で作った memo.db をそのまま使い続けられるようにするための処理。
    """
    with get_conn() as conn:
        # PRAGMA table_info で、今そのテーブルにある列の一覧が取れる
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
        for col, coltype in LATER_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} {coltype}")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def insert_raw_note(body: str, source: str = "manual") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO raw_notes (created_at, body, source) VALUES (?, ?, ?)",
            (now_iso(), body, source),
        )
        return cur.lastrowid


def insert_items(items: list[dict], raw_note_id: int | None, ai_model: str) -> int:
    """AIが分解した項目リストをまとめて保存する。保存件数を返す。"""
    ts = now_iso()
    rows = [
        (
            raw_note_id,
            ts,
            ts,
            it.get("category") or "メモ",
            (str(it.get("title") or "").strip() or "（無題）"),
            it.get("detail") or "",
            json.dumps(it.get("tags") or [], ensure_ascii=False),
            it.get("date_text"),
            it.get("event_date"),
            it.get("due_date"),
            it.get("start_at"),
            it.get("end_at"),
            1 if it.get("all_day", 1) else 0,
            it.get("importance"),
            it.get("estimated_minutes"),
            it.get("status") or "未着手",
            ai_model,
            it.get("confidence"),
        )
        for it in items
    ]

    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO items
                (raw_note_id, created_at, updated_at, category, title, detail,
                 tags, date_text, event_date, due_date, start_at, end_at, all_day,
                 importance, estimated_minutes, status, ai_model, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def fetch_items(
    categories: list[str] | None = None,
    statuses: list[str] | None = None,
    keyword: str = "",
    order: str = "timeline",
    descending: bool = True,
) -> list[sqlite3.Row]:
    """条件に合う項目を取り出す。

    order="timeline" … event_date（無ければ登録日）の日付順
    order="created"  … 登録した順
    """
    sql = "SELECT * FROM items WHERE 1=1"
    params: list = []

    if categories:
        sql += f" AND category IN ({','.join('?' for _ in categories)})"
        params.extend(categories)

    if statuses:
        sql += f" AND status IN ({','.join('?' for _ in statuses)})"
        params.extend(statuses)

    if keyword:
        sql += " AND (title LIKE ? OR detail LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    direction = "DESC" if descending else "ASC"
    if order == "timeline":
        # COALESCE(a, b, c) = 「aがNULLならb、それもNULLならc」を返すSQLの関数。
        # 日付が無い項目は登録日を使って並べる。
        # 日付ありを先に見せたいので、日付の有無でまずグループ分けしている。
        sql += (
            " ORDER BY (event_date IS NULL) ASC,"
            f" COALESCE(event_date, substr(created_at, 1, 10)) {direction},"
            " COALESCE(substr(start_at, 12, 5), '99:99') ASC, id DESC"
        )
    else:
        sql += f" ORDER BY id {direction}"

    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_raw_notes(limit: int = 50) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM raw_notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def update_item(item_id: int, **fields) -> None:
    """使い方: update_item(3, status="完了")"""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [item_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE items SET {assignments} WHERE id = ?", params)


def delete_item(item_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def existing_schedule_keys() -> set[tuple[str, str]]:
    """すでに登録済みの (日付, 開始日時) の組を集めて返す。

    シフト表を2回読み込んでしまったときに、
    同じ勤務が二重登録されるのを防ぐために使う。
    set（集合）にしておくと「入ってる?」の判定が一瞬で済む。
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT event_date, start_at FROM items "
            "WHERE event_date IS NOT NULL AND start_at IS NOT NULL"
        ).fetchall()
    return {(r["event_date"], r["start_at"]) for r in rows}


def count_by_category() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM items GROUP BY category"
        ).fetchall()
    return {r["category"]: r["n"] for r in rows}
