import hashlib
import re
import secrets
from functools import wraps
from time import time

from flask import Blueprint, abort, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

api = Blueprint("api", __name__, url_prefix="/api")
SESSION_SECONDS = 3600
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(32))
PRODUCT_FIELDS = "id, name, price_cents"
ORDER_FIELDS = "id, product_id, quantity, unit_price_cents, status"


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def require_user(role=None):
    def decorator(handler):
        @wraps(handler)
        def authenticated(*args, **kwargs):
            match = re.fullmatch(
                r"Bearer ([A-Za-z0-9_-]{43})",
                request.headers.get("Authorization", ""),
                flags=re.IGNORECASE | re.ASCII,
            )
            if match is None:
                abort(401)
            g.token_hash = token_hash(match[1])
            g.user = get_db().execute(
                """SELECT users.id, users.tenant_id, users.role
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (g.token_hash, int(time())),
            ).fetchone()
            if g.user is None:
                abort(401)
            if role is not None and g.user["role"] != role:
                abort(403)
            return handler(*args, **kwargs)

        return authenticated

    return decorator


def payload(*fields):
    data = request.get_json()
    if not isinstance(data, dict) or data.keys() != set(fields):
        abort(400)
    return data


def bounded_int(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        abort(400)
    return value


def order_for_tenant(order_id):
    if order_id > 2**63 - 1:
        abort(404)
    row = get_db().execute(
        f"SELECT {ORDER_FIELDS} FROM orders WHERE id = ? AND tenant_id = ?",
        (order_id, g.user["tenant_id"]),
    ).fetchone()
    if row is None:
        abort(404)
    return dict(row)


@api.post("/auth/login")
def login():
    data = payload("username", "password")
    username, password = data["username"], data["password"]
    if not isinstance(username, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", username):
        abort(400)
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        abort(400)
    # JSON escape sequences can introduce lone surrogates that scrypt cannot encode.
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        abort(400)
    db = get_db()
    user = db.execute(
        "SELECT id, role, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    password_hash = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
    if not check_password_hash(password_hash, password) or user is None:
        abort(401)
    token = secrets.token_urlsafe(32)
    now = int(time())
    with db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            (token_hash(token), user["id"], now + SESSION_SECONDS),
        )
    return {"access_token": token, "expires_in": SESSION_SECONDS, "role": user["role"]}


@api.post("/auth/logout")
@require_user()
def logout():
    db = get_db()
    with db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (g.token_hash,))
    return "", 204


@api.get("/products")
@require_user()
def products():
    query = request.args.get("q", "")
    if len(query) > 100 or (query and not query.isprintable()):
        abort(400)
    # Escape LIKE wildcards so the user controls a literal substring only.
    query = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    rows = get_db().execute(
        f"""SELECT {PRODUCT_FIELDS} FROM products
            WHERE tenant_id = ? AND name LIKE ? ESCAPE '!'
            ORDER BY id LIMIT 100""",
        (g.user["tenant_id"], f"%{query}%"),
    )
    return {"items": [dict(row) for row in rows]}


@api.post("/products")
@require_user("supplier")
def create_product():
    data = payload("name", "price_cents")
    name = data["name"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or not name.isprintable():
        abort(400)
    name = name.strip()
    price = bounded_int(data["price_cents"], 100000000)
    db = get_db()
    with db:
        cursor = db.execute(
            "INSERT INTO products (tenant_id, name, price_cents) VALUES (?, ?, ?)",
            (g.user["tenant_id"], name, price),
        )
    return {"id": cursor.lastrowid, "name": name, "price_cents": price}, 201


@api.get("/orders")
@require_user()
def orders():
    rows = get_db().execute(
        f"SELECT {ORDER_FIELDS} FROM orders WHERE tenant_id = ? ORDER BY id LIMIT 100",
        (g.user["tenant_id"],),
    )
    return {"items": [dict(row) for row in rows]}


@api.get("/orders/<int:order_id>")
@require_user()
def get_order(order_id):
    return order_for_tenant(order_id)


@api.post("/orders")
@require_user("buyer")
def create_order():
    data = payload("product_id", "quantity")
    product_id = bounded_int(data["product_id"], 2**63 - 1)
    quantity = bounded_int(data["quantity"], 1000)
    db = get_db()
    with db:
        # Copy the current price and tenant from the scoped product in one statement.
        cursor = db.execute(
            """INSERT INTO orders (tenant_id, product_id, quantity, unit_price_cents)
               SELECT tenant_id, id, ?, price_cents FROM products
               WHERE id = ? AND tenant_id = ?""",
            (quantity, product_id, g.user["tenant_id"]),
        )
        if cursor.rowcount == 0:
            abort(404)
        return order_for_tenant(cursor.lastrowid), 201


@api.patch("/orders/<int:order_id>")
@require_user("supplier")
def ship_order(order_id):
    data = payload("status")
    if data["status"] != "shipped":
        abort(400)
    db = get_db()
    with db:
        # Acquire the write lock before the read so concurrent shipping retries agree.
        db.execute("BEGIN IMMEDIATE")
        order_for_tenant(order_id)
        db.execute(
            "UPDATE orders SET status = 'shipped' WHERE id = ? AND tenant_id = ? AND status = 'pending'",
            (order_id, g.user["tenant_id"]),
        )
        return order_for_tenant(order_id)
