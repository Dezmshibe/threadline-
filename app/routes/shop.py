from flask import Blueprint, Response, abort, render_template, request
from sqlalchemy import and_, or_

from .. import db
from ..constants import HERO_SIZES
from ..models import Category, Product, Variant
from ..utils import HEX_RE, size_key

bp = Blueprint("shop", __name__)

SORTS = {
    "new": Product.created_at.desc(),
    "price_asc": Product.price_cents.asc(),
    "price_desc": Product.price_cents.desc(),
    "name": Product.name.asc(),
}


@bp.route("/")
def home():
    active = Product.query.filter_by(is_active=True)
    featured = active.filter_by(featured=True).order_by(Product.created_at.desc()).limit(4).all()
    newest = active.order_by(Product.created_at.desc()).limit(8).all()
    return render_template("index.html", featured=featured, newest=newest, hero_sizes=HERO_SIZES)


@bp.route("/shop")
def shop():
    q = request.args.get("q", "").strip()[:80]
    cat_slug = request.args.get("category", "")
    size = request.args.get("size", "")
    sort = request.args.get("sort", "new")
    page = request.args.get("page", 1, type=int)

    query = Product.query.filter_by(is_active=True)
    category = Category.query.filter_by(slug=cat_slug).first() if cat_slug else None
    if category:
        query = query.filter(Product.category_id == category.id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))
    if size:
        query = query.filter(Product.variants.any(and_(Variant.size == size, Variant.stock > 0)))
    query = query.order_by(SORTS.get(sort, SORTS["new"]))
    pagination = query.paginate(page=page, per_page=12, error_out=False)

    all_sizes = sorted({s for (s,) in db.session.query(Variant.size).distinct()}, key=size_key)
    return render_template("shop.html", pagination=pagination, products=pagination.items, q=q, category=category,
                           size=size, sort=sort, all_sizes=all_sizes)


@bp.route("/product/<slug>")
def product(slug):
    p = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    related = (Product.query.filter(Product.is_active.is_(True), Product.category_id == p.category_id, Product.id != p.id)
               .order_by(Product.created_at.desc()).limit(4).all())
    return render_template("product.html", p=p, groups=p.by_color(), related=related)


GARMENTS = {
    "top": ("M120 90 L160 68 Q200 104 240 68 L280 90 L346 154 L308 190 L276 162 L276 410 L124 410 L124 162 L92 190 L54 154 Z",
            "M160 68 Q200 104 240 68"),
    "outer": ("M118 96 L158 70 Q200 112 242 70 L282 96 L350 160 L316 360 L282 360 L278 420 L122 420 L118 360 L84 360 L50 160 Z",
              "M200 112 L200 420"),
    "bottom": ("M128 60 L272 60 L296 440 L214 440 L200 170 L186 440 L104 440 Z", "M200 60 L200 170"),
    "dress": ("M158 58 L242 58 L256 150 L306 440 L94 440 L144 150 Z", "M144 150 L256 150"),
    "bag": ("M108 190 H292 L314 440 H86 Z", "M150 190 Q150 96 200 96 Q250 96 250 190"),
}


@bp.route("/placeholder/<kind>/<hexcode>.svg")
def placeholder(kind, hexcode):
    if kind not in GARMENTS or not HEX_RE.fullmatch(hexcode):
        abort(404)
    body, detail = GARMENTS[kind]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500" role="img">'
        f'<path d="{body}" fill="#{hexcode}" stroke="#000" stroke-opacity=".18" stroke-width="2" stroke-linejoin="round"/>'
        f'<path d="{detail}" fill="none" stroke="#000" stroke-opacity=".28" stroke-width="3" stroke-dasharray="7 6" stroke-linecap="round"/>'
        "</svg>"
    )
    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
