"""
maintenance.py — DB のメンテナンス用スクリプト（手動で実行する）

    python scripts/maintenance.py seed              # 過去データのうち、DBに無いものだけ追加
    python scripts/maintenance.py dedupe            # 重複している明細を一覧表示（削除はしない）
    python scripts/maintenance.py dedupe --apply    # 重複を実際に削除（各グループの最古の1件を残す）

DATABASE_URL と APP_USER_ID は本番と同じ環境変数を使う。

元コードは、起動のたびにこの2つの処理を自動で走らせていた。
・重複の削除: 「同じ日・同じ名前・同じ金額」の明細を全部1件にまとめる。
  → コンビニでコーヒーを同じ日に2回買った、のような正当な2件も消えてしまう。
・過去データの再投入: ダッシュボードから消した過去データが、再起動のたびに復活する。
そのため、起動時の自動実行はやめて、確認しながら手動で実行する形にした。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import db  # noqa: E402
from data.past_records import PAST_RECORDS, SEED_DETAIL  # noqa: E402


def seed() -> None:
    db.init_db()
    added = 0
    for rec_date, r_type, category, title, amount in PAST_RECORDS:
        if db.record_exists(config.APP_USER_ID, rec_date, title, amount, r_type):
            continue
        db.insert_money_record(
            record_date=rec_date, record_type=r_type, category=category, title=title,
            amount=amount, status="confirmed", detail=SEED_DETAIL, user_id=config.APP_USER_ID,
        )
        added += 1
    print(f"過去データ {len(PAST_RECORDS)} 件のうち、{added} 件を追加しました（残りは登録済み）")


def dedupe(apply: bool) -> None:
    groups = db.query(
        """
        SELECT record_date, record_type, title, amount, COUNT(*) AS n, MIN(id) AS keep_id
        FROM public.money_records
        WHERE user_id = %s
        GROUP BY record_date, record_type, title, amount
        HAVING COUNT(*) > 1
        ORDER BY record_date, title
        """,
        (config.APP_USER_ID,),
    )
    if not groups:
        print("重複はありません")
        return

    print(f"同じ日・種別・名前・金額の明細が重複しているグループ: {len(groups)} 件")
    for g in groups:
        print(f"  {g['record_date']} {g['record_type']:7} {g['title']} ¥{g['amount']:,} × {g['n']}")

    if not apply:
        print("\n※ これは確認だけです。本当に別々の買い物なら削除しないでください。")
        print("  削除する場合: python scripts/maintenance.py dedupe --apply")
        return

    removed = db.execute(
        """
        DELETE FROM public.money_records a
        USING public.money_records b
        WHERE a.id > b.id AND a.user_id = b.user_id AND a.user_id = %s
          AND a.record_date = b.record_date AND a.title = b.title
          AND a.amount = b.amount AND a.record_type = b.record_type
        """,
        (config.APP_USER_ID,),
    )
    print(f"\n{removed} 件を削除しました")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    p = sub.add_parser("dedupe")
    p.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    seed() if args.cmd == "seed" else dedupe(args.apply)
