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

    # Use Aiven's specific port 19605
    mysql_port = os.getenv('MYSQL_PORT', '19605')
    app.config['MYSQL_PORT'] = int(mysql_port)

    # Aiven SSL Configuration
    if os.getenv('RENDER'):
        # Aiven requires SSL. This tells flask-mysqldb to use it.
        app.config['MYSQL_CUSTOM_OPTIONS'] = {"ssl": {"ca": "/etc/ssl/certs/ca-certificates.crt"}}

    # Initialize extensions
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

    from app import models
    setup_logger(app)

    @app.errorhandler(429)
    def too_many_requests(e):
        return render_template('429.html'), 429

    from app.db_init import init_db
    init_db(app)

    return app