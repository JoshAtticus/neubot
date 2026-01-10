from flask import request
from flask_login import current_user
from typing import Optional
from backend.database import get_db_connection

def get_client_ip():
    if request.headers.get('CF-Connecting-IP'):
        ip = request.headers.get('CF-Connecting-IP').split(',')[0].strip()
    else:
        ip = request.remote_addr
    return ip

def get_user_id_from_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    
    parts = auth_header.split()
    
    if parts[0].lower() != 'bearer' or len(parts) != 2:
        return None
        
    token = parts[1]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM app_tokens WHERE token = ?", (token,))
        result = cursor.fetchone()
        if result:
            return result['user_id']
    return None

def get_request_user_id():
    user_id = current_user.get_id() if current_user.is_authenticated else None
    if not user_id:
        auth_header = request.headers.get('Authorization')
        user_id = get_user_id_from_token(auth_header)
    return user_id
