import sqlite3
from pathlib import Path

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

DEMO_PASSWORD = "TradeLink-Demo-Only!"


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_schema(db):
    db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


def seed_demo(db):
    with db:
        db.executemany(
            "INSERT OR IGNORE INTO tenants VALUES (?, ?)",
            [(1, "Pacific Workspace"), (2, "Atlantic Workspace")],
        )
        for user in [
            (1, 1, "pacific-buyer", "buyer"),
            (2, 1, "pacific-supplier", "supplier"),
            (3, 2, "atlantic-buyer", "buyer"),
            (4, 2, "atlantic-supplier", "supplier"),
        ]:
            user_id, tenant_id, username, role = user
            if db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                continue
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (user_id, tenant_id, username, generate_password_hash(DEMO_PASSWORD), role),
            )
        db.executemany(
            "INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?, ?)",
            [(101, 1, "USB-C Adapter", 1500, 800), (202, 2, "Ceramic Mug", 2400, 1100)],
        )
        db.executemany(
            """INSERT OR IGNORE INTO orders
               (id, tenant_id, product_id, quantity, unit_price_cents)
               VALUES (?, ?, ?, ?, ?)""",
            [(1001, 1, 101, 10, 1500), (2002, 2, 202, 25, 2400)],
        )


@click.command("init-db")
@click.option("--demo", is_flag=True, help="Add fictional workspaces and known demo accounts.")
@with_appcontext
def init_db_command(demo):
    db = get_db()
    create_schema(db)
    if demo:
        seed_demo(db)
    click.echo("Database ready.")
