import importlib.util
import pathlib
import re

import pytest
import sqlalchemy
import sqlalchemy.orm
from sqlalchemy import select

from proboards_forum import create_app
from proboards_forum.formatting import bbcode_to_html, render
from proboards_forum.importer import import_scraped_forum
from proboards_forum.models import (
    Board, Category, Poll, Post, Thread, User
)


REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "instance"), {"TESTING": True})


def db(app):
    return app.extensions["db"]()


class Browser:
    """Test client that tracks the CSRF token like a real browser."""

    def __init__(self, app):
        self.client = app.test_client()

    def token(self):
        with self.client.session_transaction() as session:
            if "csrf_token" not in session:
                session["csrf_token"] = "test-token"
            return session["csrf_token"]

    def get(self, url, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url, data=None, **kwargs):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        return self.client.post(url, data=data, **kwargs)

    def register(self, username, password="password123"):
        return self.post("/register", {
            "username": username, "email": f"{username}@example.com",
            "password": password, "confirm": password,
        })

    def login(self, username, password="password123"):
        return self.post("/login", {
            "username": username, "password": password,
        })

    def logout(self):
        return self.post("/logout")


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture
def forum(app):
    """A forum with an admin, a member, a category and a board."""
    admin = Browser(app)
    admin.register("admin")
    admin.post("/admin/category", {"name": "General"})
    category = db(app).scalar(select(Category))
    admin.post("/admin/board/new", {
        "name": "Chit Chat", "description": "Talk here",
        "category_id": category.id,
    })
    board = db(app).scalar(select(Board))
    member = Browser(app)
    member.register("bob")
    return admin, member, board


def create_thread(browser, board, title="Hello", body="First post", **extra):
    data = {"title": title, "body": body, "action": "post", **extra}
    return browser.post(f"/thread/new/{board.id}", data)


# --- Accounts -------------------------------------------------------------

def test_first_member_is_admin(app, forum):
    users = {u.username: u for u in db(app).scalars(select(User))}
    assert users["admin"].is_admin
    assert not users["bob"].is_staff


def test_login_and_logout(app, forum):
    _, member, _ = forum
    member.logout()
    assert "Welcome, Guest" in text(member.get("/"))
    response = member.login("bob", "wrong-password")
    assert "Invalid username or password" in text(response)
    response = member.login("bob")
    assert response.status_code == 302
    assert "Welcome back" in text(member.get("/"))


def test_login_rejects_offsite_redirect(app, forum):
    _, member, _ = forum
    member.logout()
    response = member.post("/login?next=//evil.example", {
        "username": "bob", "password": "password123",
        "next": "https://evil.example",
    })
    assert response.headers["Location"] == "/"


def test_duplicate_username_rejected(app, forum):
    other = Browser(app)
    other.register("BOB")
    assert db(app).scalar(
        select(sqlalchemy.func.count(User.id))
    ) == 2


def test_post_without_csrf_token_is_rejected(app, forum):
    _, member, board = forum
    response = member.client.post(f"/thread/new/{board.id}", data={
        "title": "x", "body": "y",
    })
    assert response.status_code == 400
    assert db(app).scalar(select(Thread)) is None


def test_banned_member_is_logged_out(app, forum):
    admin, member, _ = forum
    bob = db(app).scalar(select(User).where(User.username == "bob"))
    admin.post(f"/admin/users/{bob.id}", {"role": "member", "banned": "1"})
    assert "Welcome, Guest" in text(member.get("/"))


# --- Boards, threads & posts ---------------------------------------------

def test_create_thread_and_reply(app, forum):
    admin, member, board = forum
    response = create_thread(member, board, "My first thread", "[b]Hi[/b]")
    assert response.status_code == 302
    thread = db(app).scalar(select(Thread))
    page = text(member.get(response.headers["Location"]))
    assert "My first thread" in page
    assert "<strong>Hi</strong>" in page

    admin.post(f"/thread/{thread.id}/reply", {"body": "Welcome!"})
    page = text(member.get(f"/thread/{thread.id}"))
    assert "Welcome!" in page
    assert "Re: My first thread" in page

    home = text(member.get("/"))
    assert "Chit Chat" in home
    assert "2 posts in 1 threads" in home


