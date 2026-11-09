CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('buyer', 'supplier'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents BETWEEN 1 AND 100000000),
    internal_cost_cents INTEGER CHECK (internal_cost_cents >= 0),
    UNIQUE (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS products_tenant ON products(tenant_id, id);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 1000),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents BETWEEN 1 AND 100000000),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'shipped')),
    FOREIGN KEY (product_id, tenant_id) REFERENCES products(id, tenant_id)
);
CREATE INDEX IF NOT EXISTS orders_tenant ON orders(tenant_id, id);
