import os
from flask import Flask, render_template
from flask_mysqldb import MySQL
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from config import Config
from app.utils.logger import setup_logger

# Initialize extensions globally
mysql = MySQL()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Convert port to int and provide a default
    mysql_port = os.getenv('MYSQL_PORT', '3306')
    app.config['MYSQL_PORT'] = int(mysql_port)

    # Aiven/Render SSL Configuration
    # Note: 'MYSQL_SSL_MODE' is the standard key for flask-mysqldb 
    if os.getenv('RENDER'):
        app.config['MYSQL_CUSTOM_OPTIONS'] = {"ssl": {"ca": "/etc/ssl/certs/ca-certificates.crt"}}
        # Alternatively, if your setup uses the newer connector:
        # app.config['MYSQL_SSL_MODE'] = 'REQUIRED'

    # Initialize extensions with the app
    mysql.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # Register Blueprints
    from app.auth import auth_bp
    from app.prescriptions import prescriptions_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(prescriptions_bp)

    # Load models
    from app import models

    # Setup logger
    setup_logger(app)

    @app.errorhandler(429)
    def too_many_requests(e):
        return render_template('429.html'), 429

    # Database Initialization
    from app.db_init import init_db
    init_db(app)

    return app