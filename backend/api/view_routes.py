from flask import Blueprint, send_from_directory, current_app
from flask_login import login_required

view_bp = Blueprint('views', __name__)

@view_bp.route('/login')
def login_page():
    return send_from_directory(current_app.static_folder, 'login.html')

@view_bp.route('/integrations')
@login_required
def integrations_page():
    return send_from_directory(current_app.static_folder, 'integrations.html')

@view_bp.route('/home-assistant-setup.html')
@login_required
def ha_setup_page():
    return send_from_directory(current_app.static_folder, 'home-assistant-setup.html')

@view_bp.route('/docs')
def docs_index():
    return send_from_directory(current_app.static_folder, 'docs/index.html')

@view_bp.route('/', defaults={'path': ''})
@view_bp.route('/<path:path>')
def serve_static(path):
    if (path == "" or path == "index.html"):
        return send_from_directory(current_app.static_folder, 'index.html')
    return send_from_directory(current_app.static_folder, path)
