"""
database.py — Operational SQLite layer for Smart Energy AI.

DB path is always resolved relative to this file's location,
so the correct database is used regardless of the working
directory from which Python is launched.
"""

from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

# =========================================================
# CANONICAL DATABASE PATH  (Fix #2)
# =========================================================

DB_PATH: Path = Path(__file__).resolve().parent / "energy.db"


@contextmanager
def get_connection(db_path=None):
    """مدير سياق للاتصال بقاعدة البيانات مع إغلاق آمن وتفعيل WAL ومفاتيح أجنبية."""
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 15000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """دالة مساعدة لتحويل sqlite3.Row إلى Dictionary عادي."""
    return dict(row) if row else None


# ==========================================
# 1. دوال المباني (Buildings CRUD)
# ==========================================

def add_building(building_id: str, name: str, description: str = "",
                 db_path=None) -> Dict[str, Any]:
    """إضافة مبنى جديد إلى النظام."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO buildings (building_id, name, description) VALUES (?, ?, ?);",
                (building_id, name, description)
            )
            return {"success": True, "building_id": building_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_buildings(db_path=None) -> List[Dict[str, Any]]:
    """استرجاع قائمة بجميع المباني المسجلة."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT building_id, name, description FROM buildings ORDER BY building_id ASC;")
        return [dict(row) for row in cursor.fetchall()]


