from datetime import datetime, timedelta
import math
from typing import Optional, Tuple, Dict, Any
from backend.database import get_db_connection
from backend.config import Config

class RateLimiter:
    def __init__(self):
        # DB is initialized in database.py
        pass

    def _identity_key(self, ip: str, user_id: Optional[str]) -> str:
        # Use user_id when available so resets follow the user; fall back to IP for guests
        return f"user:{user_id}" if user_id else f"ip:{ip}"
    
    def _cleanup_old_requests(self, ip: str, req_type: str, user_id: Optional[str] = None):
        with get_db_connection() as conn:
            cursor = conn.cursor()

            now = datetime.now()
            month_ago = now - timedelta(days=30)
            month_ago_str = month_ago.strftime("%Y-%m-%d %H:%M:%S")

            if user_id:
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = ? AND timestamp > ?
                ''', (user_id, req_type, month_ago_str))
            else:
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = ? AND timestamp > ? AND user_id IS NULL
                ''', (ip, req_type, month_ago_str))

            recent_count = cursor.fetchone()[0]

            if recent_count == 0:
                if user_id:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE user_id = ? AND req_type = ?
                    ''', (user_id, req_type))
                else:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE ip = ? AND req_type = ? AND user_id IS NULL
                    ''', (ip, req_type))
            else:
                if user_id:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE user_id = ? AND req_type = ? AND timestamp < ?
                    ''', (user_id, req_type, month_ago_str))
                else:
                    cursor.execute('''
                    DELETE FROM requests 
                    WHERE ip = ? AND req_type = ? AND timestamp < ? AND user_id IS NULL
                    ''', (ip, req_type, month_ago_str))

            conn.commit()
    
    def _get_next_reset(self, ip: str, user_id: Optional[str]) -> Optional[datetime]:
        identity = self._identity_key(ip, user_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT reset_date FROM reset_dates WHERE ip = ?', (identity,))
            row = cursor.fetchone()
            if not row:
                return None
            start = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            return start + timedelta(days=30)
    
    def _save_reset_date(self, ip: str, reset_date: datetime, user_id: Optional[str]):
        identity = self._identity_key(ip, user_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT OR REPLACE INTO reset_dates (ip, reset_date) 
            VALUES (?, ?)
            ''', (identity, reset_date.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
    
    def check_rate_limit(self, ip: str, req_type: str, user_id: Optional[str] = None) -> Tuple[bool, int]:
        self._cleanup_old_requests(ip, req_type, user_id)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            
            if user_id:
                search_limit = Config.USER_SEARCH_RATE_LIMIT
                weather_limit = Config.USER_WEATHER_RATE_LIMIT
                
                if req_type in ["search", "weather"]:
                    cursor.execute('''
                    SELECT COUNT(*) FROM requests 
                    WHERE user_id = ? AND req_type = ? AND timestamp > ?
                    ''', (user_id, req_type, month_ago))
                    current_count = cursor.fetchone()[0]
                    
                    limit = search_limit if req_type == "search" else weather_limit
                    return (current_count < limit), limit - current_count

            else:
                search_limit = Config.GUEST_SEARCH_RATE_LIMIT
                weather_limit = Config.GUEST_WEATHER_RATE_LIMIT
                
                if req_type in ["search", "weather"]:
                    cursor.execute('''
                    SELECT COUNT(*) FROM requests 
                    WHERE ip = ? AND req_type = ? AND timestamp > ? AND user_id IS NULL
                    ''', (ip, req_type, month_ago))
                    current_count = cursor.fetchone()[0]

                    limit = search_limit if req_type == "search" else weather_limit
                    return (current_count < limit), limit - current_count
        
        return True, -1
    
    def add_request(self, ip: str, req_type: str, user_id: Optional[str] = None):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute('''
            INSERT INTO requests (ip, req_type, timestamp, user_id)
            VALUES (?, ?, ?, ?)
            ''', (ip, req_type, now_str, user_id))

            # if req_type != "total":
            #    cursor.execute('''
            #    INSERT INTO requests (ip, req_type, timestamp, user_id)
            #    VALUES (?, ?, ?, ?)
            #    ''', (ip, "total", now_str, user_id))

            identity = self._identity_key(ip, user_id)
            cursor.execute('SELECT reset_date FROM reset_dates WHERE ip = ?', (identity,))
            row = cursor.fetchone()
            if not row:
                cursor.execute('''
                INSERT OR REPLACE INTO reset_dates (ip, reset_date) VALUES (?, ?)
                ''', (identity, now_str))
            else:
                start = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if now_dt - start >= timedelta(days=30):
                    cursor.execute('''
                    INSERT OR REPLACE INTO reset_dates (ip, reset_date) VALUES (?, ?)
                    ''', (identity, now_str))

            conn.commit()
    
    def get_limits(self, ip: str, user_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        self._cleanup_old_requests(ip, "search", user_id)
        self._cleanup_old_requests(ip, "weather", user_id)
        self._cleanup_old_requests(ip, "total", user_id)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            
            if user_id:
                search_limit = Config.USER_SEARCH_RATE_LIMIT
                weather_limit = Config.USER_WEATHER_RATE_LIMIT
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'search' AND timestamp > ?
                ''', (user_id, month_ago))
                search_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'weather' AND timestamp > ?
                ''', (user_id, month_ago))
                weather_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE user_id = ? AND req_type = 'total' AND timestamp > ?
                ''', (user_id, month_ago))
                total_count = cursor.fetchone()[0]
            else:
                search_limit = Config.GUEST_SEARCH_RATE_LIMIT
                weather_limit = Config.GUEST_WEATHER_RATE_LIMIT
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'search' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                search_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'weather' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                weather_count = cursor.fetchone()[0]
                
                cursor.execute('''
                SELECT COUNT(*) FROM requests 
                WHERE ip = ? AND req_type = 'total' AND timestamp > ? AND user_id IS NULL
                ''', (ip, month_ago))
                total_count = cursor.fetchone()[0]
        
        next_reset = self._get_next_reset(ip, user_id)
        now_dt = datetime.now()

        if next_reset and now_dt >= next_reset:
            with get_db_connection() as conn2:
                cur2 = conn2.cursor()
                if user_id:
                    cur2.execute('DELETE FROM requests WHERE user_id = ?', (user_id,))
                else:
                    cur2.execute('DELETE FROM requests WHERE ip = ? AND user_id IS NULL', (ip,))
                conn2.commit()
            self._save_reset_date(ip, now_dt, user_id)
            search_count = 0
            weather_count = 0
            total_count = 0
            next_reset = self._get_next_reset(ip, user_id)

        # Initialize a reset window for new identities so UI shows a reset schedule
        if next_reset is None:
            self._save_reset_date(ip, now_dt, user_id)
            next_reset = self._get_next_reset(ip, user_id)

        diff = next_reset - now_dt if next_reset else None
        if not next_reset:
            reset_info = {
                "started": False,
                "timestamp": None,
                "days_remaining": None,
                "date": None
            }
        else:
            total_seconds = diff.total_seconds()
            days_remaining = 30 if total_seconds <= 0 else int(math.ceil(total_seconds / 86400.0))
            reset_info = {
                "started": True,
                "timestamp": int(next_reset.timestamp()),
                "days_remaining": days_remaining,
                "date": next_reset.strftime("%Y-%m-%d")
            }

        return {
            "search": {
                "limit": search_limit,
                "remaining": search_limit - search_count,
                "used": search_count
            },
            "weather": {
                "limit": weather_limit,
                "remaining": weather_limit - weather_count,
                "used": weather_count
            },
            "reset": reset_info
        }
