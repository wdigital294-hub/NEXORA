"""Acesso a dados da NEXORA.

Todo o SQL da aplicação passa por aqui ou pelos repositórios em repo.py.
Motivo: quando a migração para PostgreSQL acontecer, o trabalho fica
confinado a estes dois ficheiros em vez de espalhado pelas rotas.

Regras da casa:
  * nunca concatenar valores dentro de SQL — sempre placeholders '?';
  * dinheiro é sempre INTEGER em cêntimos, nunca REAL;
  * datas guardadas em ISO-8601 UTC (texto), ordenáveis lexicograficamente.
"""
import sqlite3
from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    slug          TEXT    NOT NULL UNIQUE,
    logo          TEXT,
    cover         TEXT,
    description   TEXT,
    phone         TEXT,
    whatsapp      TEXT,
    address       TEXT,
    opening_hours TEXT,
    -- active | suspended | blocked
    status        TEXT    NOT NULL DEFAULT 'active',
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    -- owner (dono da NEXORA) | business (gestor de uma empresa)
    role          TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'active',
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    description TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_categories_business ON categories(business_id);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    name        TEXT    NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL DEFAULT 0,
    image       TEXT,
    available   INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_business ON products(business_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    code          TEXT    NOT NULL,
    customer_name TEXT,
    customer_phone TEXT,
    table_number  TEXT,
    notes         TEXT,
    payment_method TEXT,
    total_cents   INTEGER NOT NULL DEFAULT 0,
    -- new | confirmed | preparing | delivered | cancelled
    status        TEXT    NOT NULL DEFAULT 'new',
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_business ON orders(business_id, created_at);

CREATE TABLE IF NOT EXISTS order_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id    INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_name  TEXT    NOT NULL,   -- congelado no momento do pedido
    quantity      INTEGER NOT NULL,
    price_cents   INTEGER NOT NULL,   -- preço unitário no momento do pedido
    subtotal_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    price_cents INTEGER NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 30,
    features    TEXT,
    max_products INTEGER NOT NULL DEFAULT 0,  -- 0 = ilimitado
    status      TEXT    NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    plan_id     INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    -- active | pending | expired | suspended | cancelled
    status      TEXT    NOT NULL DEFAULT 'pending',
    start_date  TEXT,
    end_date    TEXT,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subs_business ON subscriptions(business_id);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    plan_id         INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    amount_cents    INTEGER NOT NULL,
    method          TEXT,
    proof_image     TEXT,
    -- pending | approved | rejected
    status          TEXT    NOT NULL DEFAULT 'pending',
    reference       TEXT,
    notes           TEXT,
    paid_at         TEXT,
    verified_at     TEXT,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_business ON payments(business_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

CREATE TABLE IF NOT EXISTS payment_methods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    details     TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_paymethods_business ON payment_methods(business_id);

-- Dados de pagamento DA NEXORA (para onde as empresas transferem).
CREATE TABLE IF NOT EXISTS platform_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_db():
    """Conexão por request. Fechada automaticamente no teardown."""
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL reduz bloqueios entre leitura e escrita simultâneas.
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        if exc is None:
            conn.commit()
        else:
            conn.rollback()
        conn.close()


def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=()):
    """Executa e devolve o lastrowid. Commit acontece no teardown."""
    cur = get_db().execute(sql, params)
    rowid = cur.lastrowid
    cur.close()
    return rowid


def init_db():
    get_db().executescript(SCHEMA)
    get_db().commit()
