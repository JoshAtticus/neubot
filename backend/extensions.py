from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector

login_manager = LoginManager()
oauth = OAuth()
auth_server = AuthorizationServer()
require_oauth = ResourceProtector()

