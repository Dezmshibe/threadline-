import os
import secrets
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from .. import db
from ..constants import ORDER_STATUSES
from ..models import (
    Category, Discount, Order, OrderItem, Product, ProductImage, Variant, utcnow,
)
from ..utils import HEX_RE, admin_required, parse_money, slugify, unique_slug

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
@admin_required
def guard():
    pass


# ============================================================
# DASHBOARD
# ============================================================

@bp.route("/")
def dashboard():
    from datetime import timedelta
    from sqlalchemy import cast, Date

    revenue = (db.session.query(func.coalesce(func.sum(Order.total_cents), 0))
               .filter(Order.status.in_(["paid", "shipped", "delivered"])).scalar())
    stats = {
        "orders": Order.query.count(),
        "to_ship": Order.query.filter(Order.status == "paid").count(),
        "awaiting_payment": Order.query.filter(Order.status == "pending").count(),
        "revenue": revenue,
        "products": Product.query.filter_by(is_active=True).count(),
    }

    # 14-day revenue series
    since = utcnow() - timedelta(days=13)
    rows = (db.session.query(
                cast(Order.created_at, Date).label("d"),
                func.sum(Order.total_cents).label("cents"),
                func.count(Order.id).label("count"),
            )
            .filter(Order.status.in_(["paid", "shipped", "delivered"]),
                    Order.created_at >= since)
            .group_by("d").all())
    by_day = {r.d: {"cents": r.cents or 0, "count": r.count} for r in rows}
    days = []
    for i in range(14):
        d = (since + timedelta(days=i)).date()
        entry = by_day.get(d, {"cents": 0, "count": 0})
        days.append({"date": d, "cents": entry["cents"], "count": entry["count"]})
    peak = max((d["cents"] for d in days), default=0) or 1
    for d in days:
        d["pct"] = round(d["cents"] / peak * 100)

    low = (Variant.query.join(Product)
           .filter(Product.is_active.is_(True), Variant.stock <= 3)
           .order_by(Variant.stock, Product.name).limit(15).all())
    recent = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html",
                           stats=stats, low=low, recent=recent,
                           days=days, peak=peak)


# ============================================================
# PRODUCTS
# ============================================================

@bp.route("/products")
def products():
    q = request.args.get("q", "").strip()[:80]
    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    return render_template("admin/products.html",
                           products=query.order_by(Product.created_at.desc()).all(), q=q)


def _image_ok(head, ext):
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _save_image(file):
    ext = os.path.splitext(file.filename or "")[1].lower()
    head = file.stream.read(16)
    file.stream.seek(0)
    if not _image_ok(head, ext):
        return None
    name = secrets.token_hex(8) + ext
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name


def _parse_variants(form):
    rows, errors, seen = [], [], set()
    ids, sizes, colors = form.getlist("v_id"), form.getlist("v_size"), form.getlist("v_color")
    hexes, stocks = form.getlist("v_hex"), form.getlist("v_stock")
    for i in range(len(sizes)):
        size, color = sizes[i].strip()[:20], colors[i].strip()[:40]
        if not size and not color:
            continue  # blank row = removed
        hx = hexes[i].strip().lstrip("#") if i < len(hexes) else ""
        try:
            stock = int(stocks[i]) if i < len(stocks) else -1
        except ValueError:
            stock = -1
        if not size or not color:
            errors.append(f"Row {i + 1}: size and colour are both required.")
        elif not HEX_RE.fullmatch(hx):
            errors.append(f"Row {i + 1}: pick a colour swatch.")
        elif stock < 0:
            errors.append(f"Row {i + 1}: stock must be 0 or more.")
        elif (size.lower(), color.lower()) in seen:
            errors.append(f"Row {i + 1}: {color} / {size} is listed twice.")
        else:
            seen.add((size.lower(), color.lower()))
            rows.append({"id": int(ids[i]) if i < len(ids) and ids[i].isdigit() else None,
                         "size": size, "color": color, "hex": hx.lower(), "stock": stock})
    if not rows and not errors:
        errors.append("Add at least one size and colour.")
    return rows, errors


