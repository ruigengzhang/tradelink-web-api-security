"""Replay the same requests against isolated before and after test clients."""

import json
from contextlib import closing
from tempfile import TemporaryDirectory
from pathlib import Path

from flask import Flask, abort, request

from tradelink import create_app
from tradelink.db import DEMO_PASSWORD, connect, create_schema, seed_demo


def vulnerable_client(db, token):
    app = Flask("isolated_lab", static_folder=None)
    app.testing = True

    @app.before_request
    def authenticate_pacific_buyer():
        if request.headers.get("Authorization") != f"Bearer {token}":
            abort(401)

    @app.get("/api/orders/<int:order_id>")
    def read_order(order_id):
        # TL-01: Missing tenant constraint.
        row = db.execute(
            """SELECT id, product_id, quantity, unit_price_cents, status
               FROM orders WHERE id = ?""",
            (order_id,),
        ).fetchone()
        if row is None:
            abort(404)
        return dict(row)

    @app.get("/api/products")
    def products():
        # TL-02: Search is interpolated. TL-03: Internal cost is serialized.
        query = request.args.get("q", "")
        rows = db.execute(
            f"""SELECT id, name, price_cents, internal_cost_cents FROM products
                WHERE tenant_id = 1 AND name LIKE '%{query}%' ORDER BY id"""
        )
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/products")
    def create_product():
        # TL-04: A buyer can invoke a supplier-only function.
        data = request.get_json()
        with db:
            cursor = db.execute(
                "INSERT INTO products (tenant_id, name, price_cents) VALUES (1, ?, ?)",
                (data["name"], data["price_cents"]),
            )
        return {"id": cursor.lastrowid, **data}, 201

    return app.test_client()


def compare():
    with TemporaryDirectory(prefix="tradelink-") as directory, closing(connect(":memory:")) as db:
        create_schema(db)
        seed_demo(db)
        app = create_app({"TESTING": True, "DATABASE": str(Path(directory) / "secure.sqlite3")})
        result = app.test_cli_runner().invoke(args=["init-db", "--demo"], catch_exceptions=False)
        if result.exit_code:
            raise RuntimeError(result.output)
        secure = app.test_client()
        login = secure.post(
            "/api/auth/login", json={"username": "pacific-buyer", "password": DEMO_PASSWORD}
        )
        token = login.json["access_token"]
        before = vulnerable_client(db, token)
        headers = {"Authorization": f"Bearer {token}"}
        cases = [
            ("TL-01", "GET", "/api/orders/2002", {}),
            ("TL-02", "GET", "/api/products", {"query_string": {"q": "' OR 1=1 -- "}}),
            ("TL-03", "GET", "/api/products", {"query_string": {"q": "USB"}}),
            ("TL-04", "POST", "/api/products", {"json": {"name": "Lab item", "price_cents": 100}}),
        ]
        for finding, method, path, options in cases:
            insecure = before.open(path, method=method, headers=headers, **options)
            fixed = secure.open(path, method=method, headers=headers, **options)
            yield {
                "finding": finding,
                "before": {"status": insecure.status_code, "body": insecure.get_json()},
                "after": {"status": fixed.status_code, "body": fixed.get_json()},
            }


if __name__ == "__main__":
    print(json.dumps(list(compare()), indent=2))