def test_board_lists_threads_with_stickies_first(app, forum):
    admin, member, board = forum
    create_thread(member, board, "Ordinary thread")
    create_thread(admin, board, "Pinned thread", sticky="1")
    page = text(member.get(f"/board/{board.id}"))
    assert page.index("Pinned thread") < page.index("Ordinary thread")


def test_thread_pagination(app, forum):
    admin, member, board = forum
    create_thread(member, board)
    thread = db(app).scalar(select(Thread))
    for i in range(20):
        member.post(f"/thread/{thread.id}/reply", {"body": f"reply {i}"})
    page_two = text(member.get(f"/thread/{thread.id}?page=2"))
    assert "reply 19" in page_two
    assert "reply 0<" not in page_two
    last = db(app).scalars(select(Post).order_by(Post.id.desc())).first()
    response = member.get(f"/post/{last.id}")
    assert "page=2" in response.headers["Location"]


def test_quote_prefills_reply(app, forum):
    admin, member, board = forum
    create_thread(admin, board, body="Quote me")
    thread = db(app).scalar(select(Thread))
    post = db(app).scalar(select(Post))
    page = text(member.get(f"/thread/{thread.id}/reply?quote={post.id}"))
    assert "[quote=admin]Quote me[/quote]" in page


def test_edit_and_delete_own_post(app, forum):
    _, member, board = forum
    create_thread(member, board)
    thread = db(app).scalar(select(Thread))
    member.post(f"/thread/{thread.id}/reply", {"body": "typo"})
    reply = db(app).scalars(select(Post).order_by(Post.id.desc())).first()

    member.post(f"/post/{reply.id}/edit", {"body": "fixed", "action": "post"})
    page = text(member.get(f"/thread/{thread.id}"))
    assert "fixed" in page and "Last edited" in page

    member.post(f"/post/{reply.id}/delete")
    assert db(app).get(Post, reply.id) is None


def test_members_cannot_edit_others_posts(app, forum):
    admin, member, board = forum
    create_thread(admin, board)
    post = db(app).scalar(select(Post))
    assert member.get(f"/post/{post.id}/edit").status_code == 403
    assert member.post(f"/post/{post.id}/delete").status_code == 403
    assert admin.get(f"/post/{post.id}/edit").status_code == 200


def test_locked_thread_blocks_replies(app, forum):
    admin, member, board = forum
    create_thread(member, board)
    thread = db(app).scalar(select(Thread))
    admin.post(f"/thread/{thread.id}/moderate", {"action": "lock"})
    member.post(f"/thread/{thread.id}/reply", {"body": "sneaky"})
    assert db(app).scalar(
        select(sqlalchemy.func.count(Post.id))
    ) == 1
    assert member.post(
        f"/thread/{thread.id}/moderate", {"action": "unlock"}
    ).status_code == 403


def test_move_and_delete_thread(app, forum):
    admin, member, board = forum
    admin.post("/admin/board/new", {
        "name": "Archive", "category_id": board.category_id,
    })
    archive = db(app).scalar(select(Board).where(Board.name == "Archive"))
    create_thread(member, board)
    thread = db(app).scalar(select(Thread))
    admin.post(f"/thread/{thread.id}/moderate",
               {"action": "move", "board_id": archive.id})
    assert db(app).get(Thread, thread.id).board_id == archive.id
    admin.post(f"/thread/{thread.id}/moderate", {"action": "delete"})
    assert db(app).get(Thread, thread.id) is None
    assert db(app).scalar(select(Post)) is None


def test_board_moderator_can_moderate_their_board(app, forum):
    admin, member, board = forum
    admin.post(f"/admin/board/{board.id}", {
        "name": board.name, "category_id": board.category_id,
        "moderators": "bob",
    })
    create_thread(admin, board)
    thread = db(app).scalar(select(Thread))
    member.post(f"/thread/{thread.id}/moderate", {"action": "sticky"})
    assert db(app).get(Thread, thread.id).sticky


def test_staff_only_board_is_hidden(app, forum):
    admin, member, board = forum
    admin.post("/admin/board/new", {
        "name": "Staff Room", "category_id": board.category_id,
        "staff_only": "1",
    })
    staff = db(app).scalar(select(Board).where(Board.name == "Staff Room"))
    create_thread(admin, staff, "Secret plans")
    assert "Staff Room" not in text(member.get("/"))
    assert member.get(f"/board/{staff.id}").status_code == 404
    thread = db(app).scalar(select(Thread))
    assert member.get(f"/thread/{thread.id}").status_code == 404
    assert "Secret plans" not in text(member.get("/search?q=Secret"))
    assert "Secret plans" not in text(member.get("/recent"))
    assert "Staff Room" in text(admin.get("/"))


