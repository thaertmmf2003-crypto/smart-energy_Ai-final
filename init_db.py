import sqlite3
import os

DB_NAME = "energy.db"

def get_connection(db_path=DB_NAME):
    """إنشاء اتصال مع تفعيل قيود المفاتيح الأجنبية."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(db_path=DB_NAME):
    """إنشاء جميع الجداول الأساسية والفهارس المطلوبة لليوم الأول."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. جدول المباني (buildings)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buildings (
        building_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT
    );
    """)

    # 2. جدول قراءات الطاقة والأحمال (energy_readings)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS energy_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        building_id TEXT NOT NULL,
        energy_kw REAL NOT NULL,
        hvac_kw REAL NOT NULL,
        occupancy_pct REAL NOT NULL,
        solar_kw REAL NOT NULL,
        ev_kw REAL NOT NULL,
        temperature_c REAL NOT NULL,
        FOREIGN KEY (building_id) REFERENCES buildings (building_id)
    );
    """)

    # 3. جدول قراءات الطاقة الشمسية الإضافي/المفصل (solar_readings)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS solar_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        building_id TEXT NOT NULL,
        solar_kw REAL NOT NULL,
        temperature_c REAL,
        FOREIGN KEY (building_id) REFERENCES buildings (building_id)
    );
    """)

    # 4. جدول الحوادث ومشاكل استهلاك الطاقة (incidents)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id TEXT NOT NULL,
        incident_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        description TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (building_id) REFERENCES buildings (building_id)
    );
    """)

    # 5. جدول الأدلة المرتبطة بالحوادث (evidence)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id INTEGER NOT NULL,
        evidence_type TEXT NOT NULL,
        data_payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents (id)
    );
    """)

    # 6. جدول سجلات تشغيل الوكيل الذكي (agent_runs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        summary TEXT
    );
    """)

    # 7. جدول استدعاء الأدوات المنفذة بواسطة الوكيل (tool_calls)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tool_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        input_args TEXT,
        output_result TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
    );
    """)

    # إنشاء الفهارس (Indexes) على building_id و timestamp لتسريع الاستعلامات
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_energy_b_time ON energy_readings (building_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_solar_b_time ON solar_readings (building_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_b_status ON incidents (building_id, status);")

    # إضافة المباني الافتراضية المتفق عليها في العقد المشترك
    initial_buildings = [
        ("B001", "Administration", "Administration Building"),
        ("B002", "Labs", "Laboratories Building"),
        ("B003", "Classrooms", "Classrooms Building")
    ]
    cursor.executemany("""
    INSERT OR IGNORE INTO buildings (building_id, name, description)
    VALUES (?, ?, ?);
    """, initial_buildings)

    conn.commit()
    conn.close()
    print("Database initialized successfully with default buildings!")

if __name__ == "__main__":
    init_db()