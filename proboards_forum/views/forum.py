"""
Home page, boards, threads, posting, polls, shoutbox and search.
"""
from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, send_from_directory, url_for
)
from sqlalchemy import delete, func, or_, select

from .. import auth
from ..formatting import html_to_text, snippet
from ..helpers import (
    all_boards, board_stats, get_settings, online_users, paginate,
    post_counts, unread_thread_ids
)
from ..models import (
    Board, Category, Poll, PollOption, PollVote, Post, ShoutboxPost, Thread,
    ThreadRead, User, now
)


bp = Blueprint("forum", __name__)

MAX_TITLE = 255
MAX_POST = 50_000
MAX_SHOUT = 500
MAX_POLL_OPTIONS = 20


def get_board_or_404(board_id: int) -> Board:
    board = g.db.get(Board, board_id)
    if board is None or not auth.can_view_board(board):
        abort(404)
    return board


def get_thread_or_404(thread_id: int) -> Thread:
    thread = g.db.get(Thread, thread_id)
    if thread is None or not auth.can_view_board(thread.board):
        abort(404)
    return thread


def visible(boards: list[Board]) -> list[Board]:
    return [b for b in boards if auth.can_view_board(b)]


def thread_url(thread: Thread, **kwargs) -> str:
    from ..helpers import slugify
    return url_for(
        "forum.thread", thread_id=thread.id, slug=slugify(thread.title),
        **kwargs
    )


def post_url(post: Post) -> str:
    """URL of the thread page containing a post, anchored to the post."""
    per_page = get_settings(g.db)["posts_per_page"]
    position = g.db.scalar(
        select(func.count(Post.id)).where(
            Post.thread_id == post.thread_id, Post.id < post.id
        )
    )
    page = position // per_page + 1
    kwargs = {"page": page} if page > 1 else {}
    return thread_url(post.thread, **kwargs) + f"#post-{post.id}"


@bp.app_context_processor
def _urls():
    return {
        "thread_url": thread_url,
        "post_url": post_url,
        "can_moderate": auth.can_moderate,
        "can_reply": auth.can_reply,
        "can_edit_post": auth.can_edit_post,
    }


def mark_thread_read(thread: Thread) -> None:
    if g.user is None:
        return
    read = g.db.get(ThreadRead, (g.user.id, thread.id))
    if read is None:
        g.db.add(ThreadRead(user_id=g.user.id, thread_id=thread.id))
    else:
        read.read_at = now()


def validate_post_body(body: str) -> bool:
    if not body.strip():
        flash("Your message can't be empty.", "error")
        return False
    if len(body) > MAX_POST:
        flash(f"Your message is too long (max {MAX_POST} characters).",
              "error")
        return False
    return True


# --- Home ---------------------------------------------------------------

@bp.route("/")
def index():
    db = g.db
    categories = list(db.scalars(
        select(Category).order_by(Category.position, Category.id)
    ))
    sections = []
    top_level = []
    for category in categories:
        boards = visible(category.boards)
        if boards:
            sections.append((category, boards))
            top_level.extend(boards)
    stats = board_stats(db, top_level)

    settings = get_settings(db)
    shouts = []
    if settings["shoutbox_enabled"] == "1":
        shouts = list(reversed(db.scalars(
            select(ShoutboxPost)
            .order_by(ShoutboxPost.created_at.desc(), ShoutboxPost.id.desc())
            .limit(30)
        ).all()))

    info = {
        "total_posts": db.scalar(select(func.count(Post.id))),
        "total_threads": db.scalar(select(func.count(Thread.id))),
        "total_members": db.scalar(select(func.count(User.id))),
        "newest_member": db.scalar(
            select(User).order_by(User.date_registered.desc(),
                                  User.id.desc()).limit(1)
        ),
        "online": online_users(db),
        "most_recent_post": db.scalar(
            select(Post).join(Thread, Thread.id == Post.thread_id)
            .where(Thread.board_id.in_(visible_board_ids()))
            .order_by(Post.id.desc()).limit(1)
        ),
    }
    return render_template(
        "forum/index.html", sections=sections, stats=stats, shouts=shouts,
        info=info,
    )


