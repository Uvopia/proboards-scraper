"""
Sessions, CSRF protection and permission checks.
"""
import functools
import hmac
import secrets
from typing import Optional

from flask import (
    abort, current_app, flash, g, redirect, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from .models import Board, Moderator, Post, Thread, User, now


# Only write last_active once a minute per user.
ACTIVITY_WRITE_INTERVAL = 60


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(user: User, password: str) -> bool:
    if not user.password_hash:
        return False
    return check_password_hash(user.password_hash, password)


def login_user(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def init_app(app) -> None:
    @app.before_request
    def _load_user():
        db = current_app.extensions["db"]()
        g.db = db
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            user = db.get(User, user_id)
            if user is None or user.banned:
                session.pop("user_id", None)
            else:
                g.user = user
                timestamp = now()
                if (
                    user.last_active is None
                    or timestamp - user.last_active > ACTIVITY_WRITE_INTERVAL
                ):
                    user.last_active = timestamp
                    db.commit()

    @app.before_request
    def _check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get(
                "X-CSRF-Token", ""
            )
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, "Your session expired. Please try again.")

    app.jinja_env.globals["csrf_token"] = csrf_token


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("You must be logged in to do that.", "error")
            return redirect(url_for("users.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("users.login", next=request.full_path))
        if not g.user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def can_view_board(board: Board, user: Optional[User] = None) -> bool:
    user = user if user is not None else g.user
    if board.staff_only and not (user and user.is_staff):
        return False
    return board.parent is None or can_view_board(board.parent, user)


def can_moderate(board: Board, user: Optional[User] = None) -> bool:
    user = user if user is not None else g.user
    if user is None:
        return False
    if user.is_staff:
        return True
    board_ids = [board.id] + [b.id for b in board.ancestors()]
    return g.db.query(Moderator).filter(
        Moderator.user_id == user.id, Moderator.board_id.in_(board_ids)
    ).first() is not None


def can_start_thread(board: Board) -> bool:
    if g.user is None:
        return False
    return not board.read_only or can_moderate(board)


def can_reply(thread: Thread) -> bool:
    if g.user is None:
        return False
    return not thread.locked or can_moderate(thread.board)


def can_edit_post(post: Post) -> bool:
    if g.user is None:
        return False
    if can_moderate(post.thread.board):
        return True
    return post.user_id == g.user.id and not post.thread.locked
