import os
import random
import secrets

import click

from . import db
from .models import Category, Product, ProductImage, User, Variant
from .utils import slugify

CATEGORIES = ["Tops", "Bottoms", "Dresses", "Outerwear", "Accessories"]
LETTER = ["XS", "S", "M", "L", "XL"]
LETTER_PLUS = ["XS", "S", "M", "L", "XL", "XXL"]
WAIST = ["28", "30", "32", "34", "36"]
ONE = ["One size"]

# name, category, price (rand), compare-at, sizes, [(colour, hex)], featured, description
SAMPLE = [
    ("Everyday Crew Tee", "Tops", 249, None, LETTER_PLUS, [("Chalk", "ededed"), ("Indigo", "2a3990"), ("Black", "1e1e22")], True,
     "Midweight combed cotton with a ribbed collar that keeps its shape wash after wash."),
    ("Heavyweight Pocket Tee", "Tops", 329, None, LETTER_PLUS, [("Olive", "6b705c"), ("Sand", "c2b280"), ("Rust", "a4492b")], True,
     "240gsm cotton, boxy through the body, with a chest pocket that sits flat."),
    ("Oxford Button-Down", "Tops", 549, None, LETTER, [("Sky", "9db7d5"), ("White", "f4f4f2")], False,
     "A softly washed oxford with a relaxed collar. Wears open over a tee or buttoned up."),
    ("Straight Leg Denim", "Bottoms", 899, 1099, WAIST, [("Indigo", "2b3a67"), ("Washed blue", "6f8fb5"), ("Black", "222226")], True,
     "12oz stretch denim with a mid rise and a straight leg that sits easily over boots or trainers."),
    ("Utility Cargo Pants", "Bottoms", 749, None, WAIST, [("Khaki", "a39e7a"), ("Black", "222226")], False,
     "Ripstop cotton with deep side pockets and an elastic-back waist."),
    ("Pleated Chino Shorts", "Bottoms", 449, None, WAIST, [("Stone", "bdb7a6"), ("Navy", "1f2a44")], False,
     "Knee-length, with a single pleat and a relaxed leg."),
    ("Wrap Midi Dress", "Dresses", 799, None, LETTER, [("Forest", "2f5d50"), ("Plum", "5b2a4e")], True,
     "Fluid viscose with an adjustable wrap waist and a midi hem."),
    ("Bias Slip Dress", "Dresses", 649, 799, LETTER, [("Black", "1f1f23"), ("Champagne", "d9c3a0")], False,
     "Cut on the bias so it drapes. Adjustable straps."),
    ("Zip Hoodie", "Outerwear", 699, None, LETTER_PLUS, [("Charcoal", "3a3f47"), ("Heather grey", "9a9ea6")], True,
     "Brushed-back fleece with a full zip and kangaroo pockets."),
    ("Coach Jacket", "Outerwear", 999, None, LETTER, [("Navy", "1f2a44"), ("Olive", "5a6148")], False,
     "Water-resistant nylon shell with a snap front and an unlined body."),
    ("Canvas Tote", "Accessories", 199, None, ONE, [("Natural", "d8cfb8"), ("Black", "222226")], False,
     "Heavy canvas with an inside pocket and long straps that fit over a shoulder."),
    ("Ribbed Beanie", "Accessories", 149, None, ONE, [("Charcoal", "3a3f47"), ("Mustard", "c99a2e"), ("Indigo", "2a3990")], False,
     "A stretchy rib knit that sits snug without squeezing."),
]


def seed_catalog():
    cats = {}
    for name in CATEGORIES:
        c = Category.query.filter_by(slug=slugify(name)).first() or Category(name=name, slug=slugify(name))
        db.session.add(c)
        cats[name] = c
    db.session.flush()
    rng = random.Random(42)
    added = 0
    for name, cat, price, compare, sizes, colors, featured, desc in SAMPLE:
        if Product.query.filter_by(slug=slugify(name)).first():
            continue
        p = Product(name=name, slug=slugify(name), description=desc, price_cents=price * 100,
                    compare_at_cents=compare * 100 if compare else None, category=cats[cat], featured=featured)
        for cname, hx in colors:
            for s in sizes:
                p.variants.append(Variant(size=s, color=cname, color_hex=hx, stock=rng.choice([0, 2, 5, 8, 12])))
        db.session.add(p)
        added += 1
    db.session.commit()
        # migrate legacy single image into the new gallery
    for p in Product.query.all():
        if p.image and not p.images:
            p.images.append(ProductImage(
                filename=p.image, alt_text=p.name, position=0
            ))
    db.session.commit()
    return added


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create database tables."""
        db.create_all()
        click.echo("Database ready.")

    @app.cli.command("seed")
    def seed():
        """Create tables, sample catalogue and the first admin."""
        db.create_all()
        n = seed_catalog()
        click.echo(f"Added {n} sample products.")
        email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
        if not User.query.filter_by(email=email).first():
            password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            u = User(email=email, name="Store admin", is_admin=True)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            click.echo(f"Admin created: {email}")
            if not os.environ.get("ADMIN_PASSWORD"):
                click.echo(f"Generated password (shown once): {password}")

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.password_option()
    def create_admin(email, password):
        """Create (or promote) an admin user."""
        db.create_all()
        email = email.lower()
        u = User.query.filter_by(email=email).first() or User(email=email, name="Store admin")
        u.is_admin = True
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Admin ready: {email}")