@bp.route("/mark-read", methods=["POST"])
@auth.login_required
def mark_all_read():
    g.user.mark_read_at = now()
    g.db.execute(delete(ThreadRead).where(ThreadRead.user_id == g.user.id))
    g.db.commit()
    flash("All boards marked as read.", "success")
    return redirect(url_for("forum.index"))


# --- Boards -------------------------------------------------------------

@bp.route("/board/<int:board_id>")
@bp.route("/board/<int:board_id>/<slug>")
def board(board_id: int, slug: str = ""):
    db = g.db
    board = get_board_or_404(board_id)
    settings = get_settings(db)

    sub_boards = visible(board.sub_boards)
    stats = board_stats(db, sub_boards)

    # Announcements from any board appear at the top of every board.
    announcements = []
    page_number = request.args.get("page", "1")
    if page_number in ("", "1"):
        announcements = [
            t for t in db.scalars(
                select(Thread).where(Thread.announcement.is_(True))
                .order_by(Thread.last_post_at.desc())
            )
            if auth.can_view_board(t.board)
        ]

    stmt = (
        select(Thread)
        .where(Thread.board_id == board.id, Thread.announcement.is_(False))
        .order_by(Thread.sticky.desc(), Thread.last_post_at.desc(),
                  Thread.id.desc())
    )
    page = paginate(db, stmt, settings["threads_per_page"])
    threads = announcements + page.items
    thread_info = thread_list_info(threads)

    return render_template(
        "forum/board.html", board=board, sub_boards=sub_boards, stats=stats,
        announcements=announcements, page=page, thread_info=thread_info,
        can_start=auth.can_start_thread(board),
    )


def thread_list_info(threads: list[Thread]) -> dict:
    """Reply counts, last posts and unread flags for a list of threads."""
    db = g.db
    ids = [t.id for t in threads]
    info = {t.id: {"replies": 0, "last_post": None, "unread": False}
            for t in threads}
    if not ids:
        return info
    for thread_id, count, last_id in db.execute(
        select(Post.thread_id, func.count(Post.id), func.max(Post.id))
        .where(Post.thread_id.in_(ids)).group_by(Post.thread_id)
    ):
        info[thread_id]["replies"] = count - 1
        info[thread_id]["last_post_id"] = last_id
    last_ids = [i.get("last_post_id") for i in info.values()
                if i.get("last_post_id")]
    last_posts = {p.id: p for p in db.scalars(
        select(Post).where(Post.id.in_(last_ids))
    )}
    for thread_id in ids:
        info[thread_id]["last_post"] = last_posts.get(
            info[thread_id].get("last_post_id")
        )
    for thread_id in unread_thread_ids(db, threads):
        info[thread_id]["unread"] = True
    return info


# --- Threads ------------------------------------------------------------

@bp.route("/thread/<int:thread_id>")
@bp.route("/thread/<int:thread_id>/<slug>")
def thread(thread_id: int, slug: str = ""):
    db = g.db
    thread = get_thread_or_404(thread_id)
    settings = get_settings(db)

    stmt = (
        select(Post).where(Post.thread_id == thread.id)
        .order_by(Post.created_at, Post.id)
    )
    page = paginate(db, stmt, settings["posts_per_page"])
    counts = post_counts(db, [p.user_id for p in page.items])

    thread.views = (thread.views or 0) + 1
    mark_thread_read(thread)
    db.commit()

    voted_option = None
    has_voted = False
    if thread.poll and g.user:
        vote = db.get(PollVote, (thread.poll.id, g.user.id))
        if vote is not None:
            has_voted = True
            voted_option = vote.option_id

    return render_template(
        "forum/thread.html", thread=thread, page=page, counts=counts,
        has_voted=has_voted, voted_option=voted_option,
        moderator=auth.can_moderate(thread.board),
        boards=[b for b in all_boards(db) if auth.can_view_board(b)]
        if auth.can_moderate(thread.board) else [],
    )


@bp.route("/post/<int:post_id>")
def post(post_id: int):
    post = g.db.get(Post, post_id)
    if post is None or not auth.can_view_board(post.thread.board):
        abort(404)
    return redirect(post_url(post))


