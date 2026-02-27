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

mysql = MySQL()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.config['MYSQL_PORT'] = int(os.getenv('MYSQL_PORT', 3306))

    # Enable SSL for Aiven only in production
    if os.getenv('RENDER'):
        app.config['MYSQL_SSL'] = True

    mysql.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

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