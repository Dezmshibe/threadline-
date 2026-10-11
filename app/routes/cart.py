from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from .. import cartlib, db
from ..constants import PROVINCES
from ..models import Order, OrderItem, Product, Variant
from ..utils import EMAIL_RE, new_order_ref

bp = Blueprint("cart", __name__)


def payment_options():
    cfg = current_app.config
    opts = []
    if cfg["PAYFAST_MERCHANT_ID"] and cfg["PAYFAST_MERCHANT_KEY"]:
        opts.append(("payfast", "Card or instant EFT (PayFast)"))
    opts.append(("eft", "Manual EFT: we ship once payment reflects"))
    if cfg["ENABLE_COD"]:
        opts.append(("cod", "Pay on delivery"))
    return opts


def can_view_order(order):
    if current_user.is_authenticated and (current_user.is_admin or order.user_id == current_user.id):
        return True
    return order.ref in session.get("orders", [])


# ---------- discount ----------

@bp.post("/cart/discount")
def apply_discount():
    code = request.form.get("code", "").strip()
    ok, msg = cartlib.set_code(code)
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("cart.view"))


@bp.post("/cart/discount/remove")
def remove_discount():
    cartlib.clear_code()
    flash("Discount code removed.", "ok")
    return redirect(url_for("cart.view"))


# ---------- cart ----------

@bp.route("/cart")
def view():
    return render_template("cart.html", cart=cartlib.totals())


@bp.post("/cart/add")
def add():
    slug = request.form.get("product_slug", "")
    back = url_for("shop.product", slug=slug) if slug and Product.query.filter_by(slug=slug).first() else url_for("shop.shop")
    variant = db.session.get(Variant, request.form.get("variant_id", type=int) or 0)
    if not variant:
        flash("Choose a colour and size first.", "error")
        return redirect(back)
    if not variant.product.is_active or variant.stock <= 0:
        flash("That size is sold out.", "error")
        return redirect(back)
    qty = max(1, min(request.form.get("qty", 1, type=int), cartlib.MAX_QTY))
    if cartlib.add(variant, qty):
        flash(f"Added {variant.product.name} ({variant.color}, {variant.size}) to your cart.", "ok")
        return redirect(url_for("cart.view"))
    flash("Your cart already has all the stock we have of that size.", "error")
    return redirect(back)


@bp.post("/cart/update")
def update():
    cartlib.set_qty(request.form.get("variant_id", type=int) or 0, request.form.get("qty", 0, type=int))
    return redirect(url_for("cart.view"))


@bp.post("/cart/remove")
def remove():
    cartlib.remove(request.form.get("variant_id", type=int) or 0)
    return redirect(url_for("cart.view"))


# ---------- checkout ----------

def validate_checkout(form):
    f = {k: form.get(k, "").strip() for k in
         ("name", "email", "phone", "address1", "address2", "city", "province", "postal_code", "payment_method")}
    errors = {}
    if len(f["name"]) < 2:
        errors["name"] = "Enter your full name."
    if not EMAIL_RE.match(f["email"]):
        errors["email"] = "Enter a valid email address."
    digits = "".join(ch for ch in f["phone"] if ch.isdigit())
    if len(digits) < 9 or len(digits) > 13:
        errors["phone"] = "Enter a phone number we can reach for delivery."
    if len(f["address1"]) < 4:
        errors["address1"] = "Enter your street address."
    if len(f["city"]) < 2:
        errors["city"] = "Enter your city or town."
    if f["province"] not in PROVINCES:
        errors["province"] = "Choose a province."
    if not (f["postal_code"].isdigit() and len(f["postal_code"]) == 4):
        errors["postal_code"] = "Enter a 4-digit postal code."
    if f["payment_method"] not in [k for k, _ in payment_options()]:
        errors["payment_method"] = "Choose how you'd like to pay."
    return f, errors


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = cartlib.totals()
    if not cart["items"]:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view"))
    options = payment_options()
    form, errors = {"payment_method": options[0][0]}, {}
    if current_user.is_authenticated:
        form.update(name=current_user.name, email=current_user.email)

    if request.method == "POST":
        form, errors = validate_checkout(request.form)
        if not errors:
            # Re-check stock right before taking it.
            for line in cart["items"]:
                if line["variant"].stock < line["qty"]:
                    flash(f"Sorry, {line['product'].name} ({line['variant'].size}) just sold out.", "error")
                    return redirect(url_for("cart.view"))

            order = Order(
                ref=new_order_ref(),
                user_id=current_user.id if current_user.is_authenticated else None,
                email=form["email"].lower(),
                name=form["name"],
                phone=form["phone"],
                address1=form["address1"],
                address2=form["address2"] or None,
                city=form["city"],
                province=form["province"],
                postal_code=form["postal_code"],
                subtotal_cents=cart["subtotal"],
                discount_code=cart["discount"].code if cart["discount"] else None,
                discount_cents=cart["discount_cents"],
                shipping_cents=cart["shipping"],
                total_cents=cart["total"],
                payment_method=form["payment_method"],
                status="pending",
            )

            for line in cart["items"]:
                v = line["variant"]
                v.stock -= line["qty"]
                order.items.append(OrderItem(
                    variant_id=v.id,
                    product_name=line["product"].name,
                    size=v.size,
                    color=v.color,
                    unit_cents=line["product"].price_cents,
                    qty=line["qty"],
                ))

            db.session.add(order)

            # Increment discount usage BEFORE clearing the cart session
            if cart["discount"]:
                cart["discount"].uses += 1

            db.session.commit()

            cartlib.clear()
            session["orders"] = (session.get("orders", []) + [order.ref])[-20:]
            current_app.logger.info("New order %s (%s) total %s", order.ref, order.payment_method, order.total_cents)

            if order.payment_method == "payfast":
                return redirect(url_for("pay.start", ref=order.ref))
            return redirect(url_for("cart.order_view", ref=order.ref))

    return render_template("checkout.html", cart=cart, form=form, errors=errors, provinces=PROVINCES, options=options)


# ---------- order lookup ----------

@bp.route("/order/<ref>")
def order_view(ref):
    order = Order.query.filter_by(ref=ref).first_or_404()
    if not can_view_order(order):
        abort(404)
    return render_template("order.html", order=order, eft_details=current_app.config["EFT_DETAILS"])


@bp.route("/track", methods=["GET", "POST"])
def track():
    """Guest order lookup by reference + email."""
    error = None
    ref = email = ""
    if request.method == "POST":
        ref = request.form.get("ref", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        if not ref or not email:
            error = "Enter both your order reference and email."
        else:
            order = Order.query.filter_by(ref=ref, email=email).first()
            if order:
                session["orders"] = (session.get("orders", []) + [order.ref])[-20:]
                return redirect(url_for("cart.order_view", ref=order.ref))
            error = "No order matches that reference and email."
    return render_template("track.html", ref=ref, email=email, error=error)