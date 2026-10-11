from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..models import Order, User
from ..utils import EMAIL_RE, safe_next

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))
    form, errors = {}, {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email")}
        password = request.form.get("password", "")
        if len(form["name"]) < 2:
            errors["name"] = "Enter your name."
        if not EMAIL_RE.match(form["email"]):
            errors["email"] = "Enter a valid email address."
        elif User.query.filter_by(email=form["email"].lower()).first():
            errors["email"] = "An account with this email already exists. Try logging in."
        if len(password) < 8:
            errors["password"] = "Use at least 8 characters."
        if not errors:
            user = User(email=form["email"].lower(), name=form["name"])
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your account is ready.", "ok")
            return redirect(url_for("auth.account"))
    return render_template("register.html", form=form, errors=errors)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(safe_next(request.args.get("next")) or url_for("auth.account"))
        error = "That email and password don't match."
    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("shop.home"))


@bp.route("/account")
@login_required
def account():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("account.html", orders=orders)
