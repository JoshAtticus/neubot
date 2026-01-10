from authlib.oauth2.rfc6749 import grants
from authlib.integrations.flask_oauth2 import current_token
from authlib.oauth2.rfc6750 import BearerTokenValidator
from backend.models.oauth import OAuth2Client, OAuth2Token, OAuth2AuthorizationCode
from backend.models.user import User
from backend.database import get_db_connection
from backend.extensions import auth_server, require_oauth
import json
import time

def query_client(client_id):
    return OAuth2Client.get(client_id)

def save_token(token, request):
    if request.user:
        user_id = request.user.id
    else:
        user_id = request.client.user_id  # client_credentials grant

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Revoke old tokens if needed, but for now just insert new one
        cursor.execute('''
            INSERT INTO oauth2_tokens 
            (client_id, user_id, access_token, refresh_token, scope, issued_at, expires_in)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            request.client.client_id,
            user_id,
            token['access_token'],
            token.get('refresh_token'),
            token.get('scope'),
            token['issued_at'],
            token['expires_in']
        ))
        conn.commit()

class AuthorizationCodeGrant(grants.AuthorizationCodeGrant):
    def save_authorization_code(self, code, request):
        client_code_challenge_method = request.data.get('code_challenge_method')
        client_code_challenge = request.data.get('code_challenge')
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO oauth2_codes 
                (code, client_id, user_id, redirect_uri, response_type, scope, nonce, auth_time, 
                 code_challenge, code_challenge_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code, request.client.client_id, request.user.id, request.redirect_uri, 
                request.response_type, request.scope, request.data.get('nonce'), int(time.time()),
                client_code_challenge, client_code_challenge_method
            ))
            conn.commit()
        return code

    def query_authorization_code(self, code, client):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oauth2_codes WHERE code = ? AND client_id = ?", (code, client.client_id))
            row = cursor.fetchone()
            if row:
                return OAuth2AuthorizationCode(dict(row))
        return None

    def delete_authorization_code(self, authorization_code):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM oauth2_codes WHERE id = ?", (authorization_code.data['id'],))
            conn.commit()

    def authenticate_user(self, authorization_code):
        return User.get(authorization_code.user_id)

class RefreshTokenGrant(grants.RefreshTokenGrant):
    def authenticate_refresh_token(self, refresh_token):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oauth2_tokens WHERE refresh_token = ? AND revoked = 0", (refresh_token,))
            row = cursor.fetchone()
            if row:
                return OAuth2Token(dict(row))
        return None

    def authenticate_user(self, credential):
        return User.get(credential.user_id)

    def revoke_old_credential(self, credential):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE oauth2_tokens SET revoked = 1 WHERE id = ?", (credential.data['id'],))
            conn.commit()

class MyBearerTokenValidator(BearerTokenValidator):
    def authenticate_token(self, token_string):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oauth2_tokens WHERE access_token = ? AND revoked = 0", (token_string,))
            row = cursor.fetchone()
            if row:
                return OAuth2Token(dict(row))
        return None

def config_oauth(app):
    auth_server.init_app(app, query_client=query_client, save_token=save_token)
    auth_server.register_grant(AuthorizationCodeGrant)
    auth_server.register_grant(RefreshTokenGrant)
    
    require_oauth.register_token_validator(MyBearerTokenValidator())