def _save_product(product):
    f = request.form
    errors = []
    name = f.get("name", "").strip()
    price = parse_money(f.get("price", ""))
    compare = parse_money(f.get("compare_at", "")) if f.get("compare_at", "").strip() else None
    category = db.session.get(Category, f.get("category_id", type=int) or 0)
    if len(name) < 2:
        errors.append("Enter a product name.")
    if price is None or price <= 0:
        errors.append("Enter a price above zero.")
    if f.get("compare_at", "").strip() and (compare is None or (price and compare <= price)):
        errors.append("Compare-at price must be higher than the price.")
    if not category:
        errors.append("Choose a category.")
    rows, vErrors = _parse_variants(f)
    errors += vErrors

    image_name = None
    upload = request.files.get("image")
    if upload and upload.filename:
        image_name = _save_image(upload)
        if not image_name:
            errors.append("Image must be a real JPG, PNG or WebP file.")
    if errors:
        return errors

    if product.slug is None:
        with db.session.no_autoflush:
            product.slug = unique_slug(Product, name)
    product.name, product.description = name, f.get("description", "").strip()
    product.price_cents, product.compare_at_cents, product.category = price, compare, category
    product.featured, product.is_active = bool(f.get("featured")), bool(f.get("is_active"))
    if image_name:
        product.image = image_name
    elif f.get("remove_image"):
        product.image = None

    existing = {v.id: v for v in product.variants}
    keep = set()
    for r in rows:
        v = existing.get(r["id"]) if r["id"] else None
        if v is None:
            v = Variant()
            product.variants.append(v)
        v.size, v.color, v.color_hex, v.stock = r["size"], r["color"], r["hex"], r["stock"]
        if v.id:
            keep.add(v.id)
    for vid, v in existing.items():
        if vid not in keep:
            OrderItem.query.filter_by(variant_id=vid).update({"variant_id": None})
            product.variants.remove(v)
    db.session.add(product)
    db.session.commit()
    return []


def _form_page(product):
    selected = request.form.get("category_id", type=int) if request.form else product.category_id
    return render_template("admin/product_form.html", product=product, form=request.form,
                           selected_category=selected,
                           categories=Category.query.order_by(Category.name).all())


@bp.route("/products/new", methods=["GET", "POST"])
def product_new():
    product = Product(is_active=True)
    if request.method == "POST":
        errors = _save_product(product)
        if not errors:
            flash("Product created.", "ok")
            return redirect(url_for("admin.products"))
        for e in errors:
            flash(e, "error")
        db.session.rollback()
    return _form_page(product)


@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def product_edit(pid):
    product = db.session.get(Product, pid) or abort(404)
    if request.method == "POST":
        errors = _save_product(product)
        if not errors:
            flash("Changes saved.", "ok")
            return redirect(url_for("admin.products"))
        for e in errors:
            flash(e, "error")
        db.session.rollback()
    return _form_page(product)


@bp.post("/products/<int:pid>/toggle")
def product_toggle(pid):
    product = db.session.get(Product, pid) or abort(404)
    product.is_active = not product.is_active
    db.session.commit()
    flash(f"{product.name} is now {'visible' if product.is_active else 'hidden'}.", "ok")
    return redirect(url_for("admin.products"))


# ============================================================
# PRODUCT IMAGES
# ============================================================

@bp.post("/products/<int:pid>/images/upload")
def product_image_upload(pid):
    product = db.session.get(Product, pid) or abort(404)
    files = request.files.getlist("images")
    added = 0
    for f in files:
        if not f or not f.filename:
            continue
        name = _save_image(f)
        if not name:
            continue
        pos = len(product.images)
        product.images.append(ProductImage(
            filename=name,
            alt_text=product.name,
            position=pos,
        ))
        added += 1
    db.session.commit()
    flash(f"Added {added} image{'s' if added != 1 else ''}.", "ok")
    return redirect(url_for("admin.product_edit", pid=product.id))


