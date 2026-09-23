"""
Database models for the forum.

The schema mirrors the structure of a ProBoards v4.5 forum: categories hold
boards, boards hold sub-boards and threads, threads hold posts (and
optionally a poll). Members can chat in the shoutbox and hold private
conversations with one another.
"""
import time
from typing import Optional

from sqlalchemy import (
    Boolean, ForeignKey, Integer, String, Text, UniqueConstraint,
    create_engine, event
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, scoped_session,
    sessionmaker
)


def now() -> int:
    """Current time as a Unix timestamp."""
    return int(time.time())


class Base(DeclarativeBase):
    pass


# Role hierarchy; higher numbers imply more privileges.
ROLE_MEMBER = "member"
ROLE_GMOD = "gmod"
ROLE_ADMIN = "admin"
ROLE_LEVELS = {ROLE_MEMBER: 0, ROLE_GMOD: 1, ROLE_ADMIN: 2}
ROLE_TITLES = {
    ROLE_MEMBER: "Member",
    ROLE_GMOD: "Global Moderator",
    ROLE_ADMIN: "Administrator",
}


class Setting(Base):
    """Key/value store for forum-wide settings."""
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    # Imported members have no password until an admin sets one.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_MEMBER)
    # Custom rank/group title shown under the name (e.g., imported groups).
    title: Mapped[Optional[str]] = mapped_column(String(64))
    banned: Mapped[bool] = mapped_column(Boolean, default=False)

    date_registered: Mapped[int] = mapped_column(Integer, default=now)
    last_active: Mapped[Optional[int]] = mapped_column(Integer)
    # Threads whose last post predates this are considered read.
    mark_read_at: Mapped[int] = mapped_column(Integer, default=now)

    avatar_url: Mapped[Optional[str]] = mapped_column(String(512))
    signature: Mapped[Optional[str]] = mapped_column(Text)
    # "bbcode", or "html" for signatures imported from ProBoards.
    signature_format: Mapped[str] = mapped_column(String(8), default="bbcode")
    status: Mapped[Optional[str]] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(128))
    website: Mapped[Optional[str]] = mapped_column(String(128))
    website_url: Mapped[Optional[str]] = mapped_column(String(512))
    birthdate: Mapped[Optional[str]] = mapped_column(String(32))
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    instant_messengers: Mapped[Optional[str]] = mapped_column(String(512))
    # Posts made before import that aren't in the database.
    legacy_post_count: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def role_title(self) -> str:
        return self.title or ROLE_TITLES.get(self.role, "Member")

    def has_role(self, role: str) -> bool:
        return ROLE_LEVELS.get(self.role, 0) >= ROLE_LEVELS[role]

    @property
    def is_admin(self) -> bool:
        return self.has_role(ROLE_ADMIN)

    @property
    def is_staff(self) -> bool:
        return self.has_role(ROLE_GMOD)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Top-level boards only; sub-boards hang off their parent board.
    boards: Mapped[list["Board"]] = relationship(
        primaryjoin="and_(Category.id == Board.category_id, "
                    "Board.parent_id.is_(None))",
        order_by="Board.position, Board.id",
        viewonly=True,
    )


class Board(Base):
    __tablename__ = "board"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("board.id"))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Only staff can see/post in a staff-only board.
    staff_only: Mapped[bool] = mapped_column(Boolean, default=False)
    # Only staff can start threads in a read-only board.
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped[Category] = relationship()
    parent: Mapped[Optional["Board"]] = relationship(
        remote_side=[id], back_populates="sub_boards"
    )
    sub_boards: Mapped[list["Board"]] = relationship(
        back_populates="parent", order_by="Board.position, Board.id"
    )
    moderators: Mapped[list[User]] = relationship(
        secondary="moderator", order_by="User.display_name"
    )

    def ancestors(self) -> list["Board"]:
        """Parent boards, from the top-level board down to the parent."""
        chain = []
        board = self.parent
        while board is not None:
            chain.insert(0, board)
            board = board.parent
        return chain

    def descendant_ids(self) -> list[int]:
        ids = [self.id]
        for sub in self.sub_boards:
            ids.extend(sub.descendant_ids())
        return ids