def test_hidden_sub_board_does_not_leak_into_parent(app, forum):
    admin, member, board = forum
    admin.post("/admin/board/new", {
        "name": "Mod Lounge", "category_id": board.category_id,
        "parent_id": board.id, "staff_only": "1",
    })
    lounge = db(app).scalar(select(Board).where(Board.name == "Mod Lounge"))
    create_thread(admin, lounge, "Ban list")
    home = text(member.get("/"))
    assert "Ban list" not in home and "Mod Lounge" not in home
    assert "Ban list" in text(admin.get("/"))


def test_sub_boards_roll_up_stats(app, forum):
    admin, member, board = forum
    admin.post("/admin/board/new", {
        "name": "Nested", "category_id": board.category_id,
        "parent_id": board.id,
    })
    nested = db(app).scalar(select(Board).where(Board.name == "Nested"))
    create_thread(member, nested, "Deep thread")
    home = text(member.get("/"))
    assert "Sub-boards:" in home and "Nested" in home
    assert "Deep thread" in home  # latest post of the parent board
    assert "Nested" in text(member.get(f"/board/{board.id}"))


def test_unread_indicators(app, forum):
    admin, member, board = forum
    create_thread(admin, board, "Fresh news")
    thread = db(app).scalar(select(Thread))
    # Pretend bob registered a while ago, before the thread was posted.
    bob = db(app).scalar(select(User).where(User.username == "bob"))
    bob.mark_read_at -= 60
    db(app).commit()
    assert 'class="tag new"' in text(member.get(f"/board/{board.id}"))
    member.get(f"/thread/{thread.id}")
    assert 'class="tag new"' not in text(member.get(f"/board/{board.id}"))


# --- Polls ----------------------------------------------------------------

def test_poll_voting(app, forum):
    admin, member, board = forum
    create_thread(admin, board, "Vote!", poll_question="Best color?",
                  poll_options="Red\nBlue\n\nGreen")
    poll = db(app).scalar(select(Poll))
    assert [o.text for o in poll.options] == ["Red", "Blue", "Green"]

    blue = poll.options[1]
    member.post(f"/thread/{poll.id}/vote", {"option": blue.id})
    member.post(f"/thread/{poll.id}/vote", {"option": blue.id})
    session = db(app)
    session.expire_all()
    assert session.get(Poll, poll.id).total_votes == 1
    assert "(100%)" in text(member.get(f"/thread/{poll.id}"))


def test_poll_needs_two_options(app, forum):
    admin, _, board = forum
    create_thread(admin, board, poll_question="Q?", poll_options="Only one")
    assert db(app).scalar(select(Thread)) is None


# --- Shoutbox, conversations, search, profiles ---------------------------

def test_shoutbox(app, forum):
    _, member, _ = forum
    member.post("/shoutbox", {"body": "Hello everyone :)"})
    page = text(member.get("/"))
    assert "Hello everyone" in page
    assert "\U0001F642" in page


def test_conversations(app, forum):
    admin, member, _ = forum
    member.post("/conversations/new", {
        "to": "admin", "subject": "Question", "body": "Can you help?",
    })
    assert '<span class="badge">1</span>' in text(admin.get("/"))
    inbox = text(admin.get("/conversations"))
    assert "Question" in inbox
    conversation_id = re.search(r"/conversations/(\d+)", inbox).group(1)
    page = text(admin.get(f"/conversations/{conversation_id}"))
    assert "Can you help?" in page
    assert '<span class="badge">' not in text(admin.get("/"))

    outsider = Browser(app)
    outsider.register("carol")
    assert outsider.get(
        f"/conversations/{conversation_id}"
    ).status_code == 404


def test_search(app, forum):
    admin, member, board = forum
    create_thread(admin, board, "Gardening tips", "Tomatoes need sun")
    create_thread(member, board, "Cars", "Engines are loud")
    page = text(member.get("/search?q=tomatoes"))
    assert "Gardening tips" in page and "Cars</a>" not in page
    page = text(member.get("/search?author=bob"))
    assert "Cars" in page and "Gardening tips" not in page
    page = text(member.get("/search?q=Cars&in=titles"))
    assert "1 found" in page


