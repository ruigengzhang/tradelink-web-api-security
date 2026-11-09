import sqlite3
from contextlib import closing

import pytest

from lab.compare import compare
from tradelink.db import DEMO_PASSWORD, connect, create_schema, seed_demo


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/products"),
        ("post", "/api/products"),
        ("get", "/api/orders"),
        ("post", "/api/orders"),
        ("get", "/api/orders/1001"),
        ("patch", "/api/orders/1001"),
        ("post", "/api/auth/logout"),
    ],
)
def test_private_routes_require_bearer(client, method, path):
    for headers in ({}, {"Authorization": "Bearer forged"}, {"X-Tenant-ID": "1"}):
        response = getattr(client, method)(path, headers=headers)
        assert response.status_code == 401
        assert response.json == {"error": "Unauthorized"}
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == "no-store"


def test_wrong_password_and_unknown_user_have_same_public_error(client):
    def attempt(username):
        return client.post("/api/auth/login", json={"username": username, "password": "wrong"})

    known, unknown = attempt("pacific-buyer"), attempt("unknown")
    assert known.status_code == unknown.status_code == 401
    assert known.json == unknown.json


def test_logout_revokes_only_current_token(client, sign_in):
    first, second = sign_in(), sign_in()
    assert first != second
    assert client.post("/api/auth/logout", headers=first).status_code == 204
    assert client.get("/api/orders", headers=first).status_code == 401
    assert client.get("/api/orders", headers=second).status_code == 200


def test_sessions_expire_and_only_digest_is_stored(app, client, sign_in, monkeypatch):
    monkeypatch.setattr("tradelink.api.time", lambda: 100)
    headers = sign_in()
    token = headers["Authorization"].split()[1]
    with closing(connect(app.config["DATABASE"])) as db:
        session = db.execute("SELECT token_hash, expires_at FROM sessions").fetchone()
        assert session["token_hash"] != token
        assert len(session["token_hash"]) == 64
        assert session["expires_at"] == 3700
    monkeypatch.setattr("tradelink.api.time", lambda: 3700)
    assert client.get("/api/orders", headers=headers).status_code == 401


@pytest.mark.parametrize(
    ("username", "own_id", "foreign_id"),
    [("pacific-buyer", 1001, 2002), ("atlantic-supplier", 2002, 1001)],
)
def test_order_lists_and_lookup_are_tenant_scoped(client, sign_in, username, own_id, foreign_id):
    headers = {**sign_in(username), "X-Tenant-ID": "99"}
    listing = client.get("/api/orders?tenant_id=99", headers=headers)
    assert [item["id"] for item in listing.json["items"]] == [own_id]
    assert client.get(f"/api/orders/{own_id}", headers=headers).status_code == 200
    foreign = client.get(f"/api/orders/{foreign_id}", headers=headers)
    missing = client.get("/api/orders/9999", headers=headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json == missing.json
    assert client.get(f"/api/orders/{2**63}", headers=headers).status_code == 404


def test_foreign_order_update_is_denied_and_has_no_side_effect(client, sign_in):
    result = client.patch(
        "/api/orders/2002", headers=sign_in("pacific-supplier"), json={"status": "shipped"}
    )
    assert result.status_code == 404
    own = client.get("/api/orders/2002", headers=sign_in("atlantic-supplier"))
    assert own.json["status"] == "pending"


def test_only_buyer_can_order_and_only_supplier_can_ship_or_create_product(client, sign_in):
    buyer = sign_in()
    supplier = sign_in("pacific-supplier")
    assert client.post("/api/orders", headers=supplier, json={"product_id": 101, "quantity": 1}).status_code == 403
    assert client.patch("/api/orders/1001", headers=buyer, json={"status": "shipped"}).status_code == 403
    assert client.post("/api/products", headers=buyer, json={"name": "Cable", "price_cents": 500}).status_code == 403


def test_order_lifecycle_and_product_role(client, sign_in):
    buyer = sign_in()
    supplier = sign_in("pacific-supplier")
    product = client.post("/api/products", headers=supplier, json={"name": "Cable", "price_cents": 775})
    assert product.status_code == 201
    assert set(product.json) == {"id", "name", "price_cents"}
    product_id = product.json["id"]

    assert client.post(
        "/api/orders", headers=buyer, json={"product_id": 202, "quantity": 2}
    ).status_code == 404
    order = client.post("/api/orders", headers=buyer, json={"product_id": product_id, "quantity": 2})
    assert order.status_code == 201
    assert order.json == {
        "id": order.json["id"], "product_id": product_id, "quantity": 2,
        "unit_price_cents": 775, "status": "pending",
    }
    url = f"/api/orders/{order.json['id']}"
    for _ in range(2):
        shipped = client.patch(url, headers=supplier, json={"status": "shipped"})
        assert shipped.status_code == 200
        assert shipped.json["status"] == "shipped"
    assert client.patch(url, headers=supplier, json={"status": "pending"}).status_code == 400
    assert client.get(url, headers=buyer).json == shipped.json


def test_database_rejects_cross_tenant_product_reference(app):
    with closing(connect(app.config["DATABASE"])) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO orders (tenant_id, product_id, quantity, unit_price_cents) VALUES (1, 202, 1, 10)"
            )