def poll_from_form() -> tuple[str, list[str]]:
    question = request.form.get("poll_question", "").strip()[:MAX_TITLE]
    options = [
        line.strip()[:MAX_TITLE]
        for line in request.form.get("poll_options", "").splitlines()
        if line.strip()
    ]
    return question, options[:MAX_POLL_OPTIONS]


@bp.route("/thread/new/<int:board_id>", methods=["GET", "POST"])
@auth.login_required
def new_thread(board_id: int):
    db = g.db
    board = get_board_or_404(board_id)
    if not auth.can_start_thread(board):
        abort(403)

    form = request.form
    if request.method == "POST":
        title = form.get("title", "").strip()
        body = form.get("body", "")
        question, options = poll_from_form()
        valid = True
        if not title or len(title) > MAX_TITLE:
            flash("Please enter a subject (up to 255 characters).", "error")
            valid = False
        if not validate_post_body(body):
            valid = False
        if question and len(options) < 2:
            flash("A poll needs at least two options.", "error")
            valid = False

        if valid and form.get("action") != "preview":
            timestamp = now()
            thread = Thread(
                board_id=board.id, user_id=g.user.id, title=title,
                created_at=timestamp, last_post_at=timestamp,
            )
            moderator = auth.can_moderate(board)
            if moderator:
                thread.sticky = bool(form.get("sticky"))
                thread.announcement = bool(form.get("announcement"))
                thread.locked = bool(form.get("locked"))
            db.add(thread)
            db.flush()
            db.add(Post(
                thread_id=thread.id, user_id=g.user.id, body=body,
                created_at=timestamp,
            ))
            if question:
                poll = Poll(id=thread.id, question=question)
                poll.options = [
                    PollOption(text=text, position=i)
                    for i, text in enumerate(options)
                ]
                db.add(poll)
            mark_thread_read(thread)
            db.commit()
            return redirect(thread_url(thread))

    return render_template(
        "forum/post_form.html", mode="thread", board=board, form=form,
        preview=form.get("body") if form.get("action") == "preview" else None,
        moderator=auth.can_moderate(board),
    )


@bp.route("/thread/<int:thread_id>/reply", methods=["GET", "POST"])
@auth.login_required
def reply(thread_id: int):
    db = g.db
    thread = get_thread_or_404(thread_id)
    if not auth.can_reply(thread):
        flash("This thread is locked.", "error")
        return redirect(thread_url(thread))

    form = request.form
    body = form.get("body", "")
    if request.method == "GET" and request.args.get("quote"):
        quoted = db.get(Post, request.args.get("quote", type=int) or 0)
        if quoted is not None and quoted.thread_id == thread.id:
            body = quote_text(quoted)

    if request.method == "POST" and validate_post_body(body) \
            and form.get("action") != "preview":
        timestamp = now()
        post = Post(
            thread_id=thread.id, user_id=g.user.id, body=body,
            created_at=timestamp,
        )
        db.add(post)
        thread.last_post_at = timestamp
        mark_thread_read(thread)
        db.commit()
        return redirect(post_url(post))

    recent = list(reversed(db.scalars(
        select(Post).where(Post.thread_id == thread.id)
        .order_by(Post.id.desc()).limit(5)
    ).all()))
    return render_template(
        "forum/post_form.html", mode="reply", thread=thread,
        board=thread.board, form={"body": body}, recent=recent,
        preview=body if form.get("action") == "preview" else None,
    )


def author_name(post: Post) -> str:
    if post.user is not None:
        return post.user.display_name
    return post.guest_name or "Guest"


def quote_text(post: Post) -> str:
    body = post.body
    if post.body_format == "html":
        body = html_to_text(body)
    name = author_name(post).replace("]", "")
    return f"[quote={name}]{body}[/quote]\n"


