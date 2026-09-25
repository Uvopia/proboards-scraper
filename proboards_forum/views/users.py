"""
Registration, login, member profiles and the member list.
"""
import os
import re
import secrets

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, url_for
)
from sqlalchemy import func, select

from .. import auth
from ..formatting import html_to_text
from ..helpers import (
    get_settings, is_safe_redirect, online_users, paginate, post_counts
)
from ..models import Post, Thread, User, now
from .forum import visible_board_ids


bp = Blueprint("users", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MIN_PASSWORD = 8
PROFILE_FIELDS = {
    "display_name": 64, "email": 255, "status": 255, "location": 128,
    "website": 128, "website_url": 512, "birthdate": 32, "gender": 16,
    "avatar_url": 512, "signature": 2000,
}


def find_user(name: str):
    return g.db.scalar(
        select(User).where(func.lower(User.username) == name.lower())
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    db = g.db
    if g.user is not None:
        return redirect(url_for("forum.index"))
    if get_settings(db)["registration_open"] != "1":
        flash("Registration is currently closed.", "error")
        return redirect(url_for("forum.index"))

    form = request.form
    if request.method == "POST":
        username = form.get("username", "").strip()
        display_name = form.get("display_name", "").strip() or username
        email = form.get("email", "").strip()
        password = form.get("password", "")
        errors = []
        if not USERNAME_RE.match(username):
            errors.append("Usernames must be 3-32 letters, numbers, "
                          "dots, dashes or underscores.")
        elif find_user(username) is not None:
            errors.append("That username is taken.")
        if len(display_name) > 64:
            errors.append("Display names can be at most 64 characters.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if len(password) < MIN_PASSWORD:
            errors.append(f"Passwords must be at least {MIN_PASSWORD} "
                          "characters.")
        elif password != form.get("confirm", ""):
            errors.append("Passwords don't match.")

        if not errors:
            # The very first member becomes the administrator.
            first = db.scalar(select(func.count(User.id))) == 0
            user = User(
                username=username, display_name=display_name, email=email,
                password_hash=auth.hash_password(password),
                role="admin" if first else "member",
            )
            db.add(user)
            db.commit()
            auth.login_user(user)
            flash(f"Welcome to the forum, {user.display_name}!", "success")
            return redirect(url_for("forum.index"))
        for error in errors:
            flash(error, "error")

    return render_template("users/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next")
    if not is_safe_redirect(next_url):
        next_url = url_for("forum.index")
    if g.user is not None:
        return redirect(next_url)

    if request.method == "POST":
        user = find_user(request.form.get("username", "").strip())
        if user is not None and auth.verify_password(
            user, request.form.get("password", "")
        ):
            if user.banned:
                flash("This account has been banned.", "error")
            else:
                auth.login_user(user)
                user.last_active = now()
                g.db.commit()
                return redirect(next_url)
        elif user is not None and not user.password_hash:
            flash("This account was imported and has no password yet. "
                  "Ask an administrator to set one.", "error")
        else:
            flash("Invalid username or password.", "error")

    return render_template("users/login.html", next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    auth.logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("forum.index"))


@bp.route("/user/<int:user_id>")
def profile(user_id: int):
    db = g.db
    user = db.get(User, user_id)
    if user is None:
        abort(404)
    board_ids = visible_board_ids()
    recent_posts = db.scalars(
        select(Post).join(Thread, Thread.id == Post.thread_id)
        .where(Post.user_id == user.id, Thread.board_id.in_(board_ids))
        .order_by(Post.created_at.desc(), Post.id.desc()).limit(5)
    ).all()
    thread_count = db.scalar(
        select(func.count(Thread.id)).where(Thread.user_id == user.id)
    )
    return render_template(
        "users/profile.html", user=user, recent_posts=recent_posts,
        post_count=post_counts(db, [user.id]).get(user.id, 0),
        thread_count=thread_count,
        online=user in online_users(db),
        messengers=parse_messengers(user.instant_messengers),
    )


def parse_messengers(value):
    pairs = []
    for item in (value or "").split(";"):
        if ":" in item:
            name, handle = item.split(":", 1)
            pairs.append((name.strip(), handle.strip()))
    return pairs


def save_avatar(file_storage) -> str:
    """Store an uploaded avatar and return its URL, or raise ValueError."""
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() \
        if "." in file_storage.filename else ""
    if ext not in AVATAR_EXTENSIONS:
        raise ValueError("Avatars must be PNG, JPG, GIF or WebP images.")
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    signatures = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")
    if not header.startswith(signatures):
        raise ValueError("That file doesn't look like an image.")
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "avatars")
    os.makedirs(folder, exist_ok=True)
    filename = f"{secrets.token_hex(12)}.{ext}"
    file_storage.save(os.path.join(folder, filename))
    return url_for("forum.uploads", filename=f"avatars/{filename}")


@bp.route("/user/<int:user_id>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_profile(user_id: int):
    db = g.db
    user = db.get(User, user_id)
    if user is None:
        abort(404)
    if user.id != g.user.id and not g.user.is_admin:
        abort(403)

    # Imported signatures are HTML; they're edited as plain text.
    signature = user.signature or ""
    if user.signature_format == "html":
        signature = html_to_text(signature)

    if request.method == "POST":
        form = request.form
        errors = []
        for field, limit in PROFILE_FIELDS.items():
            value = form.get(field, "").strip()
            if len(value) > limit:
                errors.append(f"{field.replace('_', ' ').title()} can be at "
                              f"most {limit} characters.")
        if not form.get("display_name", "").strip():
            errors.append("Display name can't be empty.")
        email = form.get("email", "").strip()
        if email and not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        for url_field in ("avatar_url", "website_url"):
            value = form.get(url_field, "").strip()
            if value and not re.match(r"^(https?://|/uploads/)", value):
                errors.append("Links must start with http:// or https://.")

        new_password = form.get("new_password", "")
        if new_password:
            if user.id == g.user.id and user.password_hash and \
                    not auth.verify_password(
                        user, form.get("current_password", "")):
                errors.append("Your current password is incorrect.")
            if len(new_password) < MIN_PASSWORD:
                errors.append(f"Passwords must be at least {MIN_PASSWORD} "
                              "characters.")
            elif new_password != form.get("confirm_password", ""):
                errors.append("New passwords don't match.")

        upload = request.files.get("avatar_file")
        if not errors and upload and upload.filename:
            try:
                user.avatar_url = save_avatar(upload)
            except ValueError as exc:
                errors.append(str(exc))

        if not errors:
            for field in PROFILE_FIELDS:
                if field == "avatar_url" and upload and upload.filename:
                    continue
                if field == "signature" and \
                        form.get(field, "").strip() == signature.strip():
                    continue
                setattr(user, field, form.get(field, "").strip() or None)
                if field == "signature":
                    user.signature_format = "bbcode"
            user.display_name = form["display_name"].strip()
            if new_password:
                user.password_hash = auth.hash_password(new_password)
            db.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("users.profile", user_id=user.id))
        for error in errors:
            flash(error, "error")

    return render_template(
        "users/edit_profile.html", user=user, signature=signature
    )


@bp.route("/members")
def members():
    db = g.db
    sort = request.args.get("sort", "name")
    query = request.args.get("q", "").strip()
    stmt = select(User)
    if query:
        stmt = stmt.where(User.display_name.ilike(f"%{query}%"))
    order = {
        "name": [func.lower(User.display_name)],
        "registered": [User.date_registered.desc()],
        "active": [User.last_active.desc().nulls_last()],
    }.get(sort, [func.lower(User.display_name)])
    stmt = stmt.order_by(*order, User.id)
    page = paginate(db, stmt, get_settings(db)["members_per_page"])
    return render_template(
        "users/members.html", page=page, sort=sort, query=query,
        counts=post_counts(db, [u.id for u in page.items]),
    )
