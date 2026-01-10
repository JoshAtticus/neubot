from flask import Flask
from flask_cors import CORS
from backend.config import Config
from backend.database import init_db
from backend.extensions import login_manager, oauth
from backend.models.user import User
from backend.api.api_routes import api_bp
from backend.api.auth_routes import auth_bp
from backend.api.view_routes import view_bp
from backend.api.developer_routes import developer_bp
from backend.oauth2 import config_oauth
import os
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    # Adjust static_folder to point to the root static directory
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
    app = Flask(__name__, static_folder=static_folder, template_folder=static_folder)
    
    # Enable ProxyFix for proper URL generation behind reverse proxies (Coolify/Traefik)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY
    
    # Session config
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False # Set to True in production

    # OAuth2 Provider Config
    config_oauth(app)
    
    # Initialize extensions
    CORS(app, origins="*", supports_credentials=True)
    login_manager.init_app(app)
    oauth.init_app(app)
    
    # Register OAuth providers
    oauth.register(
        name='google',
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

    oauth.register(
        name='github',
        client_id=Config.GITHUB_CLIENT_ID,
        client_secret=Config.GITHUB_CLIENT_SECRET,
        access_token_url='https://github.com/login/oauth/access_token',
        access_token_params=None,
        authorize_url='https://github.com/login/oauth/authorize',
        authorize_params=None,
        api_base_url='https://api.github.com/',
        client_kwargs={'scope': 'user:email'},
    )
    
    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        return User.get(user_id)
        
    # Register blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(view_bp)
    app.register_blueprint(developer_bp)
    
    # Initialize DB
    init_db()
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5300)