class Moderator(Base):
    __tablename__ = "moderator"

    board_id: Mapped[int] = mapped_column(
        ForeignKey("board.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )


class Thread(Base):
    __tablename__ = "thread"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("board.id"), index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    # Denormalized for fast sorting of thread lists.
    last_post_at: Mapped[int] = mapped_column(
        Integer, default=now, index=True
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    sticky: Mapped[bool] = mapped_column(Boolean, default=False)
    announcement: Mapped[bool] = mapped_column(Boolean, default=False)
    views: Mapped[int] = mapped_column(Integer, default=0)

    board: Mapped[Board] = relationship()
    user: Mapped[Optional[User]] = relationship()
    poll: Mapped[Optional["Poll"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class Post(Base):
    __tablename__ = "post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("thread.id", ondelete="CASCADE"), index=True
    )
    # Null for guests and deleted users; guest_name is shown instead.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), index=True
    )
    guest_name: Mapped[Optional[str]] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    # "bbcode" for posts written here, "html" for imported ProBoards posts.
    body_format: Mapped[str] = mapped_column(String(8), default="bbcode")
    created_at: Mapped[int] = mapped_column(Integer, default=now, index=True)
    edited_at: Mapped[Optional[int]] = mapped_column(Integer)
    edited_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id")
    )

    thread: Mapped[Thread] = relationship()
    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])
    edited_by: Mapped[Optional[User]] = relationship(
        foreign_keys=[edited_by_id]
    )


class ThreadRead(Base):
    """When a member last read a thread, for "new posts" indicators."""
    __tablename__ = "thread_read"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("thread.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[int] = mapped_column(Integer, default=now)


class Poll(Base):
    __tablename__ = "poll"

    id: Mapped[int] = mapped_column(
        ForeignKey("thread.id", ondelete="CASCADE"), primary_key=True
    )
    question: Mapped[str] = mapped_column(String(255))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)

    thread: Mapped[Thread] = relationship(back_populates="poll")
    options: Mapped[list["PollOption"]] = relationship(
        order_by="PollOption.position, PollOption.id",
        cascade="all, delete-orphan",
    )

    @property
    def total_votes(self) -> int:
        return sum(option.votes for option in self.options)


class PollOption(Base):
    __tablename__ = "poll_option"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        ForeignKey("poll.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Imported polls only carry vote totals, so votes are stored as a count
    # rather than derived from PollVote rows.
    votes: Mapped[int] = mapped_column(Integer, default=0)


class PollVote(Base):
    __tablename__ = "poll_vote"
    __table_args__ = (UniqueConstraint("poll_id", "user_id"),)

    poll_id: Mapped[int] = mapped_column(
        ForeignKey("poll.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    # Null for imported votes, where the chosen option is unknown.
    option_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("poll_option.id", ondelete="SET NULL")
    )


class ShoutboxPost(Base):
    __tablename__ = "shoutbox_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"))
    body: Mapped[str] = mapped_column(Text)
    body_format: Mapped[str] = mapped_column(String(8), default="bbcode")
    created_at: Mapped[int] = mapped_column(Integer, default=now, index=True)

    user: Mapped[Optional[User]] = relationship()


class Conversation(Base):
    """A private conversation between two or more members."""
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    last_message_at: Mapped[int] = mapped_column(Integer, default=now)

    participants: Mapped[list["ConversationParticipant"]] = relationship(
        cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        order_by="Message.created_at, Message.id",
        cascade="all, delete-orphan",
    )


class ConversationParticipant(Base):
    __tablename__ = "conversation_participant"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_at: Mapped[int] = mapped_column(Integer, default=0)
    # A participant who leaves no longer sees the conversation.
    left: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship()


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, default=now)

    user: Mapped[User] = relationship()


def make_session_factory(database_uri: str) -> scoped_session:
    """Create the engine/tables and return a thread-local session factory."""
    engine = create_engine(database_uri)

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return scoped_session(sessionmaker(engine, expire_on_commit=False))
