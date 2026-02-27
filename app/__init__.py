from flask import Flask

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    mysql_port = os.getenv('MYSQL_PORT')
    if mysql_port:
        app.config['MYSQL_PORT'] = int(mysql_port)

    if os.getenv('RENDER'):
        app.config['MYSQL_SSL'] = True

    # This will now show in logs before any DB connection attempt
    import logging
    logging.basicConfig(level=logging.INFO)
    logging.info(
        f"DB CONFIG | host={os.getenv('MYSQL_HOST')} | "
        f"port={os.getenv('MYSQL_PORT')} | "
        f"user={os.getenv('MYSQL_USER')} | "
        f"db={os.getenv('MYSQL_DB')} | "
        f"render={os.getenv('RENDER')}"
    )

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