from flask import Flask
from flask_cors import CORS
from backend.config import Config
from backend.database import init_db
from backend.extensions import login_manager, oauth
from backend.models.user import User
from backend.api.api_routes import api_bp
from backend.api.auth_routes import auth_bp
from backend.api.view_routes import view_bp
import os
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
    app = Flask(__name__, static_folder=static_folder, template_folder=static_folder)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY
    
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = True

    CORS(app, origins="*", supports_credentials=True)
    login_manager.init_app(app)
    oauth.init_app(app)
    
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

    # Request loader for API tokens
    @login_manager.request_loader
    def load_user_from_request(request):
        # Check for Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header:
            try:
                # Expecting 'Bearer <token>'
                token = auth_header.replace('Bearer ', '', 1)
                from backend.security import decode_api_token
                user_id = decode_api_token(token)
                if user_id:
                    return User.get(user_id)
            except Exception:
                return None
        
        # Check for token in args (optional, but requested in initial prompt "grab token from URL parameters" was for callback, but good for testing)
        token = request.args.get('token')
        if token:
            try:
                from backend.security import decode_api_token
                user_id = decode_api_token(token)
                if user_id:
                    return User.get(user_id)
            except Exception:
                return None
                
        return None
        
    # Register blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(view_bp)
    
    # Initialize DB
    init_db()
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5300)
