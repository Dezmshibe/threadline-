"""Session-backed cart: {variant_id: qty}. Always re-validated against live stock."""
from flask import current_app, session

from . import db
from .models import Discount, Variant

MAX_QTY = 10


def _raw():
    return dict(session.get("cart", {}))


def count():
    return sum(_raw().values())


def add(variant, qty):
    cart, key = _raw(), str(variant.id)
    current = cart.get(key, 0)
    new = max(current, min(current + qty, variant.stock, MAX_QTY))
    cart[key] = new
    session["cart"] = cart
    return new > current


def set_qty(variant_id, qty):
    cart, key = _raw(), str(variant_id)
    if key in cart:
        if qty <= 0:
            del cart[key]
        else:
            cart[key] = min(qty, MAX_QTY)
        session["cart"] = cart


def remove(variant_id):
    set_qty(variant_id, 0)


def clear():
    session.pop("cart", None)
    session.pop("discount_code", None)


def lines():
    cart, clean, out = _raw(), {}, []
    for key, qty in cart.items():
        v = db.session.get(Variant, int(key))
        if not v or not v.product.is_active or v.stock <= 0:
            continue
        qty = max(1, min(int(qty), v.stock, MAX_QTY))
        clean[key] = qty
        out.append({"variant": v, "product": v.product, "qty": qty, "line_cents": qty * v.product.price_cents})
    if clean != cart:
        session["cart"] = clean
    return out


def shipping_for(subtotal):
    if subtotal <= 0 or subtotal >= current_app.config["FREE_SHIPPING_OVER"]:
        return 0
    return current_app.config["SHIPPING_FLAT"]


# ---------- discount ----------

def set_code(raw_code):
    """Returns (ok, message). Stores uppercase."""
    code = (raw_code or "").strip().upper()
    if not code:
        session.pop("discount_code", None)
        return True, "Code removed."
    d = Discount.query.filter_by(code=code).first()
    if not d:
        return False, "That code doesn't exist."
    subtotal = sum(i["line_cents"] for i in lines())
    ok, err = d.is_valid_for(subtotal)
    if not ok:
        return False, err
    session["discount_code"] = d.code
    return True, f"Code {d.code} applied."


def clear_code():
    session.pop("discount_code", None)


def _active_discount():
    """Fetch the discount in session, re-validating against current subtotal."""
    code = session.get("discount_code")
    if not code:
        return None
    d = Discount.query.filter_by(code=code).first()
    if not d:
        session.pop("discount_code", None)
        return None
    subtotal = sum(i["line_cents"] for i in lines())
    ok, _ = d.is_valid_for(subtotal)
    if not ok:
        session.pop("discount_code", None)
        return None
    return d


def totals():
    items = lines()
    subtotal = sum(i["line_cents"] for i in items)
    d = _active_discount()
    discount_cents = d.compute_cents(subtotal) if d else 0
    after_discount = subtotal - discount_cents
    shipping = shipping_for(after_discount)
    return {
        "items": items,
        "subtotal": subtotal,
        "discount": d,
        "discount_cents": discount_cents,
        "shipping": shipping,
        "total": after_discount + shipping,
    }