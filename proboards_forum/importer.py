"""
Import a forum scraped with ``pbs`` into a new forum.

The scraper stores everything in a SQLite database (``forum.db``) alongside
an ``images`` directory. Original ProBoards ids are kept for users, boards,
threads and posts, so the forum structure (and post links) carry over.
Imported members have no password; an administrator sets one with
``pbf set-password`` or from the admin panel.
"""
import logging
import pathlib
import re
import shutil
import sqlite3
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ROLE_ADMIN, ROLE_GMOD, ROLE_MEMBER, Board, Category, Moderator, Poll,
    PollOption, PollVote, Post, ShoutboxPost, Thread, User
)


logger = logging.getLogger(__name__)

ADMIN_GROUPS = re.compile(r"admin", re.IGNORECASE)
GMOD_GROUPS = re.compile(r"global mod", re.IGNORECASE)
SAFE_URL = re.compile(r"^https?://", re.IGNORECASE)


class ForumImportError(Exception):
    pass


def _rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return []
    return conn.execute(f'SELECT * FROM "{table}"').fetchall()


def _role(group: Optional[str]) -> str:
    if group and ADMIN_GROUPS.search(group):
        return ROLE_ADMIN
    if group and GMOD_GROUPS.search(group):
        return ROLE_GMOD
    return ROLE_MEMBER


def _safe_url(url: Optional[str]) -> Optional[str]:
    return url if url and SAFE_URL.match(url) else None


def import_scraped_forum(
    db: Session, source_dir: str, upload_folder: str
) -> dict:
    """
    Import a scraped forum into an empty forum database.

    Args:
        db: Session for the (empty) forum database.
        source_dir: Directory produced by ``pbs`` (contains ``forum.db``
            and ``images/``), or the path to the database file itself.
        upload_folder: The forum's upload folder; avatars are copied here.

    Returns:
        Counts of imported items, keyed by type.
    """
    source = pathlib.Path(source_dir)
    db_path = source / "forum.db" if source.is_dir() else source
    image_dir = db_path.parent / "images"
    if not db_path.exists():
        raise ForumImportError(f"No scraped database found at {db_path}")

    if db.scalar(select(func.count(User.id))) or \
            db.scalar(select(func.count(Board.id))):
        raise ForumImportError(
            "The forum already has members or boards. Import into a new, "
            "empty forum instance instead."
        )

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    counts = {}

    # --- Users -------------------------------------------------------
    images = {row["id"]: row for row in _rows(conn, "image")}
    avatars = {row["user_id"]: images.get(row["image_id"])
               for row in _rows(conn, "avatar")}
    avatar_dir = pathlib.Path(upload_folder) / "imported"

    guest_names = {}
    taken = set()
    users = 0
    for row in _rows(conn, "user"):
        if row["id"] is None:
            continue
        if row["id"] < 0:
            guest_names[row["id"]] = row["name"] or "Guest"
            continue

        username = (row["username"] or row["name"] or f"user{row['id']}")
        username = username.strip()[:64] or f"user{row['id']}"
        if username.lower() in taken:
            username = f"{username[:50]}-{row['id']}"
        taken.add(username.lower())

        avatar_url = None
        image = avatars.get(row["id"])
        if image is not None:
            # Never trust paths from the database; keep just the name.
            filename = pathlib.Path(image["filename"] or "").name
            if filename and (image_dir / filename).is_file():
                avatar_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image_dir / filename, avatar_dir / filename)
                avatar_url = f"/uploads/imported/{filename}"
            else:
                avatar_url = _safe_url(image["url"])

        db.add(User(
            id=row["id"],
            username=username,
            display_name=(row["name"] or username)[:64],
            email=row["email"],
            role=_role(row["group"]),
            title=row["group"],
            date_registered=row["date_registered"] or 0,
            last_active=row["last_online"],
            mark_read_at=0,
            avatar_url=avatar_url,
            signature=row["signature"],
            signature_format="html",
            status=row["latest_status"],
            location=row["location"],
            website=row["website"],
            website_url=_safe_url(row["website_url"]),
            birthdate=row["birthdate"],
            gender=row["gender"],
            instant_messengers=row["instant_messengers"],
            legacy_post_count=row["post_count"] or 0,
        ))
        users += 1
    db.flush()
    counts["users"] = users

    def member(user_id: Optional[int]) -> Optional[int]:
        return user_id if user_id is not None and user_id > 0 else None

    # --- Categories & boards ------------------------------------------
    category_ids = set()
    for position, row in enumerate(_rows(conn, "category")):
        db.add(Category(id=row["id"], name=row["name"], position=position))
        category_ids.add(row["id"])
    counts["categories"] = len(category_ids)

    board_rows = {row["id"]: row for row in _rows(conn, "board")}

    def board_category(board_id: int, depth: int = 0) -> Optional[int]:
        row = board_rows[board_id]
        if row["category_id"] in category_ids:
            return row["category_id"]
        if row["parent_id"] in board_rows and depth < 50:
            return board_category(row["parent_id"], depth + 1)
        return None

    # Parents must be inserted before their sub-boards.
    ordered, seen = [], set()

    def visit(board_id: int, depth: int = 0) -> None:
        if board_id in seen or depth > 50:
            return
        parent_id = board_rows[board_id]["parent_id"]
        if parent_id in board_rows:
            visit(parent_id, depth + 1)
        seen.add(board_id)
        ordered.append(board_rows[board_id])

    for board_id in board_rows:
        visit(board_id)

    fallback_category = None
    for position, row in enumerate(ordered):
        category_id = board_category(row["id"])
        if category_id is None:
            if fallback_category is None:
                fallback_category = Category(name="Imported", position=999)
                db.add(fallback_category)
                db.flush()
            category_id = fallback_category.id
        db.add(Board(
            id=row["id"],
            category_id=category_id,
            parent_id=row["parent_id"]
            if row["parent_id"] in board_rows else None,
            name=row["name"],
            description=row["description"],
            position=position,
            # Password-protected boards were private; keep them staff-only.
            staff_only=bool(row["password_protected"]),
        ))
    db.flush()
    counts["boards"] = len(board_rows)

    user_ids = set(db.scalars(select(User.id)))
    for row in _rows(conn, "moderator"):
        if row["user_id"] in user_ids and row["board_id"] in board_rows:
            db.add(Moderator(board_id=row["board_id"], user_id=row["user_id"]))

    # --- Threads & posts -----------------------------------------------
    post_rows = _rows(conn, "post")
    thread_dates = {}
    for row in post_rows:
        dates = thread_dates.setdefault(row["thread_id"], [])
        if row["date"]:
            dates.append(row["date"])

    thread_ids = set()
    for row in _rows(conn, "thread"):
        if row["board_id"] not in board_rows:
            continue
        dates = thread_dates.get(row["id"]) or [0]
        db.add(Thread(
            id=row["id"],
            board_id=row["board_id"],
            user_id=member(row["user_id"]),
            title=row["title"] or "(untitled)",
            created_at=min(dates),
            last_post_at=max(dates),
            locked=bool(row["locked"]),
            sticky=bool(row["sticky"]),
            announcement=bool(row["announcement"]),
            views=row["views"] or 0,
        ))
        thread_ids.add(row["id"])
    db.flush()
    counts["threads"] = len(thread_ids)

    posts = 0
    for row in post_rows:
        if row["thread_id"] not in thread_ids:
            continue
        user_id = member(row["user_id"])
        if user_id is not None and user_id not in user_ids:
            user_id = None
        db.add(Post(
            id=row["id"],
            thread_id=row["thread_id"],
            user_id=user_id,
            guest_name=guest_names.get(row["user_id"])
            if user_id is None else None,
            body=row["message"] or "",
            body_format="html",
            created_at=row["date"] or 0,
            edited_at=row["last_edited"],
            edited_by_id=member(row["edit_user_id"])
            if member(row["edit_user_id"]) in user_ids else None,
        ))
        posts += 1
        if posts % 5000 == 0:
            db.flush()
    db.flush()
    counts["posts"] = posts

    # --- Polls ---------------------------------------------------------
    polls = 0
    options_by_poll = {}
    for row in _rows(conn, "poll_option"):
        options_by_poll.setdefault(row["poll_id"], []).append(row)
    for row in _rows(conn, "poll"):
        if row["id"] not in thread_ids:
            continue
        poll = Poll(id=row["id"], question=row["name"] or "Poll")
        poll.options = [
            PollOption(id=opt["id"], text=opt["name"] or "", position=i,
                       votes=opt["votes"] or 0)
            for i, opt in enumerate(options_by_poll.get(row["id"], []))
        ]
        db.add(poll)
        polls += 1
    db.flush()
    poll_ids = set(db.scalars(select(Poll.id)))
    for row in _rows(conn, "poll_voter"):
        if row["poll_id"] in poll_ids and row["user_id"] in user_ids:
            # Only who voted is known, not which option they chose.
            db.add(PollVote(poll_id=row["poll_id"], user_id=row["user_id"]))
    counts["polls"] = polls

    # --- Shoutbox ------------------------------------------------------
    shouts = 0
    for row in _rows(conn, "shoutbox_post"):
        db.add(ShoutboxPost(
            id=row["id"],
            user_id=row["user_id"] if row["user_id"] in user_ids else None,
            body=row["message"] or "",
            body_format="html",
            created_at=row["date"] or 0,
        ))
        shouts += 1
    counts["shoutbox_posts"] = shouts

    db.commit()
    conn.close()
    return counts
