# TradeLink Web & API Security Assessment

Project 2 follows a fictional B2B platform connecting US buyers with Chinese suppliers. Two trade workspaces share one Flask service and SQLite database. The project pairs an authenticated browser interface and JSON API with an isolated assessment that reproduces four defects and verifies their fixes.

## Run locally on macOS

Use Python 3.13 or 3.14. From the repository folder, run the following commands. If you have Python 3.14, use `python3.14` in the first command.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m flask --app tradelink init-db --demo
python -m flask --app tradelink run --host 127.0.0.1 --port 5000
```

Open [TradeLink on your Mac](http://127.0.0.1:5000). Try signing in as a Pacific buyer, searching for `USB`, then signing in as an Atlantic buyer to see the different catalog and orders. The fictional accounts share the password `TradeLink-Demo-Only!`.

| Workspace | Buyer | Supplier | Seed product | Seed order |
| --- | --- | --- | --- | --- |
| Pacific | `pacific-buyer` | `pacific-supplier` | 101 | 1001 |
| Atlantic | `atlantic-buyer` | `atlantic-supplier` | 202 | 2002 |

The database lives at `instance/tradelink.sqlite3`. Running initialization again preserves existing rows and order state. Keep the Flask development server on loopback and use fictional data. Without `--demo`, initialization creates only the database schema.

## Exercise the API

Except for login, API calls take `Authorization: Bearer <access_token>`. The role and workspace come from the authenticated account. The app reports a foreign workspace object as `404`, matching a missing object.

| Method and route | Access | Input or result |
| --- | --- | --- |
| `POST /api/auth/login` | Public | JSON `username` and `password`. Returns an expiring access token and role |
| `POST /api/auth/logout` | Signed in | Revokes the current token |
| `GET /api/products?q=USB` | Both roles | Optional literal name substring. Returns up to 100 workspace products |
| `POST /api/products` | Supplier | JSON `name` and integer `price_cents` |
| `GET /api/orders` | Both roles | Returns up to 100 workspace orders |
| `GET /api/orders/1001` | Both roles | Returns one workspace order |
| `POST /api/orders` | Buyer | JSON integer `product_id` and `quantity`. The server snapshots the catalog price |
| `PATCH /api/orders/1001` | Supplier | JSON `{"status":"shipped"}`. Repeating the request returns the shipped order |

For example, from a second terminal with the virtual environment active:

```sh
BASE=http://127.0.0.1:5000
TOKEN=$(curl -fsS "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  --data '{"username":"pacific-buyer","password":"TradeLink-Demo-Only!"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -fsS "$BASE/api/orders/1001" -H "Authorization: Bearer $TOKEN"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/api/orders/2002" \
  -H "Authorization: Bearer $TOKEN"  # 404

curl -fsS "$BASE/api/auth/logout" -X POST -H "Authorization: Bearer $TOKEN"
unset TOKEN
```

## Reproduce and retest the findings

```sh
python -m lab.compare
python -m pytest -q
```

The comparison sends identical HTTP requests through Flask test clients to vulnerable handlers and the fixed application. The vulnerable handlers run in-process against an in-memory database. The fixed application receives its own temporary database. The runner never opens a listening socket, and the normal Flask application registers only the fixed handlers.

| Finding | Before | After |
| --- | --- | --- |
| TL-01 Broken object-level authorization | Pacific buyer reads Atlantic order 2002 | `404` |
| TL-02 SQL injection | Product search bypasses workspace filter | Same input is treated as literal text and returns zero matches |
| TL-03 Internal cost exposure | Product JSON discloses supplier cost | Only ID, name and sale price are returned |
| TL-04 Broken function-level authorization | Buyer creates a product | `403` |

GitHub Actions runs the pytest suite on Python 3.13 and 3.14 for pushes and pull requests. See the [assessment report](docs/assessment-report.md), [threat model](docs/threat-model.md) and [optional OWASP ZAP baseline](zap/README.md).
