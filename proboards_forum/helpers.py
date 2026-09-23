"""
Shared helpers: settings, pagination, template filters and board statistics.
"""
import datetime
import math
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from flask import g, request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import can_view_board
from .models import (
    Board, ConversationParticipant, Conversation, Post, Setting, Thread,
    ThreadRead, User, now
)


DEFAULT_SETTINGS = {
    "forum_name": "My Forum",
    "forum_description": "Welcome to the forum!",
    "announcement": "",
    "threads_per_page": "20",
    "posts_per_page": "15",
    "members_per_page": "30",
    "shoutbox_enabled": "1",
    "registration_open": "1",
    "theme_color": "#2c4a7a",
}
INT_SETTINGS = {"threads_per_page", "posts_per_page", "members_per_page"}
ONLINE_WINDOW = 15 * 60


def ensure_default_settings(db: Session) -> None:
    existing = set(db.scalars(select(Setting.key)))
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=value))
    db.commit()


def get_settings(db: Session) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    settings.update({s.key: s.value for s in db.scalars(select(Setting))})
    for key in INT_SETTINGS:
        try:
            settings[key] = max(1, int(settings[key]))
        except (TypeError, ValueError):
            settings[key] = int(DEFAULT_SETTINGS[key])
    return settings


def set_setting(db: Session, key: str, value: str) -> None:
    setting = db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or "untitled"


def is_safe_redirect(target: Optional[str]) -> bool:
    """Only allow redirects back into this site."""
    if not target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and target.startswith("/") \
        and not target.startswith("//") and "\\" not in target


@dataclass
class Page:
    """A page of results plus what's needed to render page links."""
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def links(self) -> list[Optional[int]]:
        """Page numbers to link, with None marking a gap."""
        shown = {1, self.pages} | set(range(self.page - 2, self.page + 3))
        result, last = [], 0
        for number in sorted(n for n in shown if 1 <= n <= self.pages):
            if number - last > 1:
                result.append(None)
            result.append(number)
            last = number
        return result


def current_page() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


def paginate(db: Session, stmt, per_page: int, page: Optional[int] = None,
             scalars: bool = True) -> Page:
    page = page or current_page()
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    result = db.execute(stmt.limit(per_page).offset((page - 1) * per_page))
    items = list(result.scalars() if scalars else result)
    return Page(items=items, page=page, per_page=per_page, total=total)


def format_date(timestamp: Optional[int], with_time: bool = True) -> str:
    """ProBoards-style relative dates: "Today at 3:15pm", "Mar 4, 2021"."""
    if not timestamp:
        return ""
    dt = datetime.datetime.fromtimestamp(timestamp)
    today = datetime.date.today()
    clock = dt.strftime("%-I:%M%p").lower()
    if dt.date() == today:
        return f"Today at {clock}" if with_time else "Today"
    if dt.date() == today - datetime.timedelta(days=1):
        return f"Yesterday at {clock}" if with_time else "Yesterday"
    if dt.year == today.year:
        day = dt.strftime("%b %-d")
    else:
        day = dt.strftime("%b %-d, %Y")
    return f"{day} at {clock}" if with_time else day


def iso_date(timestamp: Optional[int]) -> str:
    if not timestamp:
        return ""
    return datetime.datetime.fromtimestamp(
        timestamp, tz=datetime.timezone.utc
    ).isoformat()


# --- Statistics ---------------------------------------------------------

@dataclass
class BoardStats:
    threads: int = 0
    posts: int = 0
    last_post: Optional[Post] = None
    unread: bool = False


def all_boards(db: Session) -> list[Board]:
    return list(db.scalars(select(Board)))