def get_historical_years(db_path=None) -> List[str]:
    """Dynamically return distinct years present in the historical energy readings database."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT substr(timestamp, 1, 4) as yr FROM energy_readings ORDER BY yr ASC;")
        return [row["yr"] for row in cursor.fetchall() if row["yr"]]



# ==========================================
# 2. دوال قراءات الطاقة (Energy Readings CRUD)
# ==========================================

def add_energy_reading(
    timestamp: str,
    building_id: str,
    energy_kw: float,
    hvac_kw: float,
    occupancy_pct: float,
    solar_kw: float,
    ev_kw: float,
    temperature_c: float,
    db_path=None
) -> Dict[str, Any]:
    """إضافة قراءة طاقة جديدة متوافقة مع الحقول الأساسية."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO energy_readings (
                    timestamp, building_id, energy_kw, hvac_kw, occupancy_pct, solar_kw, ev_kw, temperature_c
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (timestamp, building_id, energy_kw, hvac_kw, occupancy_pct, solar_kw, ev_kw, temperature_c))
            return {"success": True, "reading_id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_latest_energy_reading(building_id: str, db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع أحدث قراءة طاقة لمبنى محدد."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM energy_readings
            WHERE building_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
        """, (building_id,))
        return _to_dict(cursor.fetchone())


def get_energy_history(building_id: str, limit: int = 100, db_path=None) -> List[Dict[str, Any]]:
    """استرجاع سجل القراءات التاريخية لمبنى محدد مرتبة من الأقدم إلى الأحدث."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM (
                SELECT * FROM energy_readings
                WHERE building_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            ) ORDER BY timestamp ASC;
        """, (building_id, limit))
        return [dict(row) for row in cursor.fetchall()]


# ==========================================
# 3. دوال قراءات الطاقة الشمسية (Solar Readings CRUD)
# ==========================================

def add_solar_reading(
    timestamp: str,
    building_id: str,
    solar_kw: float,
    temperature_c: Optional[float] = None,
    db_path=None
) -> Dict[str, Any]:
    """إضافة قراءة إنتاج طاقة شمسية."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO solar_readings (timestamp, building_id, solar_kw, temperature_c)
                VALUES (?, ?, ?, ?);
            """, (timestamp, building_id, solar_kw, temperature_c))
            return {"success": True, "solar_reading_id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_latest_solar_reading(building_id: Optional[str] = None,
                              db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع آخر قراءة طاقة شمسية لمبنى معين أو للحرم الجامعي."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if building_id:
            cursor.execute(
                "SELECT * FROM solar_readings WHERE building_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1;",
                (building_id,)
            )
        else:
            cursor.execute("SELECT * FROM solar_readings ORDER BY timestamp DESC, id DESC LIMIT 1;")
        row = cursor.fetchone()
        if row:
            return _to_dict(row)

    # Fallback: derive solar_kw from energy_readings if solar_readings is empty
    b_id = building_id if (building_id and building_id != "CAMPUS") else "B001"
    latest = get_latest_energy_reading(b_id, db_path=db_path)
    if latest:
        return {
            "building_id": building_id or "CAMPUS",
            "timestamp": latest["timestamp"],
            "solar_kw": latest["solar_kw"],
            "generation_kw": latest["solar_kw"],
            "expected_kw": 150.0,
            "capacity_kwp": 200.0,
            "temperature_c": latest["temperature_c"]
        }
    return None


# ==========================================
# 4. دوال الحوادث (Incidents CRUD)
# ==========================================

def create_incident(
    building_id: str,
    incident_type: str,
    severity: str,
    created_at: str,
    description: str = "",
    status: str = "open",
    db_path=None
) -> Dict[str, Any]:
    """تسجيل حادثة جديدة."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO incidents (building_id, incident_type, severity, created_at, description, status)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (building_id, incident_type, severity, created_at, description, status))
            return {"success": True, "incident_id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_incident(incident_id: int, db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع تفاصيل حادثة محددة."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incidents WHERE id = ?;", (incident_id,))
        return _to_dict(cursor.fetchone())


def get_incidents(building_id: Optional[str] = None, status: Optional[str] = None,
                  db_path=None) -> List[Dict[str, Any]]:
    """استرجاع الحوادث مع إمكانية التصفية."""
    query = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if building_id:
        query += " AND building_id = ?"
        params.append(building_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC;"
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


# ==========================================
# 5. دوال مساعدة لمنظومة الأدوات
# ==========================================

def get_energy_readings(building_id: str, start_time: Optional[str] = None,
                         end_time: Optional[str] = None, db_path=None) -> List[Dict[str, Any]]:
    """استرجاع قراءات الطاقة لمبنى محدد مع إمكانية تحديد النطاق الزمني."""
    query = "SELECT * FROM energy_readings WHERE building_id = ?"
    params = [building_id]
    if start_time:
        query += " AND timestamp >= ?"
        params.append(start_time)
    if end_time:
        query += " AND timestamp <= ?"
        params.append(end_time)
    query += " ORDER BY timestamp ASC;"
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def get_latest_occupancy(building_id: str, db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع آخر نسبة إشغال لمبنى محدد."""
    latest = get_latest_energy_reading(building_id, db_path=db_path)
    if latest:
        return {
            "building_id": building_id,
            "timestamp": latest["timestamp"],
            "occupancy_pct": latest["occupancy_pct"],
            "estimated_people": int(latest["occupancy_pct"] * 2)
        }
    return None


def get_energy_reading_at(building_id: str, at_time: str, db_path=None) -> Optional[Dict[str, Any]]:
    """Latest energy reading for a building at or before a given timestamp."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM energy_readings
            WHERE building_id = ? AND timestamp <= ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
        """, (building_id, at_time))
        return _to_dict(cursor.fetchone())


def get_solar_reading_at(building_id: str, at_time: str, db_path=None) -> Optional[Dict[str, Any]]:
    """Latest solar reading for a building at or before a given timestamp."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM solar_readings
            WHERE building_id = ? AND timestamp <= ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
        """, (building_id, at_time))
        row = cursor.fetchone()
        if row:
            return _to_dict(row)
    reading = get_energy_reading_at(building_id, at_time, db_path=db_path)
    if reading:
        return {
            "building_id": building_id,
            "timestamp": reading["timestamp"],
            "solar_kw": reading["solar_kw"],
            "generation_kw": reading["solar_kw"],
            "temperature_c": reading["temperature_c"],
        }
    return None


def get_occupancy_at(building_id: str, at_time: str, db_path=None) -> Optional[Dict[str, Any]]:
    """Occupancy for a building at or before a given timestamp."""
    reading = get_energy_reading_at(building_id, at_time, db_path=db_path)
    if reading:
        return {
            "building_id": building_id,
            "timestamp": reading["timestamp"],
            "occupancy_pct": reading["occupancy_pct"],
            "estimated_people": int(reading["occupancy_pct"] * 2)
        }
    return None


def get_latest_grid_status(db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع حالة الشبكة الأخيرة."""
    return {
        "timestamp": "2017-12-31 23:00:00",
        "event_type": "NORMAL",
        "severity": "LOW",
        "grid_load_pct": 65.0,
        "price_signal": 0.12,
        "description": "Grid operating under normal conditions."
    }


# ==========================================
# 6. جداول ونظام المصادقة والمستخدمين (Auth System)
# ==========================================

def init_auth_tables(db_path=None) -> None:
    """
    تهيئة جداول المصادقة (users, verification_codes) تلقائياً عند بدء التشغيل
    مع تفعيل نمط WAL بشكل دائم وفحص الأعمدة (Migrations) بأمان
    وإنشاء حساب المسؤول الافتراضي.
    """
    if db_path is None:
        db_path = DB_PATH

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")

        # 1. جدول المستخدمين users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_verified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login TEXT,
                can_manage_users INTEGER DEFAULT 0,
                can_control_hvac INTEGER DEFAULT 0,
                can_approve_actions INTEGER DEFAULT 0,
                can_view_analytics INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1
            );
        """)

        # فحص الأعمدة (Migrations) بأمان
        cursor.execute("PRAGMA table_info(users);")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        required_cols = {
            "can_manage_users": "INTEGER DEFAULT 0",
            "can_control_hvac": "INTEGER DEFAULT 0",
            "can_approve_actions": "INTEGER DEFAULT 0",
            "can_view_analytics": "INTEGER DEFAULT 1",
            "is_active": "INTEGER DEFAULT 1",
            "is_verified": "INTEGER DEFAULT 0",
            "last_login": "TEXT"
        }
        for col_name, col_def in required_cols.items():
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def};")

        # 2. جدول رموز التحقق verification_codes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                code_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_used INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vc_email ON verification_codes(email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vc_user_id ON verification_codes(user_id);")

        # 3. حساب الأدمن الافتراضي
        cursor.execute("SELECT id FROM users WHERE username = 'admin' OR email = 'admin@smartenergy.ai';")
        admin_row = cursor.fetchone()
        if not admin_row:
            from werkzeug.security import generate_password_hash
            import datetime as _dt
            now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            admin_pwd_hash = generate_password_hash("admin123")
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, role, is_verified,
                    created_at, can_manage_users, can_control_hvac,
                    can_approve_actions, can_view_analytics, is_active
                ) VALUES (?, ?, ?, ?, 1, ?, 1, 1, 1, 1, 1);
            """, ("admin", "admin@smartenergy.ai", admin_pwd_hash, "admin", now_str))

        # 4. حساب الفحص والتجربة المباشر (Direct Test/Demo Account — No 2FA / Instant Login)
        cursor.execute("SELECT id FROM users WHERE username = 'tester';")
        tester_row = cursor.fetchone()
        if not tester_row:
            from werkzeug.security import generate_password_hash
            import datetime as _dt
            now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tester_pwd_hash = generate_password_hash("tester123")
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, role, is_verified,
                    created_at, can_manage_users, can_control_hvac,
                    can_approve_actions, can_view_analytics, is_active
                ) VALUES (?, ?, ?, ?, 1, ?, 1, 1, 1, 1, 1);
            """, ("tester", "tester@smart-energy.ai", tester_pwd_hash, "admin", now_str))

        # 5. حساب المالك الرئيسي / المسؤول الأول (Osama Alassaf)
        cursor.execute("""
            SELECT id FROM users 
            WHERE lower(email) IN ('osamaalassaf10@gmail.com', 'osama.alassaf10@gmail.com')
               OR lower(username) = 'osama alassaf';
        """)
        osama_row = cursor.fetchone()
        if not osama_row:
            from werkzeug.security import generate_password_hash
            import datetime as _dt
            now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            osama_pwd_hash = generate_password_hash("123456")
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, role, is_verified,
                    created_at, can_manage_users, can_control_hvac,
                    can_approve_actions, can_view_analytics, is_active
                ) VALUES (?, ?, ?, ?, 1, ?, 1, 1, 1, 1, 1);
            """, ("OSAMA ALASSAF", "osama.alassaf10@gmail.com", osama_pwd_hash, "admin", now_str))
        else:
            # التأكد من تفعيل الحساب والصلاحيات كاملة
            cursor.execute("""
                UPDATE users
                SET role = 'admin', is_verified = 1, is_active = 1,
                    can_manage_users = 1, can_control_hvac = 1,
                    can_approve_actions = 1, can_view_analytics = 1
                WHERE id = ?;
            """, (osama_row["id"],))


