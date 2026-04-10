"""SQLite хранилище: звонки, пользователи, настройки, теги."""
import sqlite3
import json
import os
import hashlib
import secrets
from config import DB_PATH


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_files (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                filename     TEXT NOT NULL,
                display_name TEXT NOT NULL,
                uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                uploaded_by  INTEGER REFERENCES users(id),
                owner_id     INTEGER REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_files (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                content      TEXT NOT NULL,
                uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                uploaded_by  INTEGER REFERENCES users(id),
                owner_id     INTEGER REFERENCES users(id),
                is_universal INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                filename         TEXT UNIQUE NOT NULL,
                call_date        TEXT,
                call_time        TEXT,
                upload_batch     TEXT,
                operator         TEXT,
                duration         INTEGER,
                status           TEXT DEFAULT 'pending',
                transcript       TEXT,
                analysis_raw     TEXT,
                result           TEXT,
                service          TEXT,
                score            INTEGER,
                tone             TEXT,
                call_quality     TEXT,
                operator_errors  TEXT,
                incorrect_info   TEXT,
                summary          TEXT,
                recommendations  TEXT,
                appointment_date TEXT,
                patient_name     TEXT,
                tags             TEXT,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_at     DATETIME,
                user_id          INTEGER REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                username          TEXT UNIQUE NOT NULL,
                password          TEXT NOT NULL,
                role              TEXT NOT NULL DEFAULT 'viewer',
                gigachat_token    TEXT DEFAULT '',
                salute_token      TEXT DEFAULT '',
                theme             TEXT DEFAULT 'light',
                active_price_id   INTEGER REFERENCES price_files(id),
                active_prompt_id  INTEGER REFERENCES prompt_files(id),
                created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tags_catalog (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT UNIQUE NOT NULL,
                color      TEXT DEFAULT '#6366F1',
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _migrate(conn)
        conn.commit()

    _ensure_defaults()

    if not get_user_by_username("admin"):
        create_user("admin", "admin", "admin")
        print("[db] Default admin created: admin / admin")


def _migrate(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(calls)").fetchall()}
    new_cols = {
        "user_id":         "INTEGER REFERENCES users(id)",
        "upload_batch":    "TEXT",
        "tone":            "TEXT",
        "call_quality":    "TEXT",
        "appointment_date": "TEXT",
        "patient_name":    "TEXT",
        "operator":        "TEXT",
        "duration":        "INTEGER",
        "tags":            "TEXT",
    }
    for col, definition in new_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE calls ADD COLUMN {col} {definition}")

    ucols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "gigachat_token" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN gigachat_token TEXT DEFAULT ''")
    if "theme" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'light'")
    if "salute_token" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN salute_token TEXT DEFAULT ''")
    if "active_price_id" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN active_price_id INTEGER REFERENCES price_files(id)")
    if "active_prompt_id" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN active_prompt_id INTEGER REFERENCES prompt_files(id)")
    if "whisper_prompt" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN whisper_prompt TEXT DEFAULT ''")

    pcols = {row[1] for row in conn.execute("PRAGMA table_info(price_files)").fetchall()}
    if "owner_id" not in pcols:
        conn.execute("ALTER TABLE price_files ADD COLUMN owner_id INTEGER REFERENCES users(id)")

    prcols = {row[1] for row in conn.execute("PRAGMA table_info(prompt_files)").fetchall()}
    if "owner_id" not in prcols:
        conn.execute("ALTER TABLE prompt_files ADD COLUMN owner_id INTEGER REFERENCES users(id)")
    if "is_universal" not in prcols:
        conn.execute("ALTER TABLE prompt_files ADD COLUMN is_universal INTEGER DEFAULT 0")


def _ensure_defaults():
    defaults = {
        "conversion_mode":    "filtered",
        "conversion_enabled": "1",
        "quality_enabled":    "1",
    }
    with get_conn() as conn:
        for key, val in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (key, val))
        conn.commit()


# ─── Настройки ───────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
        conn.commit()


def get_all_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ─── Авторизация ─────────────────────────────────────────────────────────────

def _hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"


def _check_password(password, stored):
    try:
        salt, h = stored.split(":", 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == h
    except Exception:
        return False


def create_user(username, password, role="viewer"):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?,?,?)",
                (username.strip(), _hash_password(password), role)
            )
            conn.commit()
            return get_user_by_username(username)
    except Exception:
        return None


def get_user_by_username(username):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def authenticate(username, password):
    user = get_user_by_username(username)
    if user and _check_password(password, user["password"]):
        return user
    return None


def get_all_users():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()]


def delete_user(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()


def change_password(user_id, new_password):
    with get_conn() as conn:
        conn.execute("UPDATE users SET password=? WHERE id=?",
                     (_hash_password(new_password), user_id))
        conn.commit()


def set_user_gigachat_token(user_id, token):
    with get_conn() as conn:
        conn.execute("UPDATE users SET gigachat_token=? WHERE id=?", (token, user_id))
        conn.commit()


def get_user_gigachat_token(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT gigachat_token FROM users WHERE id=?", (user_id,)).fetchone()
        return row["gigachat_token"] if row else ""


def set_user_salute_token(user_id, token):
    with get_conn() as conn:
        conn.execute("UPDATE users SET salute_token=? WHERE id=?", (token, user_id))
        conn.commit()


def get_user_salute_token(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT salute_token FROM users WHERE id=?", (user_id,)).fetchone()
        return row["salute_token"] if row else ""


def set_user_whisper_prompt(user_id, prompt):
    with get_conn() as conn:
        conn.execute("UPDATE users SET whisper_prompt=? WHERE id=?", (prompt, user_id))
        conn.commit()


def get_user_whisper_prompt(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT whisper_prompt FROM users WHERE id=?", (user_id,)).fetchone()
        return row["whisper_prompt"] if row else ""


def set_user_theme(user_id, theme):
    with get_conn() as conn:
        conn.execute("UPDATE users SET theme=? WHERE id=?", (theme, user_id))
        conn.commit()


def get_user_theme(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT theme FROM users WHERE id=?", (user_id,)).fetchone()
        return row["theme"] if row else "light"


# ─── Звонки ──────────────────────────────────────────────────────────────────

def upsert_call(filename, call_date=None, call_time=None,
                user_id=None, upload_batch=None, operator=None, duration=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO calls
               (filename, call_date, call_time, status, user_id, upload_batch, operator, duration)
               VALUES (?,?,?,'pending',?,?,?,?)""",
            (filename, call_date, call_time, user_id, upload_batch, operator, duration)
        )
        conn.commit()
        row = conn.execute("SELECT id FROM calls WHERE filename=?", (filename,)).fetchone()
        return row["id"]


def set_status(call_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE calls SET status=? WHERE id=?", (status, call_id))
        conn.commit()


def save_transcript(call_id, transcript):
    with get_conn() as conn:
        conn.execute("UPDATE calls SET transcript=?, status='analyzing' WHERE id=?",
                     (transcript, call_id))
        conn.commit()


def _scalar(v):
    if v is None:
        return None
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def save_analysis(call_id, analysis):
    errors = analysis.get("operator_errors", [])
    formatted = analysis.get("formatted_transcript")
    with get_conn() as conn:
        base_fields = """
            status='done',
            analysis_raw=?,
            result=?,
            service=?,
            score=?,
            tone=?,
            call_quality=?,
            operator_errors=?,
            incorrect_info=?,
            summary=?,
            recommendations=?,
            appointment_date=?,
            patient_name=?,
            processed_at=CURRENT_TIMESTAMP
        """
        params = (
            json.dumps(analysis, ensure_ascii=False),
            _scalar(analysis.get("result")),
            _scalar(analysis.get("service")),
            analysis.get("score"),
            _scalar(analysis.get("tone")),
            _scalar(analysis.get("call_quality")),
            json.dumps(errors, ensure_ascii=False) if isinstance(errors, list) else _scalar(errors),
            _scalar(analysis.get("incorrect_service_info") or analysis.get("incorrect_info")),
            _scalar(analysis.get("summary")),
            _scalar(analysis.get("recommendations")),
            _scalar(analysis.get("appointment_date")),
            _scalar(analysis.get("patient_name")),
            call_id,
        )
        if formatted:
            conn.execute(f"UPDATE calls SET transcript=?, {base_fields} WHERE id=?",
                         (_scalar(formatted),) + params)
        else:
            conn.execute(f"UPDATE calls SET {base_fields} WHERE id=?", params)
        conn.commit()


def set_error(call_id, message):
    with get_conn() as conn:
        conn.execute(
            "UPDATE calls SET status='error', summary=?, processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (message, call_id)
        )
        conn.commit()


def set_cancelled(call_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE calls SET status='cancelled' WHERE id=? AND status IN ('pending','transcribing','analyzing')",
            (call_id,)
        )
        conn.commit()


def cancel_all_pending(user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            r = conn.execute(
                "UPDATE calls SET status='cancelled' WHERE status IN ('pending','transcribing','analyzing') AND user_id=?",
                (user_id,)
            )
        else:
            r = conn.execute(
                "UPDATE calls SET status='cancelled' WHERE status IN ('pending','transcribing','analyzing')"
            )
        conn.commit()
        return r.rowcount


def update_call_operator(call_id, operator, user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            conn.execute("UPDATE calls SET operator=? WHERE id=? AND user_id=?",
                         (operator, call_id, user_id))
        else:
            conn.execute("UPDATE calls SET operator=? WHERE id=?", (operator, call_id))
        conn.commit()


def clear_operator_if_auto(call_id):
    """Сбрасывает оператора перед переобработкой, чтобы новый анализ заполнил его заново."""
    with get_conn() as conn:
        conn.execute("UPDATE calls SET operator=NULL WHERE id=?", (call_id,))
        conn.commit()


def update_call_tags(call_id, tags, user_id=None):
    tags_str = ",".join(t.strip() for t in tags if t.strip()) if isinstance(tags, list) else (tags or "")
    with get_conn() as conn:
        if user_id is not None:
            conn.execute("UPDATE calls SET tags=? WHERE id=? AND user_id=?",
                         (tags_str, call_id, user_id))
        else:
            conn.execute("UPDATE calls SET tags=? WHERE id=?", (tags_str, call_id))
        conn.commit()


def _parse_call(r):
    d = dict(r)
    if d.get("operator_errors"):
        try:
            d["operator_errors"] = json.loads(d["operator_errors"])
        except Exception:
            d["operator_errors"] = [d["operator_errors"]]
    else:
        d["operator_errors"] = []
    if d.get("tags"):
        d["tags"] = [t.strip() for t in d["tags"].split(",") if t.strip()]
    else:
        d["tags"] = []
    return d


def get_all_calls(user_id=None, date_from=None, date_to=None,
                  operator=None, result=None, search=None, sort_by=None, sort_dir="desc"):
    allowed_sort = {"call_date", "created_at", "result", "score", "operator", "duration", "filename"}
    if sort_by not in allowed_sort:
        sort_by = "created_at"
    sort_dir = "ASC" if sort_dir == "asc" else "DESC"

    # call_date хранится в DD.MM.YYYY — нормализуем к YYYY-MM-DD для сравнения
    _norm = ("CASE WHEN call_date GLOB '??.??.????' "
             "THEN substr(call_date,7,4)||'-'||substr(call_date,4,2)||'-'||substr(call_date,1,2) "
             "ELSE call_date END")

    conditions = []
    params = []
    if user_id is not None:
        conditions.append("user_id=?")
        params.append(user_id)
    if date_from:
        conditions.append(f"({_norm} >= ? OR (call_date IS NULL AND created_at >= ?))")
        params += [date_from, date_from]
    if date_to:
        conditions.append(f"({_norm} <= ? OR (call_date IS NULL AND created_at <= ?))")
        params += [date_to, date_to]
    if operator:
        conditions.append("operator=?")
        params.append(operator)
    if result:
        conditions.append("result=?")
        params.append(result)
    if search:
        conditions.append("(filename LIKE ? OR service LIKE ? OR transcript LIKE ? OR patient_name LIKE ?)")
        s = f"%{search}%"
        params += [s, s, s, s]

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM calls {where} ORDER BY {sort_by} {sort_dir}, id {sort_dir}"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_parse_call(r) for r in rows]


def get_stats(user_id=None, date_from=None, date_to=None, operator=None):
    conversion_mode    = get_setting("conversion_mode",    "filtered")
    conversion_enabled = get_setting("conversion_enabled", "1") == "1"
    quality_enabled    = get_setting("quality_enabled",    "1") == "1"

    _norm = ("CASE WHEN call_date GLOB '??.??.????' "
             "THEN substr(call_date,7,4)||'-'||substr(call_date,4,2)||'-'||substr(call_date,1,2) "
             "ELSE call_date END")

    conditions = []
    params = []
    if user_id is not None:
        conditions.append("user_id=?")
        params.append(user_id)
    if date_from:
        conditions.append(f"({_norm} >= ? OR (call_date IS NULL AND created_at >= ?))")
        params += [date_from, date_from]
    if date_to:
        conditions.append(f"({_norm} <= ? OR (call_date IS NULL AND created_at <= ?))")
        params += [date_to, date_to]
    if operator:
        conditions.append("operator=?")
        params.append(operator)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_conn() as conn:
        def q(extra_where, p=()):
            sql = f"SELECT COUNT(*) FROM calls {where}"
            if extra_where:
                sql += (" AND " if where else " WHERE ") + extra_where
            return conn.execute(sql, list(params) + list(p)).fetchone()[0]

        total        = q("")
        done         = q("status='done'")
        pending      = q("status IN ('pending','transcribing','analyzing')")
        errors       = q("status='error'")
        enrolled     = q("result='записан'")
        not_enrolled = q("result='не записан'")
        missed       = q("result IN ('недозвон','перезвон')")
        spravka      = q("result='справка'")
        other        = q("result IN ('прочее','другое')")

        avg_row = conn.execute(
            f"SELECT AVG(score) FROM calls {where}" +
            (" AND " if where else " WHERE ") + "status='done' AND score IS NOT NULL",
            params
        ).fetchone()
        avg_score = round(avg_row[0], 1) if avg_row[0] is not None else None

        if conversion_mode == "filtered":
            conv_base = enrolled + not_enrolled
        else:
            conv_base = enrolled + not_enrolled + missed + spravka + other

        conversion = round(enrolled / conv_base * 100, 1) if conv_base > 0 else 0

    return {
        "total": total, "done": done, "pending": pending, "errors": errors,
        "enrolled": enrolled, "not_enrolled": not_enrolled,
        "missed": missed, "spravka": spravka, "other": other,
        "avg_score": avg_score, "conversion": conversion,
        "conversion_mode": conversion_mode,
        "conversion_enabled": conversion_enabled,
        "quality_enabled": quality_enabled,
    }


def get_period_stats(user_id=None, operator=None):
    """Статистика за текущую неделю и месяц vs предыдущий период."""
    from datetime import date, timedelta
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    prev_week_start = (today - timedelta(days=today.weekday() + 7)).isoformat()
    prev_week_end = (today - timedelta(days=today.weekday() + 1)).isoformat()
    month_start = today.replace(day=1).isoformat()
    prev_month_end = (today.replace(day=1) - timedelta(days=1)).isoformat()
    prev_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()

    def period_conv(date_from, date_to):
        s = get_stats(user_id=user_id, date_from=date_from, date_to=date_to, operator=operator)
        return {
            "total": s["total"],
            "enrolled": s["enrolled"],
            "conversion": s["conversion"],
            "avg_score": s["avg_score"],
        }

    return {
        "this_week":  period_conv(week_start, today.isoformat()),
        "prev_week":  period_conv(prev_week_start, prev_week_end),
        "this_month": period_conv(month_start, today.isoformat()),
        "prev_month": period_conv(prev_month_start, prev_month_end),
    }


def get_call(call_id, user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT * FROM calls WHERE id=? AND user_id=?", (call_id, user_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        return _parse_call(row) if row else None


def delete_call(call_id, user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT filename FROM calls WHERE id=? AND user_id=?", (call_id, user_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT filename FROM calls WHERE id=?", (call_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM calls WHERE id=?", (call_id,))
        conn.commit()
        return row["filename"]


def delete_all_calls(user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            rows = conn.execute("SELECT filename FROM calls WHERE user_id=?", (user_id,)).fetchall()
            filenames = [r["filename"] for r in rows]
            conn.execute("DELETE FROM calls WHERE user_id=?", (user_id,))
        else:
            rows = conn.execute("SELECT filename FROM calls").fetchall()
            filenames = [r["filename"] for r in rows]
            conn.execute("DELETE FROM calls")
        conn.commit()
        return filenames


def delete_calls_by_batch(batch, user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT filename FROM calls WHERE upload_batch=? AND user_id=?", (batch, user_id)
            ).fetchall()
            conn.execute("DELETE FROM calls WHERE upload_batch=? AND user_id=?", (batch, user_id))
        else:
            rows = conn.execute(
                "SELECT filename FROM calls WHERE upload_batch=?", (batch,)
            ).fetchall()
            conn.execute("DELETE FROM calls WHERE upload_batch=?", (batch,))
        conn.commit()
        return [r["filename"] for r in rows]


def get_pending_ids():
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM calls WHERE status='pending'").fetchall()
        return [r[0] for r in rows]


def get_operators_list(user_id=None):
    with get_conn() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT DISTINCT operator FROM calls WHERE user_id=? AND operator IS NOT NULL AND operator != '' ORDER BY operator",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT operator FROM calls WHERE operator IS NOT NULL AND operator != '' ORDER BY operator"
            ).fetchall()
        return [r["operator"] for r in rows]


# ─── Прайс-файлы (per-user) ───────────────────────────────────────────────────

def add_price_file(filename, display_name, user_id):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO price_files (filename, display_name, uploaded_by, owner_id) VALUES (?,?,?,?)",
            (filename, display_name, user_id, user_id)
        )
        conn.commit()
        return cur.lastrowid


def get_price_files(user_id):
    """Возвращает прайсы текущего пользователя."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pf.id, pf.filename, pf.display_name, pf.uploaded_at, pf.owner_id, u.username, "
            "(SELECT active_price_id FROM users WHERE id=?) = pf.id AS is_active "
            "FROM price_files pf LEFT JOIN users u ON u.id=pf.uploaded_by "
            "WHERE pf.owner_id=? ORDER BY pf.id DESC",
            (user_id, user_id)
        ).fetchall()
        return [dict(r) for r in rows]


def activate_price(price_id, user_id):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active_price_id=? WHERE id=?", (price_id, user_id))
        conn.commit()


def deactivate_price(user_id):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active_price_id=NULL WHERE id=?", (user_id,))
        conn.commit()


def delete_price_file(price_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename FROM price_files WHERE id=? AND owner_id=?", (price_id, user_id)
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE users SET active_price_id=NULL WHERE active_price_id=?", (price_id,))
        conn.execute("DELETE FROM price_files WHERE id=?", (price_id,))
        conn.commit()
        return row["filename"]


def get_price_content(price_id):
    with get_conn() as conn:
        row = conn.execute("SELECT filename FROM price_files WHERE id=?", (price_id,)).fetchone()
        if not row:
            return None
        price_dir = os.environ.get("PRICE_DIR", "/app/price")
        path = os.path.join(price_dir, row["filename"])
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()


def update_price_content(price_id, content):
    with get_conn() as conn:
        row = conn.execute("SELECT filename FROM price_files WHERE id=?", (price_id,)).fetchone()
        if not row:
            return
        price_dir = os.environ.get("PRICE_DIR", "/app/price")
        path = os.path.join(price_dir, row["filename"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def get_active_price_for_user(user_id):
    """Возвращает путь к активному прайсу пользователя или None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT pf.filename FROM price_files pf "
            "JOIN users u ON u.active_price_id=pf.id "
            "WHERE u.id=?", (user_id,)
        ).fetchone()
        return row["filename"] if row else None


# ─── Промт-файлы (per-user + универсальные) ───────────────────────────────────

def add_prompt(display_name, content, user_id, is_universal=False):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO prompt_files (display_name, content, uploaded_by, owner_id, is_universal) VALUES (?,?,?,?,?)",
            (display_name, content, user_id, None if is_universal else user_id, 1 if is_universal else 0)
        )
        conn.commit()
        return cur.lastrowid


def get_prompt_files(user_id):
    """Промты пользователя + универсальные (is_universal=1)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pf.id, pf.display_name, pf.uploaded_at, pf.is_universal, u.username, "
            "(SELECT active_prompt_id FROM users WHERE id=?) = pf.id AS is_active "
            "FROM prompt_files pf LEFT JOIN users u ON u.id=pf.uploaded_by "
            "WHERE pf.owner_id=? OR pf.is_universal=1 ORDER BY pf.is_universal DESC, pf.id DESC",
            (user_id, user_id)
        ).fetchall()
        return [dict(r) for r in rows]


def activate_prompt(prompt_id, user_id):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active_prompt_id=? WHERE id=?", (prompt_id, user_id))
        conn.commit()


def deactivate_prompt(user_id):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active_prompt_id=NULL WHERE id=?", (user_id,))
        conn.commit()


def delete_prompt(prompt_id, user_id):
    with get_conn() as conn:
        # Удалять можно только свои или универсальные (только admin)
        conn.execute("UPDATE users SET active_prompt_id=NULL WHERE active_prompt_id=?", (prompt_id,))
        conn.execute("DELETE FROM prompt_files WHERE id=? AND (owner_id=? OR is_universal=1)", (prompt_id, user_id))
        conn.commit()


def get_active_prompt_content(user_id=None):
    """Активный промт пользователя, иначе None (будет использован дефолтный)."""
    if user_id is None:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT pf.content FROM prompt_files pf "
            "JOIN users u ON u.active_prompt_id=pf.id "
            "WHERE u.id=?", (user_id,)
        ).fetchone()
        return row["content"] if row else None


def get_prompt_content(prompt_id):
    with get_conn() as conn:
        row = conn.execute("SELECT content FROM prompt_files WHERE id=?", (prompt_id,)).fetchone()
        return row["content"] if row else None


def update_prompt_content(prompt_id, content):
    with get_conn() as conn:
        conn.execute("UPDATE prompt_files SET content=? WHERE id=?", (content, prompt_id))
        conn.commit()


# ─── Теги (каталог) ──────────────────────────────────────────────────────────

def get_tags_catalog():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tags_catalog ORDER BY name"
        ).fetchall()]


def create_tag(name, color, user_id):
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO tags_catalog (name, color, created_by) VALUES (?,?,?)",
                (name.strip(), color, user_id)
            )
            conn.commit()
            return cur.lastrowid
    except Exception:
        return None


def delete_tag(tag_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM tags_catalog WHERE id=?", (tag_id,))
        conn.commit()