def test_profile_edit(app, forum):
    _, member, _ = forum
    bob = db(app).scalar(select(User).where(User.username == "bob"))
    member.post(f"/user/{bob.id}/edit", {
        "display_name": "Bobby", "status": "Feeling great",
        "signature": "[i]Bob's sig[/i]",
        "website_url": "javascript:alert(1)",
    })
    # The bad URL rejects the whole form.
    assert db(app).get(User, bob.id).display_name == "bob"
    member.post(f"/user/{bob.id}/edit", {
        "display_name": "Bobby", "status": "Feeling great",
        "signature": "[i]Bob's sig[/i]",
    })
    page = text(member.get(f"/user/{bob.id}"))
    assert "Bobby" in page and "Feeling great" in page
    assert "<em>Bob&#39;s sig</em>" in page or "<em>Bob's sig</em>" in page


def test_cannot_edit_someone_elses_profile(app, forum):
    _, member, _ = forum
    admin_user = db(app).scalar(select(User).where(User.username == "admin"))
    assert member.get(f"/user/{admin_user.id}/edit").status_code == 403


def test_admin_pages_require_admin(app, forum):
    _, member, _ = forum
    for url in ("/admin/", "/admin/settings", "/admin/users"):
        assert member.get(url).status_code == 403


def test_admin_settings(app, forum):
    admin, _, _ = forum
    admin.post("/admin/settings", {
        "forum_name": "Retro Board", "theme_color": "#aa0000",
        "threads_per_page": "10", "posts_per_page": "10",
        "members_per_page": "10", "registration_open": "1",
    })
    page = text(Browser(app).get("/"))
    assert "Retro Board" in page
    assert "--theme: #aa0000" in page
    assert 'id="shoutbox"' not in page


# --- Formatting & security -----------------------------------------------

def test_html_in_posts_is_escaped(app, forum):
    _, member, board = forum
    create_thread(member, board, "<script>x</script>",
                  '<script>alert(1)</script> [url=javascript:alert(1)]x[/url]'
                  ' [img]javascript:alert(1)[/img]')
    thread = db(app).scalar(select(Thread))
    page = text(member.get(f"/thread/{thread.id}"))
    assert "<script>alert(1)</script>" not in page
    assert "<script>x</script>" not in page
    assert "javascript:alert" not in page.replace(
        "[url=javascript:alert(1)]", ""
    ).replace("[img]javascript:alert(1)[/img]", "")


def test_imported_html_is_sanitized():
    markup = str(render(
        '<b>ok</b><script>bad()</script><img src="x" onerror="bad()">'
        '<a href="javascript:bad()">link</a>', "html"
    ))
    assert "<b>ok</b>" in markup
    assert "script" not in markup
    assert "onerror" not in markup
    assert "javascript" not in markup


def test_bbcode():
    html = bbcode_to_html(
        "[b]bold[/b] [i]it[/i] [url=https://example.com]site[/url]\n"
        "[quote=Ann][quote]inner[/quote]outer[/quote]"
        "[code][b]not bold[/b][/code]"
        "[list][*]one[*]two[/list] [color=red]red[/color] :D"
    )
    assert "<strong>bold</strong>" in html
    assert "<em>it</em>" in html
    assert '<a href="https://example.com">site</a>' in html
    assert "Quote from Ann" in html and html.count("<blockquote") == 2
    assert html.count("<div class=\"quote-body\">") == 2
    assert "[b]not bold[/b]" in html
    assert "<ul><li>one</li><li>two</li></ul>" in html
    assert '<span style="color: red">red</span>' in html
    assert "\U0001F600" in html


def test_uploads_only_serve_images(app):
    uploads = pathlib.Path(app.config["UPLOAD_FOLDER"])
    (uploads / "evil.html").write_text("<script>bad()</script>")
    (uploads / "ok.png").write_bytes(b"\x89PNG....")
    client = app.test_client()
    assert client.get("/uploads/evil.html").status_code == 404
    assert client.get("/uploads/ok.png").status_code == 200
    assert client.get("/uploads/../secret_key").status_code == 404


# --- Import from the scraper ---------------------------------------------

