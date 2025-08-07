"""Initialisation du package SIEM AI : fabrique l’app Flask + SocketIO."""
from flask import Flask
from flask_socketio import SocketIO
from .config import settings
from .blueprints.dashboard import bp as dashboard_bp
from .blueprints.api import bp as api_bp

socketio = SocketIO()          # instance globale, partagée partout


def create_app() -> Flask:
    """Construit l’application, enregistre les blueprints, retourne l’objet Flask."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = settings.SECRET_KEY

    # Blueprints (HTML + API)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # SocketIO (CORS large pour l’instant)
    socketio.init_app(app, cors_allowed_origins="*")
    return app
