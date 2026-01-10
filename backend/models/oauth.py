from backend.database import get_db_connection
from authlib.oauth2.rfc6749 import ClientMixin, TokenMixin, AuthorizationCodeMixin
import time
import json

class OAuth2Client(ClientMixin):
    def __init__(self, client_id, client_secret, user_id, client_metadata):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self._client_metadata = client_metadata

    @property
    def client_info(self):
        return self._client_metadata

    def check_client_secret(self, client_secret):
        return self.client_secret == client_secret

    def check_endpoint_auth_method(self, method, endpoint):
        if endpoint == 'token':
            if len(self.client_secret) > 0:
                return method == 'client_secret_post' or method == 'client_secret_basic'
            else:
                return method == 'none'
        return True

    def check_response_type(self, response_type):
        allowed = self._client_metadata.get('response_types', [])
        return response_type in allowed

    def check_grant_type(self, grant_type):
        allowed = self._client_metadata.get('grant_types', [])
        return grant_type in allowed
    
    def check_redirect_uri(self, redirect_uri):
        allowed = self._client_metadata.get('redirect_uris', [])
        return redirect_uri in allowed

    def get_default_redirect_uri(self):
        allowed = self._client_metadata.get('redirect_uris', [])
        if allowed:
            return allowed[0]
        return None

    @staticmethod
    def get(client_id):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM api_clients WHERE client_id = ?", (client_id,))
            row = cursor.fetchone()
            if row:
                return OAuth2Client(
                    client_id=row['client_id'],
                    client_secret=row['client_secret'],
                    user_id=row['user_id'],
                    client_metadata=json.loads(row['client_metadata'])
                )
        return None

class OAuth2Token(TokenMixin):
    def __init__(self, data):
        self.data = data
        self.client_id = data.get('client_id')
        self.user_id = data.get('user_id')
        self.access_token = data.get('access_token')
        self.refresh_token = data.get('refresh_token')
        self.scope = data.get('scope')
        self.issued_at = data.get('issued_at')
        self.expires_in = data.get('expires_in')
        self.expires_at = self.issued_at + self.expires_in

    def get_scope(self):
        return self.scope

    def get_expires_in(self):
        return self.expires_in

    def get_expires_at(self):
        return self.expires_at

class OAuth2AuthorizationCode(AuthorizationCodeMixin):
    def __init__(self, data):
        self.data = data
        self.code = data.get('code')
        self.client_id = data.get('client_id')
        self.user_id = data.get('user_id')
        self.redirect_uri = data.get('redirect_uri')
        self.response_type = data.get('response_type')
        self.scope = data.get('scope')
        self.nonce = data.get('nonce')
        self.auth_time = data.get('auth_time')
        self.code_challenge = data.get('code_challenge')
        self.code_challenge_method = data.get('code_challenge_method')

    def get_redirect_uri(self):
        return self.redirect_uri

    def get_scope(self):
        return self.scope
    
    def get_auth_time(self):
        return self.auth_time