def create_user(
    username: str,
    email: str,
    password_hash: str,
    role: str = "user",
    is_verified: int = 0,
    can_manage_users: int = 0,
    can_control_hvac: int = 0,
    can_approve_actions: int = 0,
    can_view_analytics: int = 1,
    is_active: int = 1,
    db_path=None
) -> Dict[str, Any]:
    """إنشاء مستخدم جديد في النظام مع صلاحيات محددة."""
    import datetime as _dt
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ضبط الصلاحيات التلقائية بحسب الرتبة إذا لم يتم تخصيصها
    if role == "admin":
        can_manage_users = 1
        can_control_hvac = 1
        can_approve_actions = 1
        can_view_analytics = 1
    elif role == "manager":
        can_control_hvac = 1
        can_approve_actions = 1
        can_view_analytics = 1
    elif role == "analyst":
        can_view_analytics = 1

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, role, is_verified,
                    created_at, can_manage_users, can_control_hvac,
                    can_approve_actions, can_view_analytics, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                username.strip(),
                email.strip().lower(),
                password_hash,
                role,
                is_verified,
                now_str,
                can_manage_users,
                can_control_hvac,
                can_approve_actions,
                can_view_analytics,
                is_active
            ))
            return {"success": True, "user_id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def normalize_email_for_comparison(email_str: str) -> str:
    """Normalize email address, ignoring dots for gmail.com addresses."""
    s = (email_str or "").strip().lower()
    if "@gmail.com" in s:
        local, domain = s.split("@", 1)
        local = local.replace(".", "")
        if "+" in local:
            local = local.split("+")[0]
        return f"{local}@{domain}"
    return s


def get_user_by_login(login_term: str, db_path=None) -> Optional[Dict[str, Any]]:
    """البحث عن المستخدم عبر اسم المستخدم أو البريد الإلكتروني مع دعم ذكي لمرونة Gmail Dots."""
    term = (login_term or "").strip()
    if not term:
        return None

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # 1. تطابق مباشر (اسم المستخدم أو البريد)
        cursor.execute("""
            SELECT * FROM users
            WHERE lower(username) = lower(?) OR lower(email) = lower(?)
            LIMIT 1;
        """, (term, term))
        row = cursor.fetchone()
        if row:
            return _to_dict(row)

        # 2. تطابق ذكي مع بريد Gmail (تجاوز النقاط في اسم البريد)
        if "@gmail.com" in term.lower():
            target_norm = normalize_email_for_comparison(term)
            cursor.execute("SELECT * FROM users WHERE lower(email) LIKE '%@gmail.com';")
            for u in cursor.fetchall():
                if normalize_email_for_comparison(u["email"]) == target_norm:
                    return _to_dict(u)

        return None


def get_user_by_id(user_id: int, db_path=None) -> Optional[Dict[str, Any]]:
    """استرجاع بيانات المستخدم عبر معرّفه الرقمي."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ? LIMIT 1;", (user_id,))
        return _to_dict(cursor.fetchone())


def get_all_users(db_path=None) -> List[Dict[str, Any]]:
    """استرجاع قائمة بكافة المستخدمين في النظام."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY id ASC;")
        return [dict(row) for row in cursor.fetchall()]