@bp.post("/products/<int:pid>/images/<int:iid>/delete")
def product_image_delete(pid, iid):
    product = db.session.get(Product, pid) or abort(404)
    img = db.session.get(ProductImage, iid) or abort(404)
    if img.product_id != product.id:
        abort(404)
    db.session.delete(img)
    db.session.commit()
    # re-index positions
    for i, im in enumerate(product.images):
        im.position = i
    db.session.commit()
    flash("Image removed.", "ok")
    return redirect(url_for("admin.product_edit", pid=product.id))


@bp.post("/products/<int:pid>/images/reorder")
def product_image_reorder(pid):
    product = db.session.get(Product, pid) or abort(404)
    ids = request.form.getlist("image_ids")
    for i, iid in enumerate(ids):
        if not iid.isdigit():
            continue
        img = db.session.get(ProductImage, int(iid))
        if img and img.product_id == product.id:
            img.position = i
    db.session.commit()
    flash("Order saved.", "ok")
    return redirect(url_for("admin.product_edit", pid=product.id))


@bp.post("/products/<int:pid>/images/<int:iid>/make-primary")
def product_image_primary(pid, iid):
    product = db.session.get(Product, pid) or abort(404)
    img = db.session.get(ProductImage, iid) or abort(404)
    if img.product_id != product.id:
        abort(404)
    # move this image to position 0, shift others up
    others = [i for i in product.images if i.id != img.id]
    img.position = 0
    for j, o in enumerate(others, start=1):
        o.position = j
    # also set the legacy field
    product.image = img.filename
    db.session.commit()
    flash("Primary image updated.", "ok")
    return redirect(url_for("admin.product_edit", pid=product.id))


# ============================================================
# CATEGORIES
# ============================================================

@bp.route("/categories", methods=["GET", "POST"])
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        if len(name) < 2:
            flash("Enter a category name.", "error")
        elif Category.query.filter_by(slug=slugify(name)).first():
            flash("That category already exists.", "error")
        else:
            db.session.add(Category(name=name, slug=slugify(name)))
            db.session.commit()
            flash("Category added.", "ok")
        return redirect(url_for("admin.categories"))
    return render_template("admin/categories.html",
                           categories=Category.query.order_by(Category.name).all())


# ============================================================
# ORDERS
# ============================================================

@bp.route("/orders")
def orders():
    status = request.args.get("status", "")
    query = Order.query
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    return render_template("admin/orders.html",
                           orders=query.order_by(Order.created_at.desc()).limit(200).all(),
                           status=status, statuses=ORDER_STATUSES)


@bp.route("/orders/<int:oid>", methods=["GET", "POST"])
def order_detail(oid):
    order = db.session.get(Order, oid) or abort(404)
    if request.method == "POST":
        new = request.form.get("status", "")
        old = order.status
        if new not in ORDER_STATUSES:
            flash("Choose a valid status.", "error")
        elif old == "cancelled" and new != "cancelled":
            flash("Cancelled orders can't be reopened. Ask the customer to place a new order.", "error")
        else:
            if new == "cancelled" and old != "cancelled":
                for item in order.items:  # put stock back
                    if item.variant:
                        item.variant.stock += item.qty
            if new == "paid" and not order.paid_at:
                order.paid_at = utcnow()
            order.status = new
            db.session.commit()
            flash(f"Order {order.ref} is now {new}.", "ok")
        return redirect(url_for("admin.order_detail", oid=order.id))
    return render_template("admin/order_detail.html", order=order, statuses=ORDER_STATUSES)


# ============================================================
# DISCOUNTS
# ============================================================

@bp.route("/discounts")
def discounts():
    items = Discount.query.order_by(Discount.created_at.desc()).all()
    return render_template("admin/discounts.html", discounts=items)