@bp.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_post(post_id: int):
    db = g.db
    post = db.get(Post, post_id)
    if post is None or not auth.can_view_board(post.thread.board):
        abort(404)
    if not auth.can_edit_post(post):
        abort(403)
    thread = post.thread
    first_post_id = db.scalar(
        select(func.min(Post.id)).where(Post.thread_id == thread.id)
    )
    is_first = post.id == first_post_id

    form = request.form
    if request.method == "POST":
        body = form.get("body", "")
        title = form.get("title", thread.title).strip()
        valid = validate_post_body(body)
        if is_first and (not title or len(title) > MAX_TITLE):
            flash("Please enter a subject (up to 255 characters).", "error")
            valid = False
        if valid and form.get("action") != "preview":
            if body != post.body or post.body_format != "bbcode":
                post.body = body
                post.body_format = "bbcode"
                post.edited_at = now()
                post.edited_by_id = g.user.id
            if is_first:
                thread.title = title
            db.commit()
            return redirect(post_url(post))
        values = {"body": body, "title": title}
    else:
        body = post.body
        if post.body_format == "html":
            body = html_to_text(body)
        values = {"body": body, "title": thread.title}

    return render_template(
        "forum/post_form.html", mode="edit", post=post, thread=thread,
        board=thread.board, form=values, is_first=is_first,
        preview=values["body"] if form.get("action") == "preview" else None,
    )


@bp.route("/post/<int:post_id>/delete", methods=["POST"])
@auth.login_required
def delete_post(post_id: int):
    db = g.db
    post = db.get(Post, post_id)
    if post is None or not auth.can_view_board(post.thread.board):
        abort(404)
    if not auth.can_edit_post(post):
        abort(403)
    thread = post.thread
    first_post_id = db.scalar(
        select(func.min(Post.id)).where(Post.thread_id == thread.id)
    )
    if post.id == first_post_id:
        # Deleting the opening post deletes the whole thread.
        if not auth.can_moderate(thread.board) and db.scalar(
            select(func.count(Post.id)).where(Post.thread_id == thread.id)
        ) > 1:
            flash("Only moderators can delete a thread that has replies.",
                  "error")
            return redirect(post_url(post))
        board = thread.board
        delete_thread(thread)
        db.commit()
        flash("Thread deleted.", "success")
        return redirect(url_for("forum.board", board_id=board.id))

    db.delete(post)
    db.flush()
    thread.last_post_at = db.scalar(
        select(func.max(Post.created_at)).where(Post.thread_id == thread.id)
    ) or thread.created_at
    db.commit()
    flash("Post deleted.", "success")
    return redirect(thread_url(thread))


def delete_thread(thread: Thread) -> None:
    db = g.db
    db.execute(delete(Post).where(Post.thread_id == thread.id))
    db.execute(delete(ThreadRead).where(ThreadRead.thread_id == thread.id))
    if thread.poll is not None:
        db.execute(delete(PollVote).where(PollVote.poll_id == thread.id))
    db.delete(thread)


@bp.route("/thread/<int:thread_id>/moderate", methods=["POST"])
@auth.login_required
def moderate_thread(thread_id: int):
    db = g.db
    thread = get_thread_or_404(thread_id)
    if not auth.can_moderate(thread.board):
        abort(403)

    action = request.form.get("action")
    toggles = {
        "lock": ("locked", True), "unlock": ("locked", False),
        "sticky": ("sticky", True), "unsticky": ("sticky", False),
        "announce": ("announcement", True),
        "unannounce": ("announcement", False),
    }
    if action in toggles:
        attr, value = toggles[action]
        setattr(thread, attr, value)
        flash("Thread updated.", "success")
    elif action == "move":
        target = db.get(Board, request.form.get("board_id", type=int) or 0)
        if target is None or not auth.can_view_board(target) \
                or not auth.can_moderate(target):
            abort(400)
        thread.board_id = target.id
        flash(f"Thread moved to {target.name}.", "success")
    elif action == "close_poll" and thread.poll:
        thread.poll.closed = True
    elif action == "open_poll" and thread.poll:
        thread.poll.closed = False
    elif action == "delete":
        board = thread.board
        delete_thread(thread)
        db.commit()
        flash("Thread deleted.", "success")
        return redirect(url_for("forum.board", board_id=board.id))
    else:
        abort(400)
    db.commit()
    return redirect(thread_url(thread))


