from flask import Blueprint, redirect, url_for, session, request, render_template
from flask_login import login_user, logout_user, current_user
from backend.extensions import oauth
from backend.database import get_db_connection
from backend.models.user import User
from backend.security import generate_api_token
import secrets
from urllib.parse import urlparse
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect('/')

@auth_bp.route('/login/google')
def login_google():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    redirect_uri = url_for('auth.auth_google', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, state=state)

@auth_bp.route('/auth/google')
def auth_google():
    expected_state = session.pop('oauth_state', None)
    callback_state = request.args.get('state')
    
    if not expected_state or callback_state != expected_state:
        return "Invalid authentication state. Please try again.", 403
        
    token = oauth.google.authorize_access_token()
    
    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    
    user_id = f"google_{user_info['sub']}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name'), user_info.get('email'), 'google', user_info.get('picture'))
            )
            conn.commit()
    
    user = User(
        id=user_id,
        name=user_info.get('name'),
        email=user_info.get('email'),
        provider='google',
        profile_pic=user_info.get('picture')
    )
    login_user(user)
    
    return redirect('/')

@auth_bp.route('/login/github')
def login_github():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    redirect_uri = url_for('auth.auth_github', _external=True)
    return oauth.github.authorize_redirect(redirect_uri, state=state)

@auth_bp.route('/auth/github')
def auth_github():
    expected_state = session.pop('oauth_state', None)
    callback_state = request.args.get('state')
    
    if not expected_state or callback_state != expected_state:
        return "Invalid authentication state. Please try again.", 403
        
    token = oauth.github.authorize_access_token()
    resp = oauth.github.get('https://api.github.com/user', token=token)
    user_info = resp.json()
    
    email_resp = oauth.github.get('https://api.github.com/user/emails', token=token)
    emails = email_resp.json()
    primary_email = next((email['email'] for email in emails if email['primary']), 
                          emails[0]['email'] if emails else 'no-email@example.com')
    
    user_id = f"github_{user_info['id']}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name', user_info.get('login')), primary_email, 'github', user_info.get('avatar_url'))
            )
            conn.commit()
    
    user = User(
        id=user_id,
        name=user_info.get('name', user_info.get('login')),
        email=primary_email,
        provider='github',
        profile_pic=user_info.get('avatar_url')
    )
    login_user(user)
    
    return redirect('/')

# App Login Routes
@auth_bp.route('/login/app/')
def login_app():
    callback_url = request.args.get('callbackURL')
    if not callback_url:
        return "Missing callbackURL parameter", 400
    
    try:
        parsed_url = urlparse(callback_url)
        app_name = parsed_url.netloc or "the application"
    except:
        app_name = "an external application"

    state = secrets.token_urlsafe(16)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO app_auth_requests (state, callback_url) VALUES (?, ?)", (state, callback_url))
        conn.commit()

    session['app_oauth_state'] = state
    return render_template('app-login.html', app_name=app_name, user=current_user)

@auth_bp.route('/login/app/google')
def login_app_google():
    state = session.get('app_oauth_state')
    if not state:
        return "Invalid state, please start the login process again.", 400

    redirect_uri = url_for('auth.auth_app_google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, state=state)

@auth_bp.route('/login/app/github')
def login_app_github():
    state = session.get('app_oauth_state')
    if not state:
        return "Invalid state, please start the login process again.", 400

    redirect_uri = url_for('auth.auth_app_github_callback', _external=True)
    return oauth.github.authorize_redirect(redirect_uri, state=state)

@auth_bp.route('/auth/app/google/callback')
def auth_app_google_callback():
    state = session.pop('app_oauth_state', None)
    callback_state = request.args.get('state')

    if not state or state != callback_state:
        return "Invalid authentication state. Please try again.", 403

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT callback_url FROM app_auth_requests WHERE state = ?", (state,))
        auth_request = cursor.fetchone()
        if not auth_request:
            return "Invalid authentication request.", 403
        callback_url = auth_request['callback_url']
        cursor.execute("DELETE FROM app_auth_requests WHERE state = ?", (state,))
        conn.commit()

    token = oauth.google.authorize_access_token()
    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
    user_info = resp.json()
    user_id = f"google_{user_info['sub']}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name'), user_info.get('email'), 'google', user_info.get('picture'))
            )
            conn.commit()

    app_token = generate_api_token(user_id)
    return redirect(callback_url.replace('[TOKEN]', app_token))

@auth_bp.route('/auth/app/github/callback')
def auth_app_github_callback():
    state = session.pop('app_oauth_state', None)
    callback_state = request.args.get('state')

    if not state or state != callback_state:
        return "Invalid authentication state. Please try again.", 403

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT callback_url FROM app_auth_requests WHERE state = ?", (state,))
        auth_request = cursor.fetchone()
        if not auth_request:
            return "Invalid authentication request.", 403
        callback_url = auth_request['callback_url']
        cursor.execute("DELETE FROM app_auth_requests WHERE state = ?", (state,))
        conn.commit()

    token = oauth.github.authorize_access_token()
    resp = oauth.github.get('https://api.github.com/user', token=token)
    user_info = resp.json()
    
    email_resp = oauth.github.get('https://api.github.com/user/emails', token=token)
    emails = email_resp.json()
    primary_email = next((email['email'] for email in emails if email['primary']),
                         emails[0]['email'] if emails else 'no-email@example.com')
    
    user_id = f"github_{user_info['id']}"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (id, name, email, provider, profile_pic) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_info.get('name', user_info.get('login')), primary_email, 'github', user_info.get('avatar_url'))
            )
            conn.commit()

    app_token = generate_api_token(user_id)
    return redirect(callback_url.replace('[TOKEN]', app_token))