@pytest.mark.parametrize("query", ["' OR 1=1 -- ", "' UNION SELECT 1,2,3 -- ", "%", "_", "!"])
def test_search_treats_metacharacters_as_literal(client, sign_in, query):
    result = client.get("/api/products", query_string={"q": query}, headers=sign_in())
    assert result.status_code == 200
    assert result.json == {"items": []}


def test_catalog_search_keeps_tenant_and_cost_private(client, sign_in):
    pacific = client.get("/api/products?q=USB", headers=sign_in())
    atlantic = client.get("/api/products", headers=sign_in("atlantic-buyer"))
    assert pacific.json == {"items": [{"id": 101, "name": "USB-C Adapter", "price_cents": 1500}]}
    assert atlantic.json == {"items": [{"id": 202, "name": "Ceramic Mug", "price_cents": 2400}]}


@pytest.mark.parametrize(
    "data",
    [
        {"product_id": 101, "quantity": 1, "tenant_id": 2},
        {"product_id": 101, "quantity": 1, "status": "shipped"},
        {"product_id": 101, "quantity": 1, "unit_price_cents": 1},
        {"product_id": 101, "quantity": True},
        {"product_id": 101, "quantity": 1.0},
        {"product_id": 101, "quantity": 0},
        {"product_id": 101, "quantity": 1001},
        {"product_id": 2**63, "quantity": 1},
        [],
    ],
)
def test_order_rejects_extra_properties_and_bad_quantities(client, sign_in, data):
    assert client.post("/api/orders", headers=sign_in(), json=data).status_code == 400


def test_product_rejects_internal_cost_in_write(client, sign_in):
    response = client.post(
        "/api/products",
        headers=sign_in("pacific-supplier"),
        json={"name": "Cable", "price_cents": 100, "internal_cost_cents": 0},
    )
    assert response.status_code == 400


def test_invalid_and_large_inputs_return_public_errors(client, sign_in):
    url = "/api/auth/login"
    assert client.post(url, data="{}", content_type="text/plain").status_code == 415
    assert client.post(url, data="{", content_type="application/json").status_code == 400
    assert client.post(url, json={"username": "pacific-buyer", "password": "\ud800"}).status_code == 400
    assert client.post(url, json={"username": "pacific-buyer", "password": "x" * 20000}).status_code == 413
    headers = sign_in()
    assert client.get("/api/products?q=%00", headers=headers).status_code == 400
    assert client.get("/api/products", headers=headers, query_string={"q": "x" * 101}).status_code == 400


def test_browser_security_headers_and_route_isolation(client, sign_in):
    home = client.get("/")
    assert home.status_code == 200
    assert b"/static/app.js" in home.data
    assert "frame-ancestors 'none'" in home.headers["Content-Security-Policy"]
    assert home.headers["X-Frame-Options"] == "DENY"
    assert home.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400
    assert client.get("/healthz").json == {"status": "ok"}
    assert client.get("/lab", headers=sign_in()).status_code == 404
    assert client.get("/static/app.js").status_code == 200


def test_schema_and_demo_seed_can_be_repeated(tmp_path):
    with closing(connect(tmp_path / "demo.sqlite3")) as db:
        create_schema(db)
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        seed_demo(db)
        stored_hash = db.execute("SELECT password_hash FROM users WHERE id = 1").fetchone()[0]
        assert stored_hash != DEMO_PASSWORD
        create_schema(db)
        seed_demo(db)
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4
        assert db.execute("SELECT password_hash FROM users WHERE id = 1").fetchone()[0] == stored_hash


def test_lab_demonstrates_each_exploit_and_retest():
    results = {case["finding"]: case for case in compare()}
    assert set(results) == {"TL-01", "TL-02", "TL-03", "TL-04"}
    assert results["TL-01"]["before"]["body"]["id"] == 2002
    assert results["TL-01"]["after"]["status"] == 404
    assert [item["id"] for item in results["TL-02"]["before"]["body"]["items"]] == [101, 202]
    assert results["TL-02"]["after"] == {"status": 200, "body": {"items": []}}
    assert results["TL-03"]["before"]["body"]["items"][0]["internal_cost_cents"] == 800
    assert "internal_cost_cents" not in results["TL-03"]["after"]["body"]["items"][0]
    assert results["TL-04"]["before"]["status"] == 201
    assert results["TL-04"]["after"]["status"] == 403