@bp.route("/thread/<int:thread_id>/vote", methods=["POST"])
@auth.login_required
def vote(thread_id: int):
    db = g.db
    thread = get_thread_or_404(thread_id)
    poll = thread.poll
    if poll is None:
        abort(404)
    if poll.closed or thread.locked:
        flash("This poll is closed.", "error")
        return redirect(thread_url(thread))
    if db.get(PollVote, (poll.id, g.user.id)) is not None:
        flash("You have already voted in this poll.", "error")
        return redirect(thread_url(thread))
    option = db.get(PollOption, request.form.get("option", type=int) or 0)
    if option is None or option.poll_id != poll.id:
        flash("Please choose an option.", "error")
        return redirect(thread_url(thread))
    option.votes = (option.votes or 0) + 1
    db.add(PollVote(poll_id=poll.id, user_id=g.user.id, option_id=option.id))
    db.commit()
    return redirect(thread_url(thread))


# --- Shoutbox -----------------------------------------------------------

@bp.route("/shoutbox", methods=["POST"])
@auth.login_required
def shout():
    body = request.form.get("body", "").strip()
    if get_settings(g.db)["shoutbox_enabled"] != "1":
        abort(403)
    if body:
        g.db.add(ShoutboxPost(user_id=g.user.id, body=body[:MAX_SHOUT]))
        g.db.commit()
    return redirect(url_for("forum.index") + "#shoutbox")


@bp.route("/shoutbox/<int:shout_id>/delete", methods=["POST"])
@auth.login_required
def delete_shout(shout_id: int):
    shout = g.db.get(ShoutboxPost, shout_id)
    if shout is None:
        abort(404)
    if not (g.user.is_staff or shout.user_id == g.user.id):
        abort(403)
    g.db.delete(shout)
    g.db.commit()
    return redirect(url_for("forum.index") + "#shoutbox")


# --- Search & recent ----------------------------------------------------

def visible_board_ids() -> list[int]:
    return [b.id for b in all_boards(g.db) if auth.can_view_board(b)]


@bp.route("/search")
def search():
    db = g.db
    query = request.args.get("q", "").strip()
    scope = request.args.get("in", "posts")
    board_id = request.args.get("board", type=int)
    author = request.args.get("author", "").strip()
    board_ids = visible_board_ids()
    if board_id:
        board = db.get(Board, board_id)
        if board is not None and board.id in board_ids:
            board_ids = [i for i in board.descendant_ids() if i in board_ids]

    page = None
    if query or author:
        pattern = f"%{query}%"
        stmt = (
            select(Post).join(Thread, Thread.id == Post.thread_id)
            .where(Thread.board_id.in_(board_ids))
        )
        if query:
            if scope == "titles":
                stmt = stmt.where(Thread.title.ilike(pattern))
                # One result per thread: its opening post.
                first_ids = select(func.min(Post.id)).group_by(Post.thread_id)
                stmt = stmt.where(Post.id.in_(first_ids))
            else:
                stmt = stmt.where(or_(Post.body.ilike(pattern),
                                      Thread.title.ilike(pattern)))
        if author:
            stmt = stmt.join(User, User.id == Post.user_id).where(or_(
                User.display_name.ilike(author), User.username.ilike(author)
            ))
        stmt = stmt.order_by(Post.created_at.desc(), Post.id.desc())
        page = paginate(db, stmt, 20)

    boards = [b for b in all_boards(db) if b.id in visible_board_ids()]
    return render_template(
        "forum/search.html", query=query, scope=scope, author=author,
        board_id=board_id, boards=boards, page=page, snippet=snippet,
    )


@bp.route("/recent")
def recent():
    db = g.db
    stmt = (
        select(Thread).where(Thread.board_id.in_(visible_board_ids()))
        .order_by(Thread.last_post_at.desc(), Thread.id.desc())
    )
    page = paginate(db, stmt, get_settings(db)["threads_per_page"])
    return render_template(
        "forum/recent.html", page=page, thread_info=thread_list_info(
            page.items
        ),
    )


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"}


@bp.route("/uploads/<path:filename>")
def uploads(filename: str):
    # Only serve images; anything else (e.g. SVG or HTML) could run scripts.
    if not any(filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
        abort(404)
    response = send_from_directory(
        current_app.config["UPLOAD_FOLDER"], filename
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
