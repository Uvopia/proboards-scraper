"""
Admin panel: forum settings, categories, boards and members.
"""
import re

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for
)
from sqlalchemy import delete, func, select

from .. import auth
from ..helpers import DEFAULT_SETTINGS, paginate, set_setting
from ..models import (
    ROLE_TITLES, Board, Category, Moderator, Post, ShoutboxPost, Thread,
    User
)
from .forum import delete_thread
from .users import MIN_PASSWORD


bp = Blueprint("admin", __name__)


@bp.before_request
@auth.admin_required
def _require_admin():
    return None


@bp.route("/")
def dashboard():
    db = g.db
    counts = {
        "members": db.scalar(select(func.count(User.id))),
        "threads": db.scalar(select(func.count(Thread.id))),
        "posts": db.scalar(select(func.count(Post.id))),
        "shouts": db.scalar(select(func.count(ShoutboxPost.id))),
        "categories": db.scalar(select(func.count(Category.id))),
        "boards": db.scalar(select(func.count(Board.id))),
    }
    return render_template("admin/dashboard.html", counts=counts)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    db = g.db
    if request.method == "POST":
        form = request.form
        for key in ("forum_name", "forum_description", "announcement"):
            set_setting(db, key, form.get(key, "").strip()[:2000])
        for key in ("threads_per_page", "posts_per_page",
                    "members_per_page"):
            value = form.get(key, "")
            if value.isdigit() and 1 <= int(value) <= 200:
                set_setting(db, key, value)
        for key in ("shoutbox_enabled", "registration_open"):
            set_setting(db, key, "1" if form.get(key) else "0")
        color = form.get("theme_color", "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            set_setting(db, "theme_color", color)
        else:
            set_setting(db, "theme_color", DEFAULT_SETTINGS["theme_color"])
        db.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html")


# --- Categories & boards ------------------------------------------------

@bp.route("/structure")
def structure():
    db = g.db
    categories = db.scalars(
        select(Category).order_by(Category.position, Category.id)
    ).all()
    return render_template("admin/structure.html", categories=categories)


@bp.route("/category", methods=["POST"])
@bp.route("/category/<int:category_id>", methods=["POST"])
def save_category(category_id: int = None):
    db = g.db
    name = request.form.get("name", "").strip()[:128]
    if not name:
        flash("Categories need a name.", "error")
        return redirect(url_for("admin.structure"))
    if category_id is None:
        position = db.scalar(select(func.max(Category.position))) or 0
        db.add(Category(name=name, position=position + 1))
    else:
        category = db.get(Category, category_id) or abort(404)
        category.name = name
        category.position = request.form.get(
            "position", type=int, default=category.position
        )
    db.commit()
    flash("Category saved.", "success")
    return redirect(url_for("admin.structure"))


@bp.route("/category/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id: int):
    db = g.db
    category = db.get(Category, category_id) or abort(404)
    if db.scalar(select(func.count(Board.id))
                 .where(Board.category_id == category.id)):
        flash("Move or delete this category's boards first.", "error")
    else:
        db.delete(category)
        db.commit()
        flash("Category deleted.", "success")
    return redirect(url_for("admin.structure"))


def board_choices(exclude: Board = None) -> list[Board]:
    boards = g.db.scalars(select(Board).order_by(Board.name)).all()
    if exclude is None:
        return boards
    excluded = set(exclude.descendant_ids())
    return [b for b in boards if b.id not in excluded]


@bp.route("/board/new", methods=["GET", "POST"])
@bp.route("/board/<int:board_id>", methods=["GET", "POST"])
def edit_board(board_id: int = None):
    db = g.db
    board = None
    if board_id is not None:
        board = db.get(Board, board_id) or abort(404)
    categories = db.scalars(
        select(Category).order_by(Category.position, Category.id)
    ).all()
    if not categories:
        flash("Create a category first.", "error")
        return redirect(url_for("admin.structure"))

    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()[:128]
        category = db.get(Category, form.get("category_id", type=int) or 0)
        parent = db.get(Board, form.get("parent_id", type=int) or 0)
        errors = []
        if not name:
            errors.append("Boards need a name.")
        if category is None:
            errors.append("Please choose a category.")
        if parent is not None and board is not None \
                and parent.id in board.descendant_ids():
            errors.append("A board can't be its own sub-board.")

        moderators = []
        for username in form.get("moderators", "").split(","):
            username = username.strip()
            if not username:
                continue
            user = db.scalar(select(User).where(
                func.lower(User.username) == username.lower()
            ))
            if user is None:
                errors.append(f"No member with username “{username}"
                              "”.")
            else:
                moderators.append(user)

        if not errors:
            if board is None:
                board = Board()
                db.add(board)
            board.name = name
            board.description = form.get("description", "").strip() or None
            board.parent_id = parent.id if parent else None
            # Sub-boards always live in their parent's category.
            board.category_id = parent.category_id if parent else category.id
            board.position = form.get("position", type=int, default=0)
            board.staff_only = bool(form.get("staff_only"))
            board.read_only = bool(form.get("read_only"))
            board.moderators = moderators
            db.flush()
            for sub_id in board.descendant_ids():
                db.get(Board, sub_id).category_id = board.category_id
            db.commit()
            flash("Board saved.", "success")
            return redirect(url_for("admin.structure"))
        for error in errors:
            flash(error, "error")

    return render_template(
        "admin/board.html", board=board, categories=categories,
        parents=board_choices(board),
    )


@bp.route("/board/<int:board_id>/delete", methods=["POST"])
def delete_board(board_id: int):
    db = g.db
    board = db.get(Board, board_id) or abort(404)
    if board.sub_boards:
        flash("Move or delete this board's sub-boards first.", "error")
        return redirect(url_for("admin.edit_board", board_id=board.id))
    target = db.get(Board, request.form.get("move_to", type=int) or 0)
    threads = db.scalars(
        select(Thread).where(Thread.board_id == board.id)
    ).all()
    for thread in threads:
        if target is not None and target.id != board.id:
            thread.board_id = target.id
        else:
            delete_thread(thread)
    db.execute(delete(Moderator).where(Moderator.board_id == board.id))
    db.delete(board)
    db.commit()
    flash("Board deleted.", "success")
    return redirect(url_for("admin.structure"))


# --- Members ------------------------------------------------------------

@bp.route("/users")
def users():
    db = g.db
    query = request.args.get("q", "").strip()
    stmt = select(User)
    if query:
        stmt = stmt.where(
            User.username.ilike(f"%{query}%")
            | User.display_name.ilike(f"%{query}%")
            | User.email.ilike(f"%{query}%")
        )
    page = paginate(db, stmt.order_by(User.id), 50)
    return render_template("admin/users.html", page=page, query=query)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id: int):
    db = g.db
    user = db.get(User, user_id) or abort(404)
    if request.method == "POST":
        form = request.form
        role = form.get("role")
        if role not in ROLE_TITLES:
            abort(400)
        if user.id == g.user.id and role != "admin":
            flash("You can't remove your own administrator role.", "error")
            return redirect(url_for("admin.edit_user", user_id=user.id))
        if user.id == g.user.id and form.get("banned"):
            flash("You can't ban yourself.", "error")
            return redirect(url_for("admin.edit_user", user_id=user.id))
        password = form.get("password", "")
        if password and len(password) < MIN_PASSWORD:
            flash(f"Passwords must be at least {MIN_PASSWORD} characters.",
                  "error")
            return redirect(url_for("admin.edit_user", user_id=user.id))
        user.role = role
        user.title = form.get("title", "").strip()[:64] or None
        user.banned = bool(form.get("banned"))
        if password:
            user.password_hash = auth.hash_password(password)
        db.commit()
        flash("Member updated.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user.html", user=user, roles=ROLE_TITLES)