def _parse_discount_form(form, existing=None):
    errors = []
    code = (form.get("code", "") or "").strip().upper()
    kind = form.get("kind", "percent")
    amount_raw = form.get("amount", "").strip()
    min_raw = form.get("min_spend", "").strip()
    max_raw = form.get("max_uses", "").strip()
    until_raw = form.get("valid_until", "").strip()

    if not (3 <= len(code) <= 40) or not code.replace("-", "").replace("_", "").isalnum():
        errors.append("Code must be 3–40 characters, letters/numbers/dashes only.")

    if existing is None or code != existing.code:
        if Discount.query.filter_by(code=code).first():
            errors.append("That code already exists.")

    if kind not in ("percent", "fixed"):
        errors.append("Kind must be percent or fixed.")

    amount = None
    if kind == "percent":
        try:
            amount = int(amount_raw)
        except (TypeError, ValueError):
            amount = None
        if amount is None or not (1 <= amount <= 100):
            errors.append("Percent must be between 1 and 100.")
    else:
        amount = parse_money(amount_raw)
        if amount is None or amount <= 0:
            errors.append("Fixed amount must be above zero.")

    min_spend = parse_money(min_raw) if min_raw else 0
    if min_spend is None or min_spend < 0:
        errors.append("Minimum spend must be zero or more.")

    max_uses = None
    if max_raw:
        try:
            max_uses = int(max_raw)
            if max_uses < 1:
                raise ValueError
        except ValueError:
            errors.append("Max uses must be a whole number above zero.")

    valid_until = None
    if until_raw:
        try:
            valid_until = datetime.strptime(until_raw, "%Y-%m-%d")
        except ValueError:
            errors.append("Valid-until date must be YYYY-MM-DD.")

    return {
        "code": code, "kind": kind, "amount": amount, "min_spend_cents": min_spend,
        "max_uses": max_uses, "valid_until": valid_until,
    }, errors


@bp.route("/discounts/new", methods=["GET", "POST"])
def discount_new():
    if request.method == "POST":
        data, errors = _parse_discount_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            d = Discount(
                code=data["code"], kind=data["kind"], amount=data["amount"],
                min_spend_cents=data["min_spend_cents"], max_uses=data["max_uses"],
                valid_until=data["valid_until"], active=True,
            )
            db.session.add(d)
            db.session.commit()
            flash(f"Discount {d.code} created.", "ok")
            return redirect(url_for("admin.discounts"))
    return render_template("admin/discount_form.html", discount=None, form=request.form)


@bp.route("/discounts/<int:did>/edit", methods=["GET", "POST"])
def discount_edit(did):
    d = db.session.get(Discount, did) or abort(404)
    if request.method == "POST":
        data, errors = _parse_discount_form(request.form, existing=d)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            d.code = data["code"]
            d.kind = data["kind"]
            d.amount = data["amount"]
            d.min_spend_cents = data["min_spend_cents"]
            d.max_uses = data["max_uses"]
            d.valid_until = data["valid_until"]
            d.active = bool(request.form.get("active"))
            db.session.commit()
            flash(f"Discount {d.code} updated.", "ok")
            return redirect(url_for("admin.discounts"))
    return render_template("admin/discount_form.html", discount=d, form=request.form)


@bp.post("/discounts/<int:did>/toggle")
def discount_toggle(did):
    d = db.session.get(Discount, did) or abort(404)
    d.active = not d.active
    db.session.commit()
    flash(f"{d.code} is now {'active' if d.active else 'inactive'}.", "ok")
    return redirect(url_for("admin.discounts"))


@bp.post("/discounts/<int:did>/delete")
def discount_delete(did):
    d = db.session.get(Discount, did) or abort(404)
    db.session.delete(d)
    db.session.commit()
    flash("Discount deleted.", "ok")
    return redirect(url_for("admin.discounts"))