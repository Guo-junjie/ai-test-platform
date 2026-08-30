"""
电商订单中心 — 被测示例服务（Flask + SQLite）

供 AI 自动化测试平台全流程验证使用：技术栈识别、接口提取、
AI 用例生成、接口/性能/集成测试、覆盖率自动采集。

模块划分：
- 认证：注册 / 登录（JWT）
- 商品：列表 / 详情 / 上架（管理员）
- 订单：创建（扣库存，含 VIP 折扣）/ 查询 / 取消（回滚库存）
"""
import io
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta

import jwt
from flask import Flask, g, jsonify, request

DB_PATH = os.environ.get("DB_PATH", "/tmp/order_center.db")
JWT_SECRET = "order-center-demo-secret"
JWT_ALGO = "HS256"
TOKEN_TTL_HOURS = 2
VIP_DISCOUNT = 0.8          # VIP 8 折
FULL_REDUCE_THRESHOLD = 100  # 满 100
FULL_REDUCE_OFF = 10         # 减 10（可与 VIP 叠加）

app = Flask(__name__)


# ==================== 数据库 ====================

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, vip INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            price REAL NOT NULL CHECK (price >= 0), stock INTEGER NOT NULL CHECK (stock >= 0),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            origin_price REAL NOT NULL, final_price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    # 种子数据（幂等）
    if not db.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        db.execute("INSERT INTO users (id, username, password, vip) VALUES (?,?,?,1)",
                   (str(uuid.uuid4()), "admin", "admin123"))
    if not db.execute("SELECT 1 FROM products WHERE sku='SKU-001'").fetchone():
        db.executemany(
            "INSERT INTO products (id, sku, name, price, stock) VALUES (?,?,?,?,?)",
            [
                (str(uuid.uuid4()), "SKU-001", "机械键盘", 399.0, 50),
                (str(uuid.uuid4()), "SKU-002", "无线鼠标", 129.0, 200),
                (str(uuid.uuid4()), "SKU-003", "显示器支架", 89.0, 0),  # 无库存，测 409
            ],
        )
    db.commit()
    db.close()


def _require_token():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, (jsonify(error="missing bearer token"), 401)
    try:
        payload = jwt.decode(auth[7:], JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        return None, (jsonify(error="token expired"), 401)
    except jwt.InvalidTokenError:
        return None, (jsonify(error="invalid token"), 401)
    user = get_db().execute(
        "SELECT * FROM users WHERE id=?", (payload["sub"],)
    ).fetchone()
    if user is None:
        return None, (jsonify(error="user not found"), 401)
    return user, None


def _calc_final_price(origin: float, vip: bool) -> float:
    """价格计算：VIP 8 折 + 满 100 减 10，可叠加，保留两位。"""
    final = origin * VIP_DISCOUNT if vip else origin
    if origin >= FULL_REDUCE_THRESHOLD:
        final -= FULL_REDUCE_OFF
    return round(max(final, 0.0), 2)


# ==================== 健康检查 ====================

@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok", service="order-center", time=int(time.time()))


# ==================== 认证模块 ====================

@app.route("/api/v1/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or len(password) < 6:
        return jsonify(error="username required, password >= 6 chars"), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify(error="username already exists"), 409
    uid = str(uuid.uuid4())
    db.execute("INSERT INTO users (id, username, password, vip) VALUES (?,?,?,0)",
               (uid, username, password))
    db.commit()
    return jsonify(id=uid, username=username, vip=False), 201


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    user = get_db().execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        ((data.get("username") or ""), (data.get("password") or "")),
    ).fetchone()
    if user is None:
        return jsonify(error="invalid credentials"), 401
    token = jwt.encode(
        {"sub": user["id"], "exp": datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )
    return jsonify(token=token, token_type="bearer", vip=bool(user["vip"]))


# ==================== 商品模块 ====================

@app.route("/api/v1/products", methods=["GET"])
def list_products():
    rows = get_db().execute("SELECT id, sku, name, price, stock FROM products").fetchall()
    return jsonify(items=[dict(r) for r in rows], total=len(rows))


@app.route("/api/v1/products/<product_id>", methods=["GET"])
def get_product(product_id: str):
    row = get_db().execute(
        "SELECT id, sku, name, price, stock FROM products WHERE id=? OR sku=?",
        (product_id, product_id),
    ).fetchone()
    if row is None:
        return jsonify(error="product not found"), 404
    return jsonify(dict(row))


@app.route("/api/v1/products", methods=["POST"])
def create_product():
    _user, err = _require_token()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    sku, name = (data.get("sku") or "").strip(), (data.get("name") or "").strip()
    price, stock = data.get("price"), int(data.get("stock", 0))
    if not sku or not name or price is None or price < 0 or stock < 0:
        return jsonify(error="sku/name/price/stock invalid"), 400
    db = get_db()
    if db.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone():
        return jsonify(error="sku duplicated"), 409
    pid = str(uuid.uuid4())
    db.execute("INSERT INTO products (id, sku, name, price, stock) VALUES (?,?,?,?,?)",
               (pid, sku, name, price, stock))
    db.commit()
    return jsonify(id=pid, sku=sku, name=name, price=price, stock=stock), 201


# ==================== 订单模块 ====================

@app.route("/api/v1/orders", methods=["POST"])
def create_order():
    user, err = _require_token()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    product_id, quantity = data.get("product_id"), int(data.get("quantity", 0))
    if not product_id or quantity <= 0:
        return jsonify(error="product_id and quantity>0 required"), 400
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=? OR sku=?",
                         (product_id, product_id)).fetchone()
    if product is None:
        return jsonify(error="product not found"), 404
    if product["stock"] < quantity:
        return jsonify(error="insufficient stock", stock=product["stock"]), 409
    origin = round(product["price"] * quantity, 2)
    final = _calc_final_price(origin, bool(user["vip"]))
    oid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO orders (id, user_id, product_id, quantity, origin_price, final_price) "
        "VALUES (?,?,?,?,?,?)",
        (oid, user["id"], product["id"], quantity, origin, final),
    )
    db.execute("UPDATE products SET stock = stock - ? WHERE id=?",
               (quantity, product["id"]))
    db.commit()
    return jsonify(
        id=oid, product_id=product["id"], quantity=quantity,
        origin_price=origin, final_price=final, status="created",
    ), 201


@app.route("/api/v1/orders/<order_id>", methods=["GET"])
def get_order(order_id: str):
    user, err = _require_token()
    if err:
        return err
    row = get_db().execute(
        "SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user["id"])
    ).fetchone()
    if row is None:
        return jsonify(error="order not found"), 404
    return jsonify(dict(row))


@app.route("/api/v1/orders", methods=["GET"])
def list_orders():
    user, err = _require_token()
    if err:
        return err
    rows = get_db().execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (user["id"],),
    ).fetchall()
    return jsonify(items=[dict(r) for r in rows], total=len(rows))


@app.route("/api/v1/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id: str):
    user, err = _require_token()
    if err:
        return err
    db = get_db()
    row = db.execute(
        "SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user["id"])
    ).fetchone()
    if row is None:
        return jsonify(error="order not found"), 404
    if row["status"] == "cancelled":
        return jsonify(error="order already cancelled"), 409
    db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    db.execute("UPDATE products SET stock = stock + ? WHERE id=?",
               (row["quantity"], row["product_id"]))  # 取消回滚库存
    db.commit()
    return jsonify(id=order_id, status="cancelled")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
