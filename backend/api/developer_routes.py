from flask import Blueprint, request, session, url_for, render_template, redirect, jsonify
from flask_login import current_user, login_required
from backend.models.user import User
from backend.models.oauth import OAuth2Client
from backend.extensions import auth_server
from backend.database import get_db_connection
import uuid
import secrets
import json

developer_bp = Blueprint('developer', __name__)

@developer_bp.route('/oauth/authorize', methods=['GET', 'POST'])
def authorize():
    if not current_user.is_authenticated:
        return redirect(url_for('views.login_page', next=request.url))

    if request.method == 'GET':
        try:
            grant = auth_server.get_consent_grant(end_user=current_user)
        except Exception as e:
            return jsonify({'error': str(e)}), 400
            
        client = grant.client
        scope = client.get_allowed_scope(grant.request.scope)
        return render_template('authorize.html', client=client, scope=scope, user=current_user, grant=grant)

    if request.form.get('confirm'):
        grant_user = current_user
    else:
        grant_user = None

    return auth_server.create_authorization_response(grant_user=grant_user)

@developer_bp.route('/oauth/token', methods=['POST'])
def issue_token():
    return auth_server.create_token_response()

@developer_bp.route('/api/developer/apps', methods=['GET'])
@login_required
def list_apps():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM api_clients WHERE user_id = ?", (current_user.id,))
        rows = cursor.fetchall()
        
        apps = []
        for row in rows:
            meta = json.loads(row['client_metadata'])
            apps.append({
                'client_id': row['client_id'],
                'client_secret': row['client_secret'], # Show secret for now
                'client_name': meta.get('client_name'),
                'redirect_uris': meta.get('redirect_uris')
            })
    return jsonify(apps)

@developer_bp.route('/api/developer/apps', methods=['POST'])
@login_required
def create_app():
    data = request.json
    client_name = data.get('client_name')
    client_uri = data.get('client_uri')
    redirect_uris_raw = data.get('redirect_uris', '')
    
    if isinstance(redirect_uris_raw, list):
        redirect_uris = redirect_uris_raw
    else:
        redirect_uris = redirect_uris_raw.split('\n')
        
    client_id = str(uuid.uuid4())
    client_secret = secrets.token_urlsafe(24)
    
    client_metadata = {
        'client_name': client_name,
        'client_uri': client_uri,
        'redirect_uris': [uri.strip() for uri in redirect_uris if uri.strip()],
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'scope': 'profile email',
        'token_endpoint_auth_method': 'client_secret_post'
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO api_clients (client_id, client_secret, user_id, client_metadata)
            VALUES (?, ?, ?, ?)
        ''', (client_id, client_secret, current_user.id, json.dumps(client_metadata)))
        conn.commit()
    
    return jsonify({
        'client_id': client_id,
        'client_secret': client_secret,
        'client_metadata': client_metadata
    })
