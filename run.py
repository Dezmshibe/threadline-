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
        else:
            print("✓ Database already initialized.")

        # TEMPORARY: force admin password to match env vars on every boot.
        # Delete this block after you confirm login works.
        from app.models import User
        email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
        password = os.environ.get("ADMIN_PASSWORD", "ThreadlineDemo2026")
        u = User.query.filter_by(email=email).first()
        if u:
            u.set_password(password)
            u.is_admin = True
            db.session.commit()
            print(f"✓ Password reset for {email}")
        else:
            u = User(email=email, name="Store admin", is_admin=True)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print(f"✓ Admin created: {email}")
        print(f"  Login with: {email} / {password}")


_bootstrap_database()


if __name__ == "__main__":
    app.run(debug=True)