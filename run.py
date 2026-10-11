import os
import secrets

from app import create_app, db

app = create_app()


def _bootstrap_database():
    """Create tables and seed on first boot. Idempotent."""
    with app.app_context():
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        if "product" not in tables:
            db.create_all()
            print("✓ Database tables created.")

            from app.cli import seed_catalog
            added = seed_catalog()
            print(f"✓ Seeded {added} products.")

            from app.models import User
            email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
            if not User.query.filter_by(email=email).first():
                password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
                u = User(email=email, name="Store admin", is_admin=True)
                u.set_password(password)
                db.session.add(u)
                db.session.commit()
                print(f"✓ Admin created: {email}")
                if not os.environ.get("ADMIN_PASSWORD"):
                    print(f"  Generated password: {password}")
        else:
            print("✓ Database already initialized.")


_bootstrap_database()


if __name__ == "__main__":
    app.run(debug=True)