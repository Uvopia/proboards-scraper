"""
A self-hosted forum modeled on ProBoards v4.5: categories and boards,
threads with polls, a shoutbox, member profiles, private conversations and
an admin panel. Forums scraped with ``pbs`` can be imported with
``pbf import``.
"""
import os
import pathlib
import secrets
from typing import Optional

from flask import Flask

from . import auth, formatting, helpers
from .models import make_session_factory


def _load_secret_key(instance_path: pathlib.Path) -> str:
    """Use PBF_SECRET_KEY if set, else a key persisted in the instance dir."""
    key = os.environ.get("PBF_SECRET_KEY")
    if key:
        return key
    key_file = instance_path / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


def create_app(
    instance_path: Optional[str] = None, config: Optional[dict] = None
) -> Flask:
    """
    Create the forum application.

    Args:
        instance_path: Directory holding the database, secret key and
            uploads. Defaults to ``$PBF_INSTANCE`` or ``./forum``.
        config: Extra Flask config values (mainly for tests).
    """
    instance = pathlib.Path(
        instance_path or os.environ.get("PBF_INSTANCE", "forum")
    ).resolve()
    instance.mkdir(parents=True, exist_ok=True)
    (instance / "uploads").mkdir(exist_ok=True)

    app = Flask(__name__, instance_path=str(instance))
    app.config.update(
        DATABASE_URI=f"sqlite:///{instance / 'forum.db'}",
        UPLOAD_FOLDER=str(instance / "uploads"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Set PBF_SECURE_COOKIES=1 when serving over HTTPS.
        SESSION_COOKIE_SECURE=os.environ.get("PBF_SECURE_COOKIES") == "1",
    )
    if config:
        app.config.update(config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(instance)

    db = make_session_factory(app.config["DATABASE_URI"])
    app.extensions["db"] = db
    helpers.ensure_default_settings(db())
    db.remove()

    @app.teardown_appcontext
    def _remove_session(_exc):
        db.remove()

    auth.init_app(app)
    helpers.init_app(app)
    app.jinja_env.filters["render"] = formatting.render

    from .views import admin, forum, messages, users
    app.register_blueprint(forum.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(messages.bp)
    app.register_blueprint(admin.bp, url_prefix="/admin")

    return app


def get_db():
    """The current request's database session."""
    from flask import current_app
    return current_app.extensions["db"]()


__all__ = ["create_app", "get_db"]
