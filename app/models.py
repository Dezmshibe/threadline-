from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .constants import KIND_BY_CATEGORY
from .utils import size_key


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(90), unique=True, nullable=False, index=True)
    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default="")
    price_cents = db.Column(db.Integer, nullable=False)
    compare_at_cents = db.Column(db.Integer)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))
    image = db.Column(db.String(120))
    featured = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    category = db.relationship("Category", back_populates="products")
    variants = db.relationship(
        "Variant",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="Variant.id",
    )
    images = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )

    @property
    def on_sale(self):
        return bool(self.compare_at_cents and self.compare_at_cents > self.price_cents)

    @property
    def in_stock(self):
        return any(v.stock > 0 for v in self.variants)

    @property
    def kind(self):
        return KIND_BY_CATEGORY.get(self.category.slug if self.category else "", "top")

    def by_color(self):
        groups = {}
        for v in self.variants:
            g = groups.setdefault(v.color, {"name": v.color, "hex": v.color_hex, "variants": []})
            g["variants"].append(v)
        for g in groups.values():
            g["variants"].sort(key=lambda v: size_key(v.size))
        return list(groups.values())

    @property
    def colors(self):
        return [{"name": g["name"], "hex": g["hex"]} for g in self.by_color()]

    @property
    def size_status(self):
        sizes = {}
        for v in self.variants:
            sizes[v.size] = sizes.get(v.size, False) or v.stock > 0
        return [{"size": s, "available": sizes[s]} for s in sorted(sizes, key=size_key)]


class Variant(db.Model):
    __table_args__ = (db.UniqueConstraint("product_id", "size", "color", name="uq_variant"),)
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    size = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(40), nullable=False)
    color_hex = db.Column(db.String(6), nullable=False, default="cfd3da")
    stock = db.Column(db.Integer, nullable=False, default=0)
    product = db.relationship("Product", back_populates="variants")


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    filename = db.Column(db.String(120), nullable=False)
    alt_text = db.Column(db.String(200), default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    product = db.relationship("Product", back_populates="images")

class Discount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)  # stored UPPERCASE
    kind = db.Column(db.String(10), nullable=False)  # 'percent' or 'fixed'
    amount = db.Column(db.Integer, nullable=False)   # percent (1-100) or cents
    min_spend_cents = db.Column(db.Integer, nullable=False, default=0)
    max_uses = db.Column(db.Integer)                 # None = unlimited
    uses = db.Column(db.Integer, nullable=False, default=0)
    valid_from = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def expired(self):
        if self.valid_until and self.valid_until < utcnow():
            return True
        return False

    @property
    def maxed_out(self):
        return self.max_uses is not None and self.uses >= self.max_uses

    def is_valid_for(self, subtotal_cents):
        """Return (ok, error_message)."""
        if not self.active:
            return False, "That code is no longer active."
        if self.expired:
            return False, "That code has expired."
        if self.maxed_out:
            return False, "That code has reached its usage limit."
        if subtotal_cents < self.min_spend_cents:
            from .utils import money
            return False, f"Spend at least {money(self.min_spend_cents)} to use this code."
        return True, None

    def compute_cents(self, subtotal_cents):
        """Amount in cents this discount takes off (never exceeds subtotal)."""
        if self.kind == "percent":
            return min(subtotal_cents, subtotal_cents * self.amount // 100)
        return min(subtotal_cents, self.amount)



class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(20), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address1 = db.Column(db.String(200), nullable=False)
    address2 = db.Column(db.String(200))
    city = db.Column(db.String(100), nullable=False)
    province = db.Column(db.String(40), nullable=False)
    postal_code = db.Column(db.String(10), nullable=False)
    subtotal_cents = db.Column(db.Integer, nullable=False)
    shipping_cents = db.Column(db.Integer, nullable=False)
    total_cents = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    pf_payment_id = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    paid_at = db.Column(db.DateTime)

    user = db.relationship("User", backref="orders")
    items = db.relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("variant.id"))
    product_name = db.Column(db.String(160), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(40), nullable=False)
    unit_cents = db.Column(db.Integer, nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    order = db.relationship("Order", back_populates="items")
    variant = db.relationship("Variant")

    @property
    def line_cents(self):
        return self.unit_cents * self.qty