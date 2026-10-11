import os

from flask import Flask, render_template
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object("app.config.Config")
    if config:
        app.config.update(config)

    os.makedirs(app.config["INSTANCE_DIR"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Log in to continue."

    from .models import Category, User
    from . import cartlib
    from .utils import money

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.jinja_env.filters["money"] = money

    @app.context_processor
    def inject_globals():
        return {
            "store_name": app.config["STORE_NAME"],
            "cart_count": cartlib.count(),
            "nav_categories": Category.query.order_by(Category.name).all(),
            "free_shipping_over": app.config["FREE_SHIPPING_OVER"],
            "whatsapp_number": app.config.get("WHATSAPP_NUMBER", ""),
        }

    from .routes import admin, auth, cart, pay, shop
    for module in (shop, cart, auth, admin, pay):
        app.register_blueprint(module.bp)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "form-action 'self' https://www.payfast.co.za https://sandbox.payfast.co.za; "
            "frame-ancestors 'none'",
        )
        return resp

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You don't have access to this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="That file is too large. Images must be under 4 MB."), 413

    from .cli import register_cli
    register_cli(app)
    return app
