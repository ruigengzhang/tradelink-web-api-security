# TradeLink vulnerability assessment report

The exercise evaluated whether authenticated users could read or change data outside their workspace or role. It examined the Flask API and SQLite query paths with two fictional workspaces. Four deliberately introduced defects were reproduced in isolated handlers and retested against the fixed application. The baseline had no network listener or access to the normal database.

## Scope and method

Reviewed login and logout, bearer-token handling, product search and creation, order lookup and updates, response fields and browser headers. Ran paired HTTP requests through Flask test clients with matching fixtures and a Pacific buyer identity. Regression checks also exercised approved workflows with both roles, foreign-object writes, database constraints and invalid input. Ratings use qualitative impact and ease of exploitation in the modeled system.

## Findings and retest evidence

| ID | Severity | Replay as Pacific buyer | Observed before | Observed after |
| --- | --- | --- | --- | --- |
| TL-01 | High | `GET /api/orders/2002` | `200` with Atlantic order 2002 and its commercial terms | `404` with the same error as a nonexistent order |
| TL-02 | High | `GET /api/products` with `q` equal to `' OR 1=1 -- ` | `200` with product IDs 101 and 202 across both workspaces | `200` with an empty list |
| TL-03 | Medium | `GET /api/products?q=USB` | `200` with `internal_cost_cents: 800` | `200` with ID, name and sale price only |
| TL-04 | Medium | `POST /api/products` with `{"name":"Lab item","price_cents":100}` | `201` and a new product in the workspace catalog | `403` |

**TL-01 · Broken object-level authorization.** An order ID alone selected the row, allowing a buyer to read quantities, prices and fulfillment state from another workspace. The fixed read and write paths use both the object ID and the tenant derived from the session. Regression tests cover both directions of isolation and verify that a denied update leaves the foreign order unchanged. [OWASP API1:2023](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)

**TL-02 · SQL injection.** The vulnerable query interpolated the search term directly into a SQL string. A tautology bypassed the workspace predicate and exposed another supplier's catalog. The fixed query binds both tenant and search term as parameters and escapes LIKE wildcards. Regression inputs include tautology, UNION syntax and individual wildcard characters. [CWE-89](https://cwe.mitre.org/data/definitions/89.html)

**TL-03 · Broken object property-level authorization.** The product response included internal costs, allowing a buyer to infer supplier margin. The fixed API explicitly selects public product fields and rejects attempts to write an internal cost. Regression tests check the precise public response shape. [OWASP API3:2023](https://owasp.org/API-Security/editions/2023/en/0xa3-broken-object-property-level-authorization/)

**TL-04 · Broken function-level authorization.** The baseline checked that the caller was authenticated and allowed any authenticated user to publish products. The fixed route checks the supplier role before accepting the request. Regression tests verify a supplier can publish and a buyer receives `403`. [OWASP API5:2023](https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/)

## Reproduce the evidence

```sh
python -m lab.compare
python -m pytest -q
```

The comparison prints before and after status codes and response bodies. The assessment uses synthetic data and targeted test cases. An optional passive ZAP baseline is configured separately and is outside this report's evidence. The [threat model](threat-model.md) records the deployment assumptions and residual risks.
