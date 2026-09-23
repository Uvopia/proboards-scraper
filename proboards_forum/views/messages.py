"""
Private conversations between members.
"""
from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for
)
from sqlalchemy import func, select

from .. import auth
from ..helpers import paginate
from ..models import (
    Conversation, ConversationParticipant, Message, User, now
)
from .forum import MAX_POST, MAX_TITLE


bp = Blueprint("messages", __name__)

MAX_RECIPIENTS = 10


def get_participation(conversation_id: int) -> ConversationParticipant:
    participant = g.db.get(
        ConversationParticipant, (conversation_id, g.user.id)
    )
    if participant is None or participant.left:
        abort(404)
    return participant


@bp.route("/conversations")
@auth.login_required
def inbox():
    db = g.db
    stmt = (
        select(Conversation, ConversationParticipant.last_read_at)
        .join(ConversationParticipant,
              ConversationParticipant.conversation_id == Conversation.id)
        .where(ConversationParticipant.user_id == g.user.id,
               ConversationParticipant.left.is_(False))
        .order_by(Conversation.last_message_at.desc())
    )
    page = paginate(db, stmt, 20, scalars=False)
    return render_template("messages/inbox.html", page=page)


@bp.route("/conversations/new", methods=["GET", "POST"])
@auth.login_required
def new():
    db = g.db
    form = request.form
    to = request.values.get("to", "")
    if request.method == "POST":
        subject = form.get("subject", "").strip()
        body = form.get("body", "")
        names = [n.strip() for n in to.split(",") if n.strip()]
        recipients, errors = [], []
        for name in names[:MAX_RECIPIENTS]:
            user = db.scalar(select(User).where(
                (func.lower(User.username) == name.lower())
                | (func.lower(User.display_name) == name.lower())
            ).limit(1))
            if user is None:
                errors.append(f"No member named “{name}”.")
            elif user.id != g.user.id and user not in recipients:
                recipients.append(user)
        if not recipients and not errors:
            errors.append("Please enter at least one recipient.")
        if not subject or len(subject) > MAX_TITLE:
            errors.append("Please enter a subject.")
        if not body.strip() or len(body) > MAX_POST:
            errors.append("Please enter a message.")

        if not errors:
            timestamp = now()
            conversation = Conversation(
                subject=subject, created_at=timestamp,
                last_message_at=timestamp,
            )
            conversation.participants = [
                ConversationParticipant(user_id=g.user.id,
                                        last_read_at=timestamp)
            ] + [
                ConversationParticipant(user_id=user.id)
                for user in recipients
            ]
            conversation.messages = [Message(
                user_id=g.user.id, body=body, created_at=timestamp
            )]
            db.add(conversation)
            db.commit()
            return redirect(url_for("messages.view",
                                    conversation_id=conversation.id))
        for error in errors:
            flash(error, "error")

    return render_template("messages/new.html", form=form, to=to)


@bp.route("/conversations/<int:conversation_id>", methods=["GET", "POST"])
@auth.login_required
def view(conversation_id: int):
    db = g.db
    participant = get_participation(conversation_id)
    conversation = db.get(Conversation, conversation_id)

    if request.method == "POST":
        body = request.form.get("body", "")
        if body.strip() and len(body) <= MAX_POST:
            timestamp = now()
            db.add(Message(
                conversation_id=conversation.id, user_id=g.user.id,
                body=body, created_at=timestamp,
            ))
            conversation.last_message_at = timestamp
            # Replying brings the conversation back for anyone who left.
            for other in conversation.participants:
                other.left = False
            participant.last_read_at = timestamp
            db.commit()
            return redirect(url_for("messages.view",
                                    conversation_id=conversation.id)
                            + "#latest")
        flash("Please enter a message.", "error")

    participant.last_read_at = now()
    db.commit()
    return render_template(
        "messages/view.html", conversation=conversation,
        others=[p.user for p in conversation.participants
                if p.user_id != g.user.id],
    )


@bp.route("/conversations/<int:conversation_id>/leave", methods=["POST"])
@auth.login_required
def leave(conversation_id: int):
    participant = get_participation(conversation_id)
    participant.left = True
    g.db.commit()
    flash("Conversation removed from your inbox.", "success")
    return redirect(url_for("messages.inbox"))
