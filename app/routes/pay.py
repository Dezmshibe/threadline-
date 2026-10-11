"""PayFast (South Africa) redirect + ITN webhook. https://developers.payfast.co.za/docs"""
import hashlib
import hmac
from urllib.parse import quote_plus

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from .. import csrf, db
from ..models import Order, utcnow
from .cart import can_view_order

bp = Blueprint("pay", __name__)


def signature(pairs, passphrase=""):
    """MD5 over the fields in posting order (not sorted), blanks skipped, optional passphrase appended."""
    s = "&".join(f"{k}={quote_plus(str(v).strip())}" for k, v in pairs if str(v).strip() != "")
    if passphrase:
        s += f"&passphrase={quote_plus(passphrase.strip())}"
    return hashlib.md5(s.encode()).hexdigest()


@bp.route("/pay/<ref>")
def start(ref):
    order = Order.query.filter_by(ref=ref).first_or_404()
    cfg = current_app.config
    if order.payment_method != "payfast" or order.status != "pending" or not can_view_order(order):
        abort(404)
    first, _, last = order.name.partition(" ")
    pairs = [
        ("merchant_id", cfg["PAYFAST_MERCHANT_ID"]),
        ("merchant_key", cfg["PAYFAST_MERCHANT_KEY"]),
        ("return_url", f"{cfg['PUBLIC_URL']}{url_for('cart.order_view', ref=order.ref)}"),
        ("cancel_url", f"{cfg['PUBLIC_URL']}{url_for('cart.order_view', ref=order.ref)}"),
        ("notify_url", f"{cfg['PUBLIC_URL']}{url_for('pay.notify')}"),
        ("name_first", first),
        ("name_last", last),
        ("email_address", order.email),
        ("m_payment_id", order.ref),
        ("amount", f"{order.total_cents / 100:.2f}"),
        ("item_name", f"Order {order.ref}"[:100]),
    ]
    pairs.append(("signature", signature(pairs, cfg["PAYFAST_PASSPHRASE"])))
    action = "https://sandbox.payfast.co.za/eng/process" if cfg["PAYFAST_SANDBOX"] else "https://www.payfast.co.za/eng/process"
    return render_template("pay.html", order=order, action=action, fields=[(k, v) for k, v in pairs if v != ""])


@bp.post("/payfast/notify")
@csrf.exempt
def notify():
    """Instant Transaction Notification. Verified by signature, merchant and amount."""
    cfg = current_app.config
    pairs = [(k, v) for k, v in request.form.items() if k != "signature"]
    expected = signature(pairs, cfg["PAYFAST_PASSPHRASE"])
    if not hmac.compare_digest(expected, request.form.get("signature", "")):
        current_app.logger.warning("PayFast ITN rejected: bad signature")
        return "", 400
    if request.form.get("merchant_id") != cfg["PAYFAST_MERCHANT_ID"]:
        return "", 400
    order = Order.query.filter_by(ref=request.form.get("m_payment_id", "")).first()
    if not order:
        return "", 404
    try:
        gross = round(float(request.form.get("amount_gross", "0")) * 100)
    except ValueError:
        return "", 400
    if gross != order.total_cents:
        current_app.logger.warning("PayFast ITN rejected: amount mismatch on %s", order.ref)
        return "", 400
    if request.form.get("payment_status") == "COMPLETE" and order.status == "pending":
        order.status = "paid"
        order.paid_at = utcnow()
        order.pf_payment_id = request.form.get("pf_payment_id", "")[:40]
        db.session.commit()
    return "", 200
