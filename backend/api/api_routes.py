from flask import Blueprint, request, jsonify, session, url_for, redirect
from flask_login import current_user, login_required
from backend.core.semantic_parser import SemanticParser
from backend.core.rate_limiter import RateLimiter
from backend.utils import get_client_ip, get_request_user_id
from backend.database import get_db_connection
from backend.models.user import User
from backend.config import Config
from backend.security import encrypt_token, decrypt_token
import secrets
import requests
import time
from datetime import datetime

api_bp = Blueprint('api', __name__, url_prefix='/api')
parser = SemanticParser()
rate_limiter = RateLimiter()

@api_bp.route('/query', methods=['POST'])
def query():
    data = request.json
    query_text = data.get('query', '')
    user_timezone = data.get('timezone', Config.DEFAULT_TIMEZONE)
    
    response, widgets, thoughts, highlighted_query = parser.process(query_text, user_timezone)
    
    # Serialize thoughts
    thoughts_serializable = []
    for t in thoughts:
        thoughts_serializable.append({
            "description": t['description'],
            "result": str(t['result']) if t['result'] is not None else None
        })
        
    return jsonify({
        "response": response,
        "widgets": widgets,
        "thoughts": thoughts_serializable,
        "highlightedQuery": highlighted_query
    })

@api_bp.route('/limits', methods=['GET'])
def get_rate_limits():
    ip = get_client_ip()
    user_id = get_request_user_id()
    limits = rate_limiter.get_limits(ip, user_id)
    return jsonify(limits)

@api_bp.route('/user', methods=['GET'])
def get_user_info():
    temp_unit = None
    user_id = None
    
    if current_user.is_authenticated:
        user_id = current_user.id
    else:
        user_id = get_request_user_id()
    
    if user_id:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT temp_unit FROM show_settings WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            if row and row['temp_unit']:
                temp_unit = row['temp_unit']

    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": current_user.id,
                "name": current_user.name,
                "email": current_user.email,
                "provider": current_user.provider,
                "profile_pic": current_user.profile_pic,
                "temp_unit": temp_unit
            }
        })
    else:
        if user_id:
            user = User.get(user_id)
            if user:
                return jsonify({
                    "authenticated": True,
                    "user": {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "provider": user.provider,
                        "profile_pic": user.profile_pic,
                        "temp_unit": temp_unit
                    }
                })
        return jsonify({
            "authenticated": False,
             "user": {
                "temp_unit": temp_unit
            }
        })

@api_bp.route('/show-settings', methods=['GET','POST'])
def show_settings_api():
    user_id = get_request_user_id()
    if request.method == 'GET':
        if not user_id:
            return jsonify({"hour_format":"12","default_room":"","bg_follow_room":False, "temp_unit":None})
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT hour_format, default_room, bg_follow_room, temp_unit FROM show_settings WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"hour_format":"12","default_room":"","bg_follow_room":False, "temp_unit":None})
            return jsonify({
                "hour_format": row['hour_format'] or '12',
                "default_room": row['default_room'] or '',
                "bg_follow_room": bool(row['bg_follow_room']),
                "temp_unit": row['temp_unit']
            })
    else:
        if not user_id:
            return jsonify({"error":"not_authenticated"}), 200
        data = request.json or {}
        
        # Fetch existing settings to merge partial updates
        existing = {}
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT hour_format, default_room, bg_follow_room, temp_unit FROM show_settings WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            if row:
                existing = dict(row)

        hour = str(data.get('hour_format') or existing.get('hour_format') or '12')
        room = (data.get('default_room') if 'default_room' in data else existing.get('default_room') or '').strip()
        
        # bg_follow_room: check key presence because False/0 is valid
        if 'bg_follow_room' in data:
            bg = 1 if data['bg_follow_room'] else 0
        else:
            bg = existing.get('bg_follow_room', 0)

        # temp_unit
        if 'temp_unit' in data:
            temp = str(data['temp_unit'] or 'c').lower()
        else:
            temp = existing.get('temp_unit', 'c')
            
        if temp not in ['c', 'f']: temp = 'c'
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
            INSERT INTO show_settings (user_id, hour_format, default_room, bg_follow_room, updated_at, temp_unit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET hour_format=excluded.hour_format, default_room=excluded.default_room, bg_follow_room=excluded.bg_follow_room, updated_at=excluded.updated_at, temp_unit=excluded.temp_unit
            ''', (user_id, hour, room, bg, now_str, temp))
            conn.commit()
        return jsonify({"ok":True})

@api_bp.route('/integrations/home-assistant/start', methods=['POST'])
@login_required
def ha_start():
    data = request.json or {}
    base_url = data.get('base_url', '').strip().rstrip('/')
    if not base_url:
        return jsonify({"success": False, "message": "base_url required"}), 400
    if not base_url.startswith(('http://', 'https://')):
        return jsonify({"success": False, "message": "base_url must start with http:// or https://"}), 400
    state = secrets.token_hex(16)
    session['ha_state'] = state
    session['ha_base_url'] = base_url
    callback_url = url_for('api.ha_callback', _external=True)
    client_id = callback_url 
    authorize_url = (
        f"{base_url}/auth/authorize?response_type=code&client_id="
        f"{requests.utils.quote(client_id, safe='')}"
        f"&redirect_uri={requests.utils.quote(callback_url, safe='')}"
        f"&state={state}"
    )
    return jsonify({"success": True, "authorize_url": authorize_url})

@api_bp.route('/integrations/home-assistant/callback')
@login_required
def ha_callback():
    state = request.args.get('state')
    code = request.args.get('code')
    error = request.args.get('error')
    expected = session.get('ha_state')
    base_url = session.get('ha_base_url')
    if error:
        return redirect(url_for('views.integrations_page') + f"?ha_error={requests.utils.quote(error)}")
    if not state or state != expected or not base_url:
        return "Invalid state", 400
    if not code:
        return "Missing code", 400
    token_url = f"{base_url}/auth/token"
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': url_for('api.ha_callback', _external=True)
    }
    try:
        r = requests.post(token_url, data=payload, timeout=15)
    except Exception as e:
        return f"Token request failed: {e}", 502
    if r.status_code != 200:
        return f"Token exchange failed ({r.status_code}): {r.text[:200]}", 502
    data = r.json()
    access_token = data.get('access_token')
    refresh_token = data.get('refresh_token')
    expires_in = data.get('expires_in', 1800)
    if not access_token:
        return "No access token", 502
    expires_at = int(time.time()) + int(expires_in)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO home_assistant_links (user_id, base_url, access_token, refresh_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM home_assistant_links WHERE user_id = ?), ?))''',
                  (current_user.id, base_url, encrypt_token(access_token), encrypt_token(refresh_token) if refresh_token else None, expires_at, current_user.id, datetime.now()))
        conn.commit()
    session.pop('ha_state', None)
    session.pop('ha_base_url', None)
    return redirect(url_for('views.integrations_page') + "?ha_link=1")

