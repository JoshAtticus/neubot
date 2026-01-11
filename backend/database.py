import sqlite3
import contextlib
from backend.config import Config

@contextlib.contextmanager
def get_db_connection():
    conn = sqlite3.connect(Config.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            provider TEXT NOT NULL,
            profile_pic TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS home_assistant_links (
            user_id TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at INTEGER,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')


        
        # Migration checks
        cursor.execute("PRAGMA table_info(home_assistant_links)")
        ha_cols = [row[1] for row in cursor.fetchall()]
        if 'refresh_token' not in ha_cols:
            try:
                cursor.execute('ALTER TABLE home_assistant_links ADD COLUMN refresh_token TEXT')
            except Exception:
                pass
        if 'expires_at' not in ha_cols:
            try:
                cursor.execute('ALTER TABLE home_assistant_links ADD COLUMN expires_at INTEGER')
            except Exception:
                pass
                
        cursor.execute("DROP TABLE IF EXISTS app_tokens")
        cursor.execute('''
        CREATE TABLE app_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')

        # Settings table (per user). If not logged in, frontend stores locally.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS show_settings (
            user_id TEXT PRIMARY KEY,
            hour_format TEXT DEFAULT '12',
            default_room TEXT,
            bg_follow_room INTEGER DEFAULT 0,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_auth_requests (
            state TEXT PRIMARY KEY,
            callback_url TEXT NOT NULL
        )
        ''')
        
        # Rate Limiter Tables
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            req_type TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            user_id TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reset_dates (
            ip TEXT PRIMARY KEY,
            reset_date DATETIME NOT NULL
        )
        ''')
        
        # Migration for requests table
        cursor.execute("PRAGMA table_info(requests)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'user_id' not in column_names:
            cursor.execute('ALTER TABLE requests ADD COLUMN user_id TEXT')
            
        # Migration for show_settings table
        cursor.execute("PRAGMA table_info(show_settings)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'temp_unit' not in column_names:
            cursor.execute("ALTER TABLE show_settings ADD COLUMN temp_unit TEXT DEFAULT 'c'")
        
        conn.commit()
