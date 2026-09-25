"""
``pbf``: command-line tool for running and managing the forum.
"""
import argparse
import getpass
import sys

from sqlalchemy import func, select

from . import auth, create_app
from .importer import ForumImportError, import_scraped_forum
from .models import ROLE_ADMIN, Board, Category, User


def _db(app):
    return app.extensions["db"]()


def cmd_run(app, args) -> None:
    app.run(host=args.host, port=args.port, debug=args.debug)


def cmd_init(app, args) -> None:
    """Create an admin account and a starter category and board."""
    db = _db(app)
    if db.scalar(select(func.count(User.id))):
        sys.exit("This forum already has members.")
    username = args.username or input("Admin username: ").strip()
    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        sys.exit("Passwords must be at least 8 characters.")
    db.add(User(
        username=username, display_name=username, email=args.email,
        password_hash=auth.hash_password(password), role=ROLE_ADMIN,
    ))
    if not db.scalar(select(func.count(Board.id))):
        category = Category(name="General", position=1)
        db.add(category)
        db.flush()
        db.add(Board(
            category_id=category.id, name="General Discussion",
            description="Talk about anything here.",
        ))
    db.commit()
    print(f"Created administrator {username!r} and a starter board.")


def cmd_import(app, args) -> None:
    db = _db(app)
    try:
        counts = import_scraped_forum(
            db, args.source, app.config["UPLOAD_FOLDER"]
        )
    except ForumImportError as exc:
        sys.exit(str(exc))
    for key, value in counts.items():
        print(f"{key.replace('_', ' ').title():>16}: {value:,}")
    print("\nImported members have no password. Set one for your own "
          "account with:\n  pbf set-password <username> --admin")


def cmd_set_password(app, args) -> None:
    db = _db(app)
    user = db.scalar(select(User).where(
        func.lower(User.username) == args.username.lower()
    ))
    if user is None:
        sys.exit(f"No member with username {args.username!r}.")
    password = args.password or getpass.getpass("New password: ")
    if len(password) < 8:
        sys.exit("Passwords must be at least 8 characters.")
    user.password_hash = auth.hash_password(password)
    if args.admin:
        user.role = ROLE_ADMIN
    db.commit()
    print(f"Password updated for {user.username!r}"
          + (" (now an administrator)." if args.admin else "."))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="pbf",
        description="Run and manage a ProBoards-style forum.",
    )
    parser.add_argument(
        "-i", "--instance", metavar="<path>",
        help="Forum data directory holding the database and uploads "
             "(default: $PBF_INSTANCE or ./forum)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Start the web server")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=5000)
    run.add_argument("--debug", action="store_true")
    run.set_defaults(func=cmd_run)

    init = commands.add_parser(
        "init", help="Create the admin account and a starter board"
    )
    init.add_argument("--username")
    init.add_argument("--password")
    init.add_argument("--email")
    init.set_defaults(func=cmd_init)

    import_ = commands.add_parser(
        "import", help="Import a forum scraped with pbs"
    )
    import_.add_argument(
        "source", help="pbs output directory (e.g. ./site) or forum.db path"
    )
    import_.set_defaults(func=cmd_import)

    set_password = commands.add_parser(
        "set-password", help="Set a member's password"
    )
    set_password.add_argument("username")
    set_password.add_argument("--password")
    set_password.add_argument(
        "--admin", action="store_true", help="Also make them an administrator"
    )
    set_password.set_defaults(func=cmd_set_password)

    args = parser.parse_args(argv)
    app = create_app(args.instance)
    with app.app_context():
        args.func(app, args)


if __name__ == "__main__":
    main()