def update_user_role(user_id: int, new_role: str, sync_permissions: bool = True, db_path=None) -> Dict[str, Any]:
    """ترقية أو تغيير دور المستخدم مع مزامنة الصلاحيات المناسبة."""
    valid_roles = {"admin", "manager", "analyst", "user"}
    if new_role not in valid_roles:
        return {"success": False, "error": f"Invalid role: {new_role}"}

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            if sync_permissions:
                can_manage = 1 if new_role == "admin" else 0
                can_hvac = 1 if new_role in ("admin", "manager") else 0
                can_approve = 1 if new_role in ("admin", "manager") else 0
                can_analytics = 1
                cursor.execute("""
                    UPDATE users
                    SET role = ?,
                        can_manage_users = ?,
                        can_control_hvac = ?,
                        can_approve_actions = ?,
                        can_view_analytics = ?
                    WHERE id = ?;
                """, (new_role, can_manage, can_hvac, can_approve, can_analytics, user_id))
            else:
                cursor.execute("UPDATE users SET role = ? WHERE id = ?;", (new_role, user_id))
            return {"success": True, "user_id": user_id, "role": new_role}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_user_permissions(user_id: int, permissions: Dict[str, Any], db_path=None) -> Dict[str, Any]:
    """تعديل الصلاحيات المخصصة للمستخدم."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET can_manage_users = ?,
                    can_control_hvac = ?,
                    can_approve_actions = ?,
                    can_view_analytics = ?,
                    is_active = coalesce(?, is_active)
                WHERE id = ?;
            """, (
                int(permissions.get("can_manage_users", 0)),
                int(permissions.get("can_control_hvac", 0)),
                int(permissions.get("can_approve_actions", 0)),
                int(permissions.get("can_view_analytics", 1)),
                permissions.get("is_active"),
                user_id
            ))
            return {"success": True, "user_id": user_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def toggle_user_active(user_id: int, db_path=None) -> Dict[str, Any]:
    """تجميد الحساب أو إعادة تنشيطه."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_active FROM users WHERE id = ?;", (user_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "User not found"}
            new_status = 0 if row["is_active"] else 1
            cursor.execute("UPDATE users SET is_active = ? WHERE id = ?;", (new_status, user_id))
            return {"success": True, "user_id": user_id, "is_active": new_status}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_user(user_id: int, db_path=None) -> Dict[str, Any]:
    """حذف المستخدم بأمان مع حذف كافة رموز التحقق التابعة له CASCADE."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM verification_codes WHERE user_id = ?;", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            return {"success": True, "user_id": user_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_user_password(user_id: int, new_password_hash: str, db_path=None) -> Dict[str, Any]:
    """تحديث كلمة مرور المستخدم."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?;", (new_password_hash, user_id))
            return {"success": True, "user_id": user_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_user_details(user_id: int, username: str, email: str, is_verified: int = 1, db_path=None) -> Dict[str, Any]:
    """تعديل وتحديث بيانات المستخدم الأساسية من لوحة الإدارة."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET username = ?, email = ?, is_verified = ?
                WHERE id = ?;
            """, (username.strip(), email.strip().lower(), int(is_verified), user_id))
            return {"success": True, "user_id": user_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_user_last_login(user_id: int, db_path=None) -> Dict[str, Any]:
    """تحديث وقت آخر تسجيل دخول."""
    import datetime as _dt
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_login = ? WHERE id = ?;", (now_str, user_id))
            return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_user_verified(user_id: int, db_path=None) -> Dict[str, Any]:
    """تأكيد الحساب بعد التحقق من الرمز."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_verified = 1 WHERE id = ?;", (user_id,))
            return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def save_verification_code(
    user_id: Optional[int],
    email: str,
    code: str,
    code_type: str,
    expires_in_minutes: int = 10,
    db_path=None
) -> Dict[str, Any]:
    """حفظ رمز تحقق جديد وإلغاء صلاحية أي رموز غير مستخدمة سابقة لنفس البريد والنوع."""
    import datetime as _dt
    now = _dt.datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (now + _dt.timedelta(minutes=expires_in_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            # إلغاء الرموز القديمة غير المستهلكة
            cursor.execute("""
                UPDATE verification_codes
                SET is_used = 2
                WHERE email = ? AND code_type = ? AND is_used = 0;
            """, (email.strip().lower(), code_type))

            cursor.execute("""
                INSERT INTO verification_codes (
                    user_id, email, code, code_type, created_at, expires_at, is_used
                ) VALUES (?, ?, ?, ?, ?, ?, 0);
            """, (user_id, email.strip().lower(), code.strip(), code_type, created_at, expires_at))
            return {"success": True, "code_id": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def verify_and_consume_code(
    email: str,
    code: str,
    code_type: str,
    db_path=None
) -> Dict[str, Any]:
    """التحقق من صحة وصلاحية رمز التحقق واستهلاكه لمنع إعادة الاستخدام."""
    import datetime as _dt
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM verification_codes
                WHERE email = ? AND code = ? AND code_type = ? AND is_used = 0
                ORDER BY id DESC
                LIMIT 1;
            """, (email.strip().lower(), code.strip(), code_type))
            row = cursor.fetchone()

            # محاولة تطابق مرنة مع بريد Gmail لتفادي مشاكل النقاط (.)
            if not row and "@gmail.com" in email.strip().lower():
                target_norm = normalize_email_for_comparison(email)
                cursor.execute("""
                    SELECT * FROM verification_codes
                    WHERE code = ? AND code_type = ? AND is_used = 0 AND lower(email) LIKE '%@gmail.com'
                    ORDER BY id DESC;
                """, (code.strip(), code_type))
                for candidate in cursor.fetchall():
                    if normalize_email_for_comparison(candidate["email"]) == target_norm:
                        row = candidate
                        break

            if not row:
                return {"success": False, "valid": False, "error": "Invalid verification code"}

            if row["expires_at"] < now_str:
                cursor.execute("UPDATE verification_codes SET is_used = 2 WHERE id = ?;", (row["id"],))
                return {"success": False, "valid": False, "error": "Verification code has expired"}

            # استهلاك الرمز
            cursor.execute("UPDATE verification_codes SET is_used = 1 WHERE id = ?;", (row["id"],))
            return {
                "success": True,
                "valid": True,
                "user_id": row["user_id"],
                "email": row["email"],
                "code_type": row["code_type"]
            }
    except Exception as e:
        return {"success": False, "valid": False, "error": str(e)}


def get_all_verification_codes(limit: int = 50, db_path=None) -> List[Dict[str, Any]]:
    """استرجاع آخر 50 رمز تحقق مع حالة كل رمز واسم المستخدم."""
    import datetime as _dt
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT vc.*, u.username
            FROM verification_codes vc
            LEFT JOIN users u ON vc.user_id = u.id
            ORDER BY vc.id DESC
            LIMIT ?;
        """, (limit,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d["is_used"] == 1:
                d["status_text"] = "consumed"
            elif d["is_used"] == 2:
                d["status_text"] = "cancelled"
            elif d["expires_at"] < now_str:
                d["status_text"] = "expired"
            else:
                d["status_text"] = "valid"
            result.append(d)
        return result

