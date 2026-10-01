import os
import psycopg2
from collections import defaultdict

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DATA = [
    # --- 2025年07月 ---
    {"date": "2025-07-31", "type": "income", "category": "給与", "amount": 102419, "memo": "7月給与合計"},
    {"date": "2025-07-31", "type": "expense", "category": "食費", "amount": 33988, "memo": "食費"},
    {"date": "2025-07-31", "type": "expense", "category": "趣味", "amount": 37900, "memo": "趣味"},
    {"date": "2025-07-31", "type": "expense", "category": "衣服", "amount": 4200, "memo": "衣服"},
    {"date": "2025-07-31", "type": "expense", "category": "交通費", "amount": 3100, "memo": "交通費"},
    {"date": "2025-07-31", "type": "expense", "category": "日用品", "amount": 880, "memo": "日用品"},
    {"date": "2025-07-31", "type": "expense", "category": "その他", "amount": 560, "memo": "その他"},
    # --- 2025年08月 ---
    {"date": "2025-08-31", "type": "income", "category": "給与", "amount": 236937, "memo": "8月給与合計"},
    {"date": "2025-08-31", "type": "expense", "category": "趣味", "amount": 144656, "memo": "趣味"},
    {"date": "2025-08-31", "type": "expense", "category": "食費", "amount": 47474, "memo": "食費"},
    {"date": "2025-08-31", "type": "expense", "category": "交際費", "amount": 6080, "memo": "交際費"},
    {"date": "2025-08-31", "type": "expense", "category": "日用品", "amount": 3077, "memo": "日用品"},
    {"date": "2025-08-31", "type": "expense", "category": "その他", "amount": 2884, "memo": "その他"},
    {"date": "2025-08-31", "type": "expense", "category": "交通費", "amount": 2800, "memo": "交通費"},
    # --- 2025年09月 ---
    {"date": "2025-09-30", "type": "income", "category": "給与", "amount": 139957, "memo": "9月給与合計"},
    {"date": "2025-09-30", "type": "expense", "category": "趣味", "amount": 90679, "memo": "趣味"},
    {"date": "2025-09-30", "type": "expense", "category": "食費", "amount": 27374, "memo": "食費"},
    {"date": "2025-09-30", "type": "expense", "category": "日用品", "amount": 12800, "memo": "日用品"},
    {"date": "2025-09-30", "type": "expense", "category": "外食費", "amount": 3834, "memo": "外食費"},
    {"date": "2025-09-30", "type": "expense", "category": "自分磨き", "amount": 400, "memo": "自分磨き"},
    # --- 2025年10月 ---
    {"date": "2025-10-31", "type": "income", "category": "給与", "amount": 261215, "memo": "10月給与合計"},
    {"date": "2025-10-31", "type": "expense", "category": "自分磨き", "amount": 143578, "memo": "自分磨き"},
    {"date": "2025-10-31", "type": "expense", "category": "趣味", "amount": 34438, "memo": "趣味"},
    {"date": "2025-10-31", "type": "expense", "category": "食費", "amount": 14201, "memo": "食費"},
    {"date": "2025-10-31", "type": "expense", "category": "日用品", "amount": 12777, "memo": "日用品"},
    # --- 2025年11月 ---
    {"date": "2025-11-30", "type": "income", "category": "給与", "amount": 107482, "memo": "11月給与合計"},
    {"date": "2025-11-30", "type": "expense", "category": "趣味", "amount": 55694, "memo": "趣味"},
    {"date": "2025-11-30", "type": "expense", "category": "自分磨き", "amount": 55398, "memo": "自分磨き"},
    {"date": "2025-11-30", "type": "expense", "category": "その他", "amount": 50000, "memo": "その他"},
    {"date": "2025-11-30", "type": "expense", "category": "日用品", "amount": 21950, "memo": "日用品"},
    {"date": "2025-11-30", "type": "expense", "category": "食費", "amount": 10010, "memo": "食費"},
    {"date": "2025-11-30", "type": "expense", "category": "交際費", "amount": 570, "memo": "交際費"},
    # --- 2025年12月 ---
    {"date": "2025-12-31", "type": "income", "category": "給与", "amount": 143189, "memo": "12月給与合計"},
    {"date": "2025-12-31", "type": "expense", "category": "自分磨き", "amount": 80791, "memo": "自分磨き"},
    {"date": "2025-12-31", "type": "expense", "category": "趣味", "amount": 28093, "memo": "趣味"},
    {"date": "2025-12-31", "type": "expense", "category": "食費", "amount": 6799, "memo": "食費"},
    {"date": "2025-12-31", "type": "expense", "category": "交際費", "amount": 4310, "memo": "交際費"},
    {"date": "2025-12-31", "type": "expense", "category": "日用品", "amount": 1288, "memo": "日用品"},
    # --- 2026年01月 ---
    {"date": "2026-01-31", "type": "income", "category": "給与", "amount": 52313, "memo": "1月給与合計"},
    {"date": "2026-01-31", "type": "expense", "category": "趣味", "amount": 122890, "memo": "趣味"},
    {"date": "2026-01-31", "type": "expense", "category": "食費", "amount": 63458, "memo": "食費"},
    {"date": "2026-01-31", "type": "expense", "category": "日用品", "amount": 6229, "memo": "日用品"},
    {"date": "2026-01-31", "type": "expense", "category": "交際費", "amount": 700, "memo": "交際費"},
    {"date": "2026-01-31", "type": "expense", "category": "その他", "amount": 50, "memo": "その他"},
    # --- 2026年02月 ---
    {"date": "2026-02-28", "type": "income", "category": "給与", "amount": 94947, "memo": "2月給与合計"},
    {"date": "2026-02-28", "type": "expense", "category": "趣味", "amount": 34789, "memo": "趣味"},
    {"date": "2026-02-28", "type": "expense", "category": "自分磨き", "amount": 30800, "memo": "自分磨き"},
    {"date": "2026-02-28", "type": "expense", "category": "食費", "amount": 14517, "memo": "食費"},
    {"date": "2026-02-28", "type": "expense", "category": "日用品", "amount": 6328, "memo": "日用品"},
    {"date": "2026-02-28", "type": "expense", "category": "交際費", "amount": 2234, "memo": "交際費"},
    {"date": "2026-02-28", "type": "expense", "category": "外食費", "amount": 1419, "memo": "外食費"},
    {"date": "2026-02-28", "type": "expense", "category": "その他", "amount": 510, "memo": "その他"},
    # --- 2026年03月 ---
    {"date": "2026-03-31", "type": "income", "category": "給与", "amount": 119087, "memo": "3月給与合計"},
    {"date": "2026-03-31", "type": "expense", "category": "趣味", "amount": 71000, "memo": "趣味"},
    {"date": "2026-03-31", "type": "expense", "category": "食費", "amount": 19161, "memo": "食費"},
    {"date": "2026-03-31", "type": "expense", "category": "交際費", "amount": 10650, "memo": "交際費"},
    {"date": "2026-03-31", "type": "expense", "category": "その他", "amount": 9765, "memo": "その他"},
    {"date": "2026-03-31", "type": "expense", "category": "日用品", "amount": 7574, "memo": "日用品"},
    # --- 2026年04月 ---
    {"date": "2026-04-30", "type": "income", "category": "給与", "amount": 60557, "memo": "4月給与合計"},
    {"date": "2026-04-30", "type": "expense", "category": "自分磨き", "amount": 34920, "memo": "自分磨き"},
    {"date": "2026-04-30", "type": "expense", "category": "食費", "amount": 17317, "memo": "食費"},
    {"date": "2026-04-30", "type": "expense", "category": "その他", "amount": 16483, "memo": "その他"},
    {"date": "2026-04-30", "type": "expense", "category": "日用品", "amount": 8999, "memo": "日用品"},
    {"date": "2026-04-30", "type": "expense", "category": "趣味", "amount": 2500, "memo": "趣味"},
    # --- 2026年05月 ---
    {"date": "2026-05-31", "type": "income", "category": "給与", "amount": 147402, "memo": "5月給与合計"},
    {"date": "2026-05-31", "type": "expense", "category": "趣味", "amount": 41748, "memo": "趣味"},
    {"date": "2026-05-31", "type": "expense", "category": "食費", "amount": 27075, "memo": "食費"},
    {"date": "2026-05-31", "type": "expense", "category": "自分磨き", "amount": 24902, "memo": "自分磨き"},
    {"date": "2026-05-31", "type": "expense", "category": "日用品", "amount": 15019, "memo": "日用品"},
    {"date": "2026-05-31", "type": "expense", "category": "その他", "amount": 14580, "memo": "その他"},
    {"date": "2026-05-31", "type": "expense", "category": "交際費", "amount": 3168, "memo": "交際費"},
    {"date": "2026-05-31", "type": "expense", "category": "交通費", "amount": 3100, "memo": "交通費"},
    # --- 2026年06月 ---
    {"date": "2026-06-30", "type": "income", "category": "給与", "amount": 170708, "memo": "6月給与合計"},
    {"date": "2026-06-30", "type": "expense", "category": "自分磨き", "amount": 79780, "memo": "自分磨き"},
    {"date": "2026-06-30", "type": "expense", "category": "交際費", "amount": 34590, "memo": "交際費"},
    {"date": "2026-06-30", "type": "expense", "category": "食費", "amount": 27098, "memo": "食費"},
    {"date": "2026-06-30", "type": "expense", "category": "日用品", "amount": 19159, "memo": "日用品"},
    {"date": "2026-06-30", "type": "expense", "category": "ガソリン", "amount": 3500, "memo": "ガソリン"},
    {"date": "2026-06-30", "type": "expense", "category": "趣味", "amount": 3030, "memo": "趣味"},
    {"date": "2026-06-30", "type": "expense", "category": "その他", "amount": 2970, "memo": "その他"},
    # --- 2026年07月 ---
    {"date": "2026-07-31", "type": "income", "category": "給与", "amount": 78204, "memo": "7月給与合計"},
    {"date": "2026-07-31", "type": "expense", "category": "自分磨き", "amount": 34078, "memo": "自分磨き"},
    {"date": "2026-07-31", "type": "expense", "category": "食費", "amount": 33401, "memo": "食費"},
    {"date": "2026-07-31", "type": "expense", "category": "日用品", "amount": 12000, "memo": "日用品"},
    {"date": "2026-07-31", "type": "expense", "category": "趣味", "amount": 9079, "memo": "趣味"},
    {"date": "2026-07-31", "type": "expense", "category": "交際費", "amount": 7925, "memo": "交際費"},
    {"date": "2026-07-31", "type": "expense", "category": "Amazon", "amount": 5312, "memo": "Amazon"},
    {"date": "2026-07-31", "type": "expense", "category": "ガソリン", "amount": 4800, "memo": "ガソリン"},
    # --- 2026年08月 ---
    {"date": "2026-08-31", "type": "income", "category": "給与", "amount": 117308, "memo": "8月給与合計"},
    {"date": "2026-08-31", "type": "expense", "category": "趣味", "amount": 69119, "memo": "趣味"},
    {"date": "2026-08-31", "type": "expense", "category": "食費", "amount": 22352, "memo": "食費"},
    {"date": "2026-08-31", "type": "expense", "category": "日用品", "amount": 13028, "memo": "日用品"},
    {"date": "2026-08-31", "type": "expense", "category": "ガソリン", "amount": 4033, "memo": "ガソリン"},
    {"date": "2026-08-31", "type": "expense", "category": "交際費", "amount": 3276, "memo": "交際費"},
    {"date": "2026-08-31", "type": "expense", "category": "その他", "amount": 160, "memo": "その他"},

    # --- 2026年09月（銀行口座・レシート・PayPay） ---
    {"date": "2026-09-01", "type": "expense", "category": "趣味", "amount": 1180, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-01", "type": "income", "category": "臨時収入", "amount": 900, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 935, "memo": "VISAデビット"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 280, "memo": "すき家(PayPay)"},
    {"date": "2026-09-02", "type": "expense", "category": "食費", "amount": 677, "memo": "サンエー(PayPay)"},
    {"date": "2026-09-03", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 146, "memo": "VISAデビット"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 890, "memo": "VISAデビット"},
    {"date": "2026-09-04", "type": "expense", "category": "食費", "amount": 1825, "memo": "VISAデビット"},
    {"date": "2026-09-05", "type": "expense", "category": "食費", "amount": 151, "memo": "ファミリーマート(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "趣味", "amount": 50, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "趣味", "amount": 1900, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "日用品", "amount": 990, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "食費", "amount": 862, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-07", "type": "expense", "category": "日用品", "amount": 1782, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-08", "type": "expense", "category": "日用品", "amount": 2692, "memo": "VISAデビット"},
    {"date": "2026-09-08", "type": "expense", "category": "食費", "amount": 270, "memo": "すき家(PayPay)"},
    {"date": "2026-09-08", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-09", "type": "expense", "category": "食費", "amount": 2912, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-09", "type": "expense", "category": "食費", "amount": 7314, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-09", "type": "expense", "category": "その他", "amount": 5336, "memo": "口座出金"},
    {"date": "2026-09-09", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-10", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-11", "type": "expense", "category": "趣味", "amount": 600, "memo": "Amazonプライム(PayPay)"},
    {"date": "2026-09-11", "type": "expense", "category": "日用品", "amount": 1210, "memo": "ダイソー(PayPay)"},
    {"date": "2026-09-14", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-14", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-15", "type": "expense", "category": "食費", "amount": 210, "memo": "VISAデビット"},
    {"date": "2026-09-16", "type": "expense", "category": "日用品", "amount": 3657, "memo": "VISAデビット"},
    {"date": "2026-09-16", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-16", "type": "expense", "category": "日用品", "amount": 3727, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-17", "type": "expense", "category": "食費", "amount": 344, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-17", "type": "expense", "category": "食費", "amount": 640, "memo": "すき家(PayPay)"},
    {"date": "2026-09-17", "type": "income", "category": "臨時収入", "amount": 300, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-19", "type": "expense", "category": "自分磨き", "amount": 77220, "memo": "VISAデビット(クリニック等)"},
    {"date": "2026-09-21", "type": "expense", "category": "食費", "amount": 280, "memo": "VISAデビット"},
    {"date": "2026-09-21", "type": "expense", "category": "食費", "amount": 135, "memo": "VISAデビット"},
    {"date": "2026-09-22", "type": "expense", "category": "食費", "amount": 210, "memo": "VISAデビット"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 4853, "memo": "ユニオン(レシート)"},
    {"date": "2026-09-23", "type": "expense", "category": "日用品", "amount": 2296, "memo": "VISAデビット"},
    {"date": "2026-09-23", "type": "expense", "category": "趣味", "amount": 470, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "趣味", "amount": 50, "memo": "Appleサービス(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-23", "type": "expense", "category": "食費", "amount": 267, "memo": "サンエー(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 108, "memo": "セブン-イレブン(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "食費", "amount": 320, "memo": "すき家(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "日用品", "amount": 682, "memo": "マツモトキヨシ(PayPay)"},
    {"date": "2026-09-25", "type": "expense", "category": "日用品", "amount": 2095, "memo": "Amazon(PayPay)"},
    {"date": "2026-09-25", "type": "income", "category": "臨時収入", "amount": 1000, "memo": "217さん受取(PayPay)"},
    {"date": "2026-09-26", "type": "expense", "category": "食費", "amount": 210, "memo": "すき家(PayPay)"},
    {"date": "2026-09-27", "type": "expense", "category": "食費", "amount": 1065, "memo": "ミスタードーナツ(PayPay)"},
    {"date": "2026-09-28", "type": "expense", "category": "趣味", "amount": 5478, "memo": "カイカツFIT(ジム会費)"},
    {"date": "2026-09-28", "type": "expense", "category": "日用品", "amount": 6610, "memo": "VISAデビット"},
    {"date": "2026-09-28", "type": "expense", "category": "日用品", "amount": 1700, "memo": "VISAデビット"},
]

def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns 
        WHERE table_schema = 'public';
    """)
    rows = cur.fetchall()
    table_cols = defaultdict(dict)
    for t, c, dt, null in rows:
        table_cols[t][c] = {"type": dt, "nullable": null}
        
    target_table = "money_records" if "money_records" in table_cols else "records"
    print(f"Target table: {target_table}")
    
    cols = table_cols[target_table]
    print(f"Columns: {list(cols.keys())}")
    
    # user_id の自動解決
    user_id_val = None
    if "user_id" in cols:
        for ut in ["users", "line_users", "user"]:
            if ut in table_cols:
                try:
                    cur.execute(f"SELECT id FROM {ut} LIMIT 1;")
                    r = cur.fetchone()
                    if r:
                        user_id_val = r[0]
                        print(f"Using user_id from {ut}: {user_id_val}")
                        break
                except Exception:
                    conn.rollback()
        
        if user_id_val is None and "raw_notes" in table_cols:
            try:
                for c in ["user_id", "line_user_id"]:
                    if c in table_cols["raw_notes"]:
                        cur.execute(f"SELECT {c} FROM raw_notes WHERE {c} IS NOT NULL LIMIT 1;")
                        r = cur.fetchone()
                        if r:
                            user_id_val = r[0]
                            print(f"Using user_id from raw_notes: {user_id_val}")
                            break
            except Exception:
                conn.rollback()

        # 外部キー制約の検出
        cur.execute("""
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
              AND kcu.column_name = 'user_id';
        """, (target_table,))
        fk = cur.fetchone()
        
        if fk:
            fk_table, fk_col = fk[0], fk[1]
            try:
                cur.execute(f"SELECT {fk_col} FROM {fk_table} LIMIT 1;")
                r = cur.fetchone()
                if r:
                    user_id_val = r[0]
                else:
                    cur.execute(f"INSERT INTO {fk_table} DEFAULT VALUES RETURNING {fk_col};")
                    user_id_val = cur.fetchone()[0]
                    conn.commit()
            except Exception:
                conn.rollback()

        if user_id_val is None:
            uid_type = cols["user_id"]["type"]
            user_id_val = 1 if "int" in uid_type else "default_user"
            print(f"Fallback user_id: {user_id_val}")

    # 既存データを初期化
    cur.execute(f"TRUNCATE TABLE {target_table} RESTART IDENTITY CASCADE;")

    def find_col(candidates):
        for c in candidates:
            if c in cols:
                return c
        return None

    d_col = find_col(["date", "trans_date", "record_date", "expense_date", "created_at"])
    a_col = find_col(["amount", "price", "cost", "value"])
    c_col = find_col(["category", "category_name", "genre"])
    m_col = find_col(["memo", "description", "note", "title", "content"])
    t_col = find_col(["type", "transaction_type", "record_type", "category_type", "kind"])
    s_col = find_col(["status"])

    count = 0
    for row in DATA:
        insert_cols = []
        vals = []

        if "user_id" in cols:
            insert_cols.append("user_id")
            vals.append(user_id_val)
        if d_col:
            insert_cols.append(d_col)
            vals.append(row["date"])
        if a_col:
            insert_cols.append(a_col)
            vals.append(row["amount"])
        if c_col:
            insert_cols.append(c_col)
            vals.append(row["category"])
        if m_col:
            insert_cols.append(m_col)
            vals.append(row["memo"])
        if t_col:
            insert_cols.append(t_col)
            vals.append(row["type"])
        if s_col:
            insert_cols.append(s_col)
            vals.append("confirmed")

        col_str = ", ".join(insert_cols)
        ph = ", ".join(["%s"] * len(vals))
        cur.execute(f"INSERT INTO {target_table} ({col_str}) VALUES ({ph});", tuple(vals))
        count += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully inserted {count} records into {target_table}!")

if __name__ == "__main__":
    run()