def board_stats(db: Session, boards: list[Board]) -> dict[int, BoardStats]:
    """
    Thread/post counts and latest post for each board, rolled up so a
    board's figures include those of its sub-boards (as on ProBoards).
    """
    board_ids = set()
    for board in boards:
        board_ids.update(board.descendant_ids())
    if not board_ids:
        return {}

    own = {board_id: BoardStats() for board_id in board_ids}
    for board_id, count in db.execute(
        select(Thread.board_id, func.count(Thread.id))
        .where(Thread.board_id.in_(board_ids)).group_by(Thread.board_id)
    ):
        own[board_id].threads = count
    for board_id, count in db.execute(
        select(Thread.board_id, func.count(Post.id))
        .join(Post, Post.thread_id == Thread.id)
        .where(Thread.board_id.in_(board_ids)).group_by(Thread.board_id)
    ):
        own[board_id].posts = count

    # Latest post per board.
    latest = (
        select(Thread.board_id, func.max(Post.id).label("post_id"))
        .join(Post, Post.thread_id == Thread.id)
        .where(Thread.board_id.in_(board_ids)).group_by(Thread.board_id)
        .subquery()
    )
    last_posts = {
        board_id: post
        for board_id, post in db.execute(
            select(latest.c.board_id, Post)
            .join(Post, Post.id == latest.c.post_id)
        )
    }
    for board_id, post in last_posts.items():
        own[board_id].last_post = post

    unread_boards = set()
    if g.get("user") is not None:
        read = (
            select(ThreadRead.thread_id, ThreadRead.read_at)
            .where(ThreadRead.user_id == g.user.id).subquery()
        )
        unread_boards = set(db.scalars(
            select(Thread.board_id).distinct()
            .outerjoin(read, read.c.thread_id == Thread.id)
            .where(
                Thread.board_id.in_(board_ids),
                Thread.last_post_at > g.user.mark_read_at,
                (read.c.read_at.is_(None))
                | (Thread.last_post_at > read.c.read_at),
            )
        ))

    board_map = {b.id: b for b in db.scalars(
        select(Board).where(Board.id.in_(board_ids))
    )}

    def rollup(board_id: int) -> BoardStats:
        stats = own[board_id]
        total = BoardStats(
            stats.threads, stats.posts, stats.last_post,
            board_id in unread_boards,
        )
        for sub in board_map[board_id].sub_boards:
            # Hidden sub-boards mustn't leak their threads into totals.
            if not can_view_board(sub):
                continue
            sub_stats = rollup(sub.id)
            total.threads += sub_stats.threads
            total.posts += sub_stats.posts
            total.unread = total.unread or sub_stats.unread
            if sub_stats.last_post and (
                total.last_post is None
                or sub_stats.last_post.created_at > total.last_post.created_at
            ):
                total.last_post = sub_stats.last_post
        return total

    return {board.id: rollup(board.id) for board in boards}


def post_counts(db: Session, user_ids) -> dict[int, int]:
    """Posts per user, including posts made before an import."""
    user_ids = [uid for uid in set(user_ids) if uid is not None]
    if not user_ids:
        return {}
    counts = dict(db.execute(
        select(Post.user_id, func.count(Post.id))
        .where(Post.user_id.in_(user_ids)).group_by(Post.user_id)
    ).all())
    legacy = dict(db.execute(
        select(User.id, User.legacy_post_count).where(User.id.in_(user_ids))
    ).all())
    return {
        uid: max(counts.get(uid, 0), legacy.get(uid) or 0)
        for uid in user_ids
    }


def online_users(db: Session) -> list[User]:
    return list(db.scalars(
        select(User).where(User.last_active >= now() - ONLINE_WINDOW)
        .order_by(User.display_name)
    ))


def unread_thread_ids(db: Session, threads: list[Thread]) -> set[int]:
    if g.get("user") is None or not threads:
        return set()
    read = dict(db.execute(
        select(ThreadRead.thread_id, ThreadRead.read_at).where(
            ThreadRead.user_id == g.user.id,
            ThreadRead.thread_id.in_([t.id for t in threads]),
        )
    ).all())
    return {
        t.id for t in threads
        if t.last_post_at > g.user.mark_read_at
        and t.last_post_at > read.get(t.id, 0)
    }


def unread_conversation_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ConversationParticipant)
        .join(Conversation,
              Conversation.id == ConversationParticipant.conversation_id)
        .where(
            ConversationParticipant.user_id == user.id,
            ConversationParticipant.left.is_(False),
            Conversation.last_message_at
            > ConversationParticipant.last_read_at,
        )
    ) or 0


def init_app(app) -> None:
    app.jinja_env.filters["date"] = format_date
    app.jinja_env.filters["isodate"] = iso_date
    app.jinja_env.filters["slug"] = slugify

    @app.context_processor
    def _inject():
        db = g.get("db")
        if db is None:
            return {}
        user = g.get("user")
        return {
            "settings": get_settings(db),
            "current_user": user,
            "unread_messages": (
                unread_conversation_count(db, user) if user else 0
            ),
        }