def load_scraper_schema():
    """Load the scraper's schema module without its network dependencies."""
    path = REPO / "proboards_scraper" / "database" / "schema.py"
    spec = importlib.util.spec_from_file_location("scraper_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scraped_site(tmp_path):
    schema = load_scraper_schema()
    site = tmp_path / "site"
    (site / "images").mkdir(parents=True)
    (site / "images" / "abc.png").write_bytes(b"\x89PNG....")
    engine = sqlalchemy.create_engine(f"sqlite:///{site / 'forum.db'}")
    schema.Base.metadata.create_all(engine)
    with sqlalchemy.orm.Session(engine) as s:
        s.add_all([
            schema.User(id=1, username="founder", name="The Founder",
                        group="Administrator", post_count=500,
                        date_registered=1000, signature="<i>sig</i>"),
            schema.User(id=2, username="regular", name="Regular Joe",
                        group="Member", post_count=3),
            schema.User(id=-1, name="Drive-by Guest"),
            schema.Image(id=1, filename="abc.png",
                         url="https://img.example/abc.png"),
            schema.Avatar(image_id=1, user_id=1),
            schema.Category(id=1, name="Main"),
            schema.Board(id=10, category_id=1, name="Lobby",
                         description="<b>Say hi</b>"),
            schema.Board(id=11, category_id=1, parent_id=10,
                         name="Introductions"),
            schema.Board(id=12, category_id=1, name="Secret",
                         password_protected=True),
            schema.Moderator(board_id=10, user_id=2),
            schema.Thread(id=100, board_id=11, user_id=1, title="Welcome",
                          sticky=True, views=42),
            schema.Post(id=1000, thread_id=100, user_id=1, date=2000,
                        message="Hello <b>world</b><script>x()</script>"),
            schema.Post(id=1001, thread_id=100, user_id=-1, date=3000,
                        message="Guest reply"),
            schema.Post(id=1002, thread_id=100, user_id=2, date=4000,
                        message="Hi!", last_edited=4500, edit_user_id=2),
            schema.Poll(id=100, name="Favorite season?"),
            schema.PollOption(id=1, poll_id=100, name="Summer", votes=3),
            schema.PollOption(id=2, poll_id=100, name="Winter", votes=1),
            schema.PollVoter(poll_id=100, user_id=2),
            schema.ShoutboxPost(id=1, date=5000, message="first!",
                                user_id=2),
        ])
        s.commit()
    return site


def test_import_scraped_forum(app, scraped_site):
    counts = import_scraped_forum(
        db(app), str(scraped_site), app.config["UPLOAD_FOLDER"]
    )
    assert counts == {
        "users": 2, "categories": 1, "boards": 3, "threads": 1,
        "posts": 3, "polls": 1, "shoutbox_posts": 1,
    }
    session = db(app)
    founder = session.get(User, 1)
    assert founder.is_admin and founder.password_hash is None
    assert founder.avatar_url == "/uploads/imported/abc.png"
    assert session.get(Board, 11).parent_id == 10
    assert session.get(Board, 12).staff_only
    guest_post = session.get(Post, 1001)
    assert guest_post.user_id is None
    assert guest_post.guest_name == "Drive-by Guest"

    client = Browser(app)
    home = text(client.get("/"))
    assert "Lobby" in home and "Introductions" in home
    assert "Secret" not in home
    page = text(client.get("/thread/100/welcome"))
    assert "Hello <b>world</b>" in page and "x()" not in page
    assert "Drive-by Guest" in page and "Favorite season?" in page
    assert "Posts: 500" in page
    assert client.get("/uploads/imported/abc.png").status_code == 200


def test_imported_members_can_log_in_after_password_set(app, scraped_site):
    import_scraped_forum(
        db(app), str(scraped_site), app.config["UPLOAD_FOLDER"]
    )
    browser = Browser(app)
    response = browser.login("founder", "whatever123")
    assert "no password yet" in text(response)

    from proboards_forum.cli import main
    main(["-i", app.instance_path, "set-password", "founder",
          "--password", "newpassword1"])
    browser.login("founder", "newpassword1")
    assert "Welcome back" in text(browser.get("/"))


def test_import_refuses_non_empty_forum(app, forum, scraped_site):
    from proboards_forum.importer import ForumImportError
    with pytest.raises(ForumImportError):
        import_scraped_forum(
            db(app), str(scraped_site), app.config["UPLOAD_FOLDER"]
        )