@api_bp.route('/integrations/home-assistant/status', methods=['GET'])
@login_required
def ha_status():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT base_url, expires_at FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"connected": False})
        return jsonify({"connected": True, "base_url": row['base_url'], "expires_at": row['expires_at']})

@api_bp.route('/integrations/home-assistant/link', methods=['DELETE'])
@login_required
def ha_unlink():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        conn.commit()
    return jsonify({"success": True, "message": "Home Assistant disconnected"})

@api_bp.route('/integrations/home-assistant/control', methods=['POST'])
@login_required
def ha_control():
    data = request.json or {}
    entity_id = data.get('entity_id')
    action = data.get('action')
    color = data.get('color') # hex string like '#ff0000'
    brightness = data.get('brightness')
    
    if not entity_id or not action:
        return jsonify({"success": False, "error": "Missing entity_id or action"}), 400
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT base_url, access_token, refresh_token, expires_at FROM home_assistant_links WHERE user_id = ?', (current_user.id,))
        row = cursor.fetchone()
        
    if not row:
        return jsonify({"success": False, "error": "Home Assistant not connected"}), 401
        
    base_url = row['base_url']
    access_token = decrypt_token(row['access_token'])
    
    current_time = int(time.time())
    if row['expires_at'] and current_time >= row['expires_at'] - 60 and row['refresh_token']:
        try:
            refresh_token = decrypt_token(row['refresh_token'])
            refresh_url = f"{base_url}/auth/token"
            payload = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': url_for('api.ha_callback', _external=True)
            }
            ref_res = requests.post(refresh_url, data=payload, timeout=10)
            if ref_res.status_code == 200:
                ref_data = ref_res.json()
                access_token = ref_data.get('access_token')
                new_refresh_token = ref_data.get('refresh_token', refresh_token)
                expires_in = ref_data.get('expires_in', 1800)
                expires_at = int(time.time()) + int(expires_in)
                with get_db_connection() as conn_update:
                    c_up = conn_update.cursor()
                    c_up.execute('UPDATE home_assistant_links SET access_token = ?, refresh_token = ?, expires_at = ? WHERE user_id = ?',
                                 (encrypt_token(access_token), encrypt_token(new_refresh_token), expires_at, current_user.id))
                    conn_update.commit()
        except Exception:
            pass

    domain = entity_id.split('.')[0]
    svc_data = {'entity_id': entity_id}
    
    if domain == 'light' and action == 'turn_on':
        if brightness is not None:
            svc_data['brightness_pct'] = brightness
        if color:
            if isinstance(color, str) and color.startswith('#'):
                hex_color = color.lstrip('#')
                rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                svc_data['rgb_color'] = rgb
            elif isinstance(color, (list, tuple)):
                svc_data['rgb_color'] = color
            else:
                svc_data['color_name'] = color
                
    try:
        url = f"{base_url}/api/services/{domain}/{action}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        res = requests.post(url, headers=headers, json=svc_data, timeout=10)
        if res.status_code in (200, 201):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": f"HA service returned {res.status_code}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
