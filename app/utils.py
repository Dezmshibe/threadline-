import re
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import abort, current_app, redirect, request, url_for
from flask_login import current_user

from .constants import SIZE_ORDER

HEX_RE = re.compile(r"[0-9a-fA-F]{6}")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def money(cents):
    sym = current_app.config["CURRENCY_SYMBOL"]
    return f"{sym}{(cents or 0) / 100:,.2f}".replace(",", "\u00a0")


def parse_money(value):
    """'1 299,50' / '1299.5' -> cents, or None if invalid."""
    try:
        d = Decimal(str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".").lstrip("Rr"))
    except InvalidOperation:
        return None
    if d < 0 or d > Decimal("1000000"):
        return None
    return int((d * 100).quantize(Decimal("1")))


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "item"


def unique_slug(model, base, exclude_id=None):
    slug, n = slugify(base), 2
    while True:
        q = model.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{slugify(base)}-{n}"
        n += 1


def size_key(size):
    if size in SIZE_ORDER:
        return (0, SIZE_ORDER.index(size), "")
    try:
        return (1, int(size), "")
    except ValueError:
        return (2, 0, size)


def new_order_ref():
    return "TL" + secrets.token_hex(4).upper()


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped
