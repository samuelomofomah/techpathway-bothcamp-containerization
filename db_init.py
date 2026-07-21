"""
db_init.py — Creates database with Techpathway BothCamp real products.
Run: python3 db_init.py
"""

import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "shopping.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS categories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            description  TEXT,
            price        REAL NOT NULL CHECK(price >= 0),
            stock        INTEGER NOT NULL DEFAULT 0,
            category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            sku          TEXT UNIQUE,
            image_url    TEXT,
            video_url    TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            email      TEXT NOT NULL UNIQUE,
            phone      TEXT,
            address    TEXT,
            avatar_url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            status      TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','processing','shipped','delivered','cancelled')),
            total       REAL NOT NULL DEFAULT 0,
            notes       TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            quantity   INTEGER NOT NULL CHECK(quantity > 0),
            unit_price REAL NOT NULL,
            UNIQUE(order_id, product_id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            content     TEXT,
            doc_type    TEXT DEFAULT 'note'
                            CHECK(doc_type IN ('note','invoice','return','complaint','other')),
            file_url    TEXT,
            order_id    INTEGER REFERENCES orders(id),
            product_id  INTEGER REFERENCES products(id),
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # ── Categories ────────────────────────────────────────────────────────────
    c.executemany("INSERT OR IGNORE INTO categories (name, description) VALUES (?,?)", [
        ("Tops",        "Shirts, polos, and casual tops"),
        ("Bottoms",     "Pants, trousers, and wide-leg styles"),
        ("Outerwear",   "Blazers, jackets, and sets"),
        ("Footwear",    "Shoes, sneakers, and dress shoes"),
        ("Accessories", "Bags, belts, and accessories"),
    ])

    # ── Products with TC images ───────────────────────────────────────────────
    # Image paths: served from /static/images/ in local mode
    # In production these will be replaced by S3 URLs after upload
    c.executemany(
        "INSERT OR IGNORE INTO products (name,description,price,stock,category_id,sku,image_url) VALUES (?,?,?,?,?,?,?)",
        [
            (
                "Classic Slim Blazer",
                "A timeless slim-fit blazer in slate blue. Perfect for the office or a smart-casual look. Tailored lapels and a clean silhouette make this a wardrobe essential.",
                189.99, 30, 3, "TC-001",
                "/static/images/blazer.jpg"
            ),
            (
                "Luxury Oil Wax Tote Bag",
                "Handcrafted from premium oil-wax cowhide leather. This elegant professional shoulder bag develops a rich patina over time. Spacious interior with structured shape.",
                249.99, 20, 5, "TC-002",
                "/static/images/tote_bag.jpg"
            ),
            (
                "Minimalist White Sneakers",
                "Clean, versatile white leather sneakers built for everyday wear. Lightweight sole, cushioned insole, and a timeless silhouette that pairs with anything.",
                119.99, 50, 4, "TC-003",
                "/static/images/white_sneakers.jpg"
            ),
            (
                "Knit Polo — Sage Blue",
                "A refined short-sleeve polo knit in soft sage blue with contrast cream trim. Breathable, textured knit fabric. Easy to dress up or down.",
                89.99, 45, 1, "TC-004",
                "/static/images/casual_top.jpg"
            ),
            (
                "Cashmere Zip Set — Oat",
                "Luxuriously soft cashmere-blend zip jacket and tapered jogger pant set in warm oat. The perfect elevated loungewear or casual outfit.",
                299.99, 25, 3, "TC-005",
                "/static/images/beige_set.jpg"
            ),
            (
                "Canadian Club Jersey",
                "Premium heavyweight jersey with a classic Canadian athletic feel. Relaxed fit, ribbed cuffs and hem, and durable stitching built to last.",
                74.99, 60, 1, "TC-006",
                "/static/images/canadian_jersey.jpg"
            ),
            (
                "Wide-Leg Dress Pants — Navy",
                "Sleek wide-leg trousers in deep navy. High-waisted silhouette with a clean front pleat and belt loops. A polished staple for any wardrobe.",
                129.99, 35, 2, "TC-007",
                "/static/images/navy_pants.jpg"
            ),
            (
                "Brogue Oxford Dress Shoes",
                "Handcrafted dark brown leather Oxford brogues with a signature red sole. Cap-toe design with elegant perforated detailing. For the man who means business.",
                349.99, 15, 4, "TC-008",
                "/static/images/oxford_shoes.jpg"
            ),
        ]
    )

    # ── Sample customers ──────────────────────────────────────────────────────
    c.executemany("INSERT OR IGNORE INTO customers (name,email,phone,address) VALUES (?,?,?,?)", [
        ("Alice Martin",   "alice@example.com", "403-555-0101", "123 Maple St, Calgary AB"),
        ("Bob Chen",       "bob@example.com",   "403-555-0102", "456 Oak Ave, Calgary AB"),
        ("Carol Singh",    "carol@example.com", "403-555-0103", "789 Pine Rd, Edmonton AB"),
        ("David Williams", "david@example.com", "587-555-0104", "321 Elm Blvd, Calgary AB"),
    ])

    # ── Sample orders ─────────────────────────────────────────────────────────
    c.executemany("INSERT OR IGNORE INTO orders (customer_id,status,total,notes) VALUES (?,?,?,?)", [
        (1, "delivered", 439.98, "First order — blazer + tote"),
        (2, "shipped",   119.99, None),
        (3, "processing", 299.99, "Gift wrap please"),
        (4, "pending",   349.99, None),
    ])

    c.executemany("INSERT OR IGNORE INTO order_items (order_id,product_id,quantity,unit_price) VALUES (?,?,?,?)", [
        (1, 1, 1, 189.99), (1, 2, 1, 249.99),
        (2, 3, 1, 119.99),
        (3, 5, 1, 299.99),
        (4, 8, 1, 349.99),
    ])

    conn.commit()
    conn.close()
    print(f"✅  Database ready → {DB_PATH}")
    print(f"    8 products with TC images loaded")


if __name__ == "__main__":
    init_db()
