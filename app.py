"""
app.py — Techpathway BothCamp
Production: Flask + Gunicorn + MySQL (RDS) + S3 + Rate Limiting + HTTPS
"""

import os, uuid, sqlite3
from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, send_from_directory)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")

# ── Mode detection ────────────────────────────────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "")
S3_BUCKET  = os.getenv("S3_BUCKET", "")
USE_MYSQL  = bool(MYSQL_HOST and "rds.amazonaws.com" in MYSQL_HOST)
USE_S3     = bool(S3_BUCKET and os.getenv("AWS_ACCESS_KEY_ID","").startswith("AKIA")
                  and len(os.getenv("AWS_ACCESS_KEY_ID","")) > 16)

if USE_MYSQL:
    import pymysql
if USE_S3:
    import boto3
    s3_client = boto3.client(
        "s3",
        region_name           = os.getenv("AWS_REGION","us-east-1"),
        aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    S3_BASE = f"https://{S3_BUCKET}.s3.amazonaws.com/"

SQLITE_PATH   = os.path.join(os.path.dirname(__file__), "shopping.db")
ALLOWED_IMAGE = {"png","jpg","jpeg","gif","webp"}
ALLOWED_VIDEO = {"mp4","mov","avi","webm"}
ALLOWED_FILE  = ALLOWED_IMAGE | ALLOWED_VIDEO | {"pdf","docx","txt"}

# ── Rate limiting ─────────────────────────────────────────────────────────────
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URL","memory://"),
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def allowed(filename, types):
    return "." in filename and filename.rsplit(".",1)[1].lower() in types

def upload_file(file, folder="uploads"):
    if not USE_S3:
        return None
    ext = file.filename.rsplit(".",1)[1].lower()
    key = f"{folder}/{uuid.uuid4().hex}.{ext}"
    s3_client.upload_fileobj(file, S3_BUCKET, key,
        ExtraArgs={"ContentType": file.content_type, "ACL":"public-read"})
    return S3_BASE + key

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    if USE_MYSQL:
        return pymysql.connect(
            host     = MYSQL_HOST,
            port     = int(os.getenv("MYSQL_PORT", 3306)),
            user     = os.getenv("MYSQL_USER","admin"),
            password = os.getenv("MYSQL_PASSWORD",""),
            db       = os.getenv("MYSQL_DB","shopdb"),
            charset  = "utf8mb4",
            cursorclass = pymysql.cursors.DictCursor,
            autocommit  = True,
        )
    return None

def query(sql, params=(), one=False):
    if USE_MYSQL:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.close()
        return (rows[0] if rows else None) if one else rows
    sql = (sql.replace("%s","?")
              .replace("DATE_FORMAT(o.created_at,'%%Y-%%m-%%d')","substr(o.created_at,1,10)")
              .replace("DATE_FORMAT(o.created_at,'%%Y-%%m')","substr(o.created_at,1,7)"))
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return (rows[0] if rows else None) if one else rows

def execute(sql, params=()):
    if USE_MYSQL:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            lid = cur.lastrowid
        conn.close()
        return lid
    conn = sqlite3.connect(SQLITE_PATH)
    cur  = conn.execute(sql.replace("%s","?"), params)
    conn.commit()
    lid  = cur.lastrowid
    conn.close()
    return lid

# ── Force HTTPS in production ─────────────────────────────────────────────────
@app.before_request
def force_https():
    if os.getenv("FLASK_ENV") == "production":
        if request.headers.get("X-Forwarded-Proto") == "http":
            return redirect(request.url.replace("http://", "https://", 1), code=301)

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500

@app.errorhandler(429)
def rate_limited(e):
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"error":"Rate limit exceeded","retry_after":60}), 429
    return render_template("errors/429.html"), 429

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    stats = {
        "products":  query("SELECT COUNT(*) AS n FROM products", one=True)["n"],
        "customers": query("SELECT COUNT(*) AS n FROM customers", one=True)["n"],
        "orders":    query("SELECT COUNT(*) AS n FROM orders",    one=True)["n"],
        "revenue":   query("SELECT COALESCE(SUM(total),0) AS n FROM orders WHERE status != 'cancelled'", one=True)["n"],
    }
    date_expr = "DATE_FORMAT(o.created_at,'%%Y-%%m-%%d')" if USE_MYSQL else "substr(o.created_at,1,10)"
    recent_orders = query(f"""
        SELECT o.id, c.name AS customer, o.status, o.total, {date_expr} AS date
        FROM orders o JOIN customers c ON c.id=o.customer_id
        ORDER BY o.created_at DESC LIMIT 8""")
    low_stock     = query("SELECT name, stock, image_url FROM products WHERE stock < 30 ORDER BY stock LIMIT 6")
    status_counts = query("SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status")
    top_products  = query("""SELECT p.name, SUM(oi.quantity) AS sold, p.image_url
        FROM order_items oi JOIN products p ON p.id=oi.product_id
        GROUP BY p.id ORDER BY sold DESC LIMIT 5""")
    return render_template("dashboard.html", stats=stats, recent_orders=recent_orders,
        low_stock=low_stock, status_counts=status_counts, top_products=top_products,
        use_s3=USE_S3, use_mysql=USE_MYSQL)

# ── Products ──────────────────────────────────────────────────────────────────
@app.route("/products")
def products():
    q, cat = request.args.get("q",""), request.args.get("category","")
    ph  = "%s" if USE_MYSQL else "?"
    sql = "SELECT p.*, c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1"
    params = []
    if q:
        sql += f" AND (p.name LIKE {ph} OR p.description LIKE {ph} OR p.sku LIKE {ph})"
        params += [f"%{q}%"]*3
    if cat:
        sql += f" AND p.category_id={ph}"; params.append(cat)
    rows = query(sql+" ORDER BY p.name", params)
    categories = query("SELECT * FROM categories ORDER BY name")
    return render_template("products.html", products=rows, categories=categories, q=q, cat=cat)

@app.route("/products/new", methods=["GET","POST"])
@limiter.limit("30 per hour")
def new_product():
    categories = query("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        f = request.form
        image_url = upload_file(request.files["image"], "products/images") if request.files.get("image") and request.files["image"].filename and allowed(request.files["image"].filename, ALLOWED_IMAGE) else None
        video_url = upload_file(request.files["video"], "products/videos") if request.files.get("video") and request.files["video"].filename and allowed(request.files["video"].filename, ALLOWED_VIDEO) else None
        execute("INSERT INTO products (name,description,price,stock,category_id,sku,image_url,video_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (f["name"],f.get("description"),float(f["price"]),int(f["stock"]),f.get("category_id") or None,f.get("sku") or None,image_url,video_url))
        flash("Product created.","success")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=None, categories=categories, use_s3=USE_S3)

@app.route("/products/<int:pid>/edit", methods=["GET","POST"])
@limiter.limit("60 per hour")
def edit_product(pid):
    product = query("SELECT * FROM products WHERE id=%s",(pid,),one=True)
    categories = query("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        f = request.form
        image_url = upload_file(request.files["image"],"products/images") if request.files.get("image") and request.files["image"].filename and allowed(request.files["image"].filename,ALLOWED_IMAGE) else product["image_url"]
        video_url = upload_file(request.files["video"],"products/videos") if request.files.get("video") and request.files["video"].filename and allowed(request.files["video"].filename,ALLOWED_VIDEO) else product["video_url"]
        execute("UPDATE products SET name=%s,description=%s,price=%s,stock=%s,category_id=%s,sku=%s,image_url=%s,video_url=%s WHERE id=%s",
                (f["name"],f.get("description"),float(f["price"]),int(f["stock"]),f.get("category_id") or None,f.get("sku") or None,image_url,video_url,pid))
        flash("Product updated.","success")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=product, categories=categories, use_s3=USE_S3)

@app.route("/products/<int:pid>/delete", methods=["POST"])
@limiter.limit("30 per hour")
def delete_product(pid):
    execute("DELETE FROM products WHERE id=%s",(pid,))
    flash("Product deleted.","warning")
    return redirect(url_for("products"))

# ── Customers ─────────────────────────────────────────────────────────────────
@app.route("/customers")
def customers():
    q  = request.args.get("q","")
    ph = "%s" if USE_MYSQL else "?"
    sql = "SELECT * FROM customers WHERE 1=1"
    params = []
    if q:
        sql += f" AND (name LIKE {ph} OR email LIKE {ph})"; params += [f"%{q}%"]*2
    rows = query(sql+" ORDER BY name", params)
    return render_template("customers.html", customers=rows, q=q)

@app.route("/customers/new", methods=["GET","POST"])
@limiter.limit("30 per hour")
def new_customer():
    if request.method == "POST":
        f = request.form
        avatar_url = upload_file(request.files["avatar"],"customers/avatars") if request.files.get("avatar") and request.files["avatar"].filename and allowed(request.files["avatar"].filename,ALLOWED_IMAGE) else None
        execute("INSERT INTO customers (name,email,phone,address,avatar_url) VALUES (%s,%s,%s,%s,%s)",
                (f["name"],f["email"],f.get("phone"),f.get("address"),avatar_url))
        flash("Customer added.","success")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=None, use_s3=USE_S3)

@app.route("/customers/<int:cid>/edit", methods=["GET","POST"])
@limiter.limit("60 per hour")
def edit_customer(cid):
    customer = query("SELECT * FROM customers WHERE id=%s",(cid,),one=True)
    if request.method == "POST":
        f = request.form
        avatar_url = upload_file(request.files["avatar"],"customers/avatars") if request.files.get("avatar") and request.files["avatar"].filename and allowed(request.files["avatar"].filename,ALLOWED_IMAGE) else customer.get("avatar_url")
        execute("UPDATE customers SET name=%s,email=%s,phone=%s,address=%s,avatar_url=%s WHERE id=%s",
                (f["name"],f["email"],f.get("phone"),f.get("address"),avatar_url,cid))
        flash("Customer updated.","success")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=customer, use_s3=USE_S3)

@app.route("/customers/<int:cid>/delete", methods=["POST"])
@limiter.limit("30 per hour")
def delete_customer(cid):
    execute("DELETE FROM customers WHERE id=%s",(cid,))
    flash("Customer deleted.","warning")
    return redirect(url_for("customers"))

# ── Orders ────────────────────────────────────────────────────────────────────
@app.route("/orders")
def orders():
    status = request.args.get("status","")
    ph = "%s" if USE_MYSQL else "?"
    date_expr = "DATE_FORMAT(o.created_at,'%%Y-%%m-%%d')" if USE_MYSQL else "substr(o.created_at,1,10)"
    sql = f"SELECT o.*, c.name AS customer_name, {date_expr} AS date FROM orders o JOIN customers c ON c.id=o.customer_id WHERE 1=1"
    params = []
    if status:
        sql += f" AND o.status={ph}"; params.append(status)
    rows = query(sql+" ORDER BY o.created_at DESC", params)
    return render_template("orders.html", orders=rows, status=status)

@app.route("/orders/new", methods=["GET","POST"])
@limiter.limit("30 per hour")
def new_order():
    customers_list = query("SELECT * FROM customers ORDER BY name")
    products_list  = query("SELECT * FROM products ORDER BY name")
    if request.method == "POST":
        f = request.form
        pids,qtys,prices = f.getlist("product_id[]"),f.getlist("quantity[]"),f.getlist("unit_price[]")
        total = sum(float(p)*int(q) for p,q in zip(prices,qtys) if p and q)
        oid = execute("INSERT INTO orders (customer_id,status,total,notes) VALUES (%s,%s,%s,%s)",
                      (f["customer_id"],f.get("status","pending"),total,f.get("notes")))
        for pid,qty,price in zip(pids,qtys,prices):
            if pid and qty:
                execute("INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
                        (oid,int(pid),int(qty),float(price)))
        flash("Order created.","success")
        return redirect(url_for("orders"))
    return render_template("order_form.html", customers=customers_list, products=products_list)

@app.route("/orders/<int:oid>")
def order_detail(oid):
    order = query("SELECT o.*,c.name AS customer_name,c.email,c.address,c.avatar_url FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=%s",(oid,),one=True)
    items = query("SELECT oi.*,p.name AS product_name,p.sku,p.image_url FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=%s",(oid,))
    docs  = query("SELECT * FROM documents WHERE order_id=%s",(oid,))
    return render_template("order_detail.html", order=order, items=items, docs=docs)

@app.route("/orders/<int:oid>/status", methods=["POST"])
def update_order_status(oid):
    execute("UPDATE orders SET status=%s WHERE id=%s",(request.form["status"],oid))
    flash("Status updated.","success")
    return redirect(url_for("order_detail",oid=oid))

@app.route("/orders/<int:oid>/delete", methods=["POST"])
@limiter.limit("20 per hour")
def delete_order(oid):
    execute("DELETE FROM orders WHERE id=%s",(oid,))
    flash("Order deleted.","warning")
    return redirect(url_for("orders"))

# ── Documents ─────────────────────────────────────────────────────────────────
@app.route("/documents")
def documents():
    doc_type,q = request.args.get("type",""),request.args.get("q","")
    ph = "%s" if USE_MYSQL else "?"
    sql = "SELECT d.*,o.id AS order_ref,p.name AS product_name FROM documents d LEFT JOIN orders o ON o.id=d.order_id LEFT JOIN products p ON p.id=d.product_id WHERE 1=1"
    params = []
    if doc_type:
        sql += f" AND d.doc_type={ph}"; params.append(doc_type)
    if q:
        sql += f" AND (d.title LIKE {ph} OR d.content LIKE {ph})"; params += [f"%{q}%"]*2
    rows = query(sql+" ORDER BY d.created_at DESC", params)
    return render_template("documents.html", docs=rows, doc_type=doc_type, q=q)

@app.route("/documents/new", methods=["GET","POST"])
@limiter.limit("30 per hour")
def new_document():
    orders_list   = query("SELECT id FROM orders ORDER BY id DESC")
    products_list = query("SELECT id,name FROM products ORDER BY name")
    if request.method == "POST":
        f = request.form
        file_url = upload_file(request.files["file"],"documents") if request.files.get("file") and request.files["file"].filename and allowed(request.files["file"].filename,ALLOWED_FILE) else None
        execute("INSERT INTO documents (title,content,doc_type,file_url,order_id,product_id) VALUES (%s,%s,%s,%s,%s,%s)",
                (f["title"],f.get("content"),f.get("doc_type","note"),file_url,f.get("order_id") or None,f.get("product_id") or None))
        flash("Document saved.","success")
        return redirect(url_for("documents"))
    return render_template("document_form.html", doc=None, orders=orders_list, products=products_list, use_s3=USE_S3)

@app.route("/documents/<int:did>/delete", methods=["POST"])
@limiter.limit("20 per hour")
def delete_document(did):
    execute("DELETE FROM documents WHERE id=%s",(did,))
    flash("Document deleted.","warning")
    return redirect(url_for("documents"))

# ── SQL Console ───────────────────────────────────────────────────────────────
@app.route("/sql")
def sql_console():
    return render_template("sql_console.html", use_mysql=USE_MYSQL)

@app.route("/api/sql", methods=["POST"])
@limiter.limit("30 per hour; 5 per minute")
def run_sql():
    sql = request.json.get("sql","").strip()
    if not sql: return jsonify({"error":"No SQL."})
    first = sql.upper().split()[0] if sql.split() else ""
    if first not in {"SELECT","SHOW","DESCRIBE","EXPLAIN","WITH","PRAGMA"}:
        return jsonify({"error":"Only SELECT / SHOW / DESCRIBE / PRAGMA allowed."})
    try:
        if USE_MYSQL:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(sql); rows = cur.fetchmany(500)
            conn.close()
            if not rows: return jsonify({"columns":[],"rows":[]})
            return jsonify({"columns":list(rows[0].keys()),"rows":[list(r.values()) for r in rows]})
        else:
            conn = sqlite3.connect(SQLITE_PATH); conn.row_factory = sqlite3.Row
            cur  = conn.execute(sql); rows = cur.fetchmany(500); conn.close()
            if not rows: return jsonify({"columns":[],"rows":[]})
            return jsonify({"columns":list(rows[0].keys()),"rows":[list(dict(r).values()) for r in rows]})
    except Exception as e:
        return jsonify({"error":str(e)})

# ── Health check (for load balancer / monitoring) ─────────────────────────────
@app.route("/health")
@limiter.exempt
def health():
    try:
        query("SELECT 1 AS ok", one=True)
        return jsonify({"status":"ok","db":"connected","s3":USE_S3}), 200
    except Exception as e:
        return jsonify({"status":"error","detail":str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# STOREFRONT
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/store")
@limiter.limit("200 per hour")
def store_home():
    featured   = query("SELECT p.*,c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.stock>0 ORDER BY p.id DESC LIMIT 8")
    categories = query("SELECT * FROM categories ORDER BY name")
    return render_template("store/home.html", featured=featured, categories=categories)

@app.route("/store/products")
@limiter.limit("200 per hour")
def store_products():
    q,cat,sort = request.args.get("q",""),request.args.get("category",""),request.args.get("sort","")
    ph  = "%s" if USE_MYSQL else "?"
    sql = "SELECT p.*,c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1"
    params = []
    if q:
        sql += f" AND (p.name LIKE {ph} OR p.description LIKE {ph})"; params += [f"%{q}%"]*2
    if cat:
        sql += f" AND p.category_id={ph}"; params.append(cat)
    sql += {
        "price_asc": " ORDER BY p.price ASC", "price_desc": " ORDER BY p.price DESC",
        "name": " ORDER BY p.name ASC"
    }.get(sort, " ORDER BY p.name ASC")
    rows = query(sql, params)
    categories = query("SELECT * FROM categories ORDER BY name")
    return render_template("store/products.html", products=rows, categories=categories, q=q, cat=cat, sort=sort)

@app.route("/store/product/<int:pid>")
@limiter.limit("300 per hour")
def store_product(pid):
    product = query("SELECT p.*,c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=%s",(pid,),one=True)
    if not product: return redirect(url_for("store_products"))
    ph = "%s" if USE_MYSQL else "?"
    related = query(f"SELECT p.*,c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.category_id={ph} AND p.id!={ph} AND p.stock>0 LIMIT 4",(product["category_id"],pid)) if product.get("category_id") else []
    return render_template("store/product.html", product=product, related=related)

@app.route("/store/checkout")
def store_checkout():
    return render_template("store/checkout.html")

@app.route("/store/order", methods=["POST"])
@limiter.limit("5 per hour; 2 per minute")
def store_place_order():
    data = request.json
    if not data or not data.get("cart"):
        return jsonify({"error":"Empty cart"})
    try:
        name,email,phone,address = data.get("name","Guest"),data.get("email",""),data.get("phone",""),data.get("address","")
        existing = query("SELECT id FROM customers WHERE email=%s",(email,),one=True)
        if existing:
            cid = existing["id"]
            execute("UPDATE customers SET name=%s,phone=%s,address=%s WHERE id=%s",(name,phone,address,cid))
        else:
            cid = execute("INSERT INTO customers (name,email,phone,address) VALUES (%s,%s,%s,%s)",(name,email,phone,address))
        cart  = data.get("cart",[])
        total = sum(float(i["price"])*int(i["qty"]) for i in cart)
        oid   = execute("INSERT INTO orders (customer_id,status,total,notes) VALUES (%s,%s,%s,%s)",(cid,"pending",total,data.get("notes","")))
        for item in cart:
            execute("INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",(oid,item["id"],item["qty"],float(item["price"])))
        return jsonify({"order_id":oid})
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/store/success")
def store_success():
    return render_template("store/success.html", order_id=request.args.get("order",""))

# ── API ───────────────────────────────────────────────────────────────────────
@app.route("/api/dashboard")
@limiter.limit("60 per hour")
def api_dashboard():
    status_counts = query("SELECT status,COUNT(*) AS cnt FROM orders GROUP BY status")
    return jsonify({"status_counts":[dict(r) for r in status_counts]})

@app.route("/static/images/<path:filename>")
def serve_image(filename):
    """Serve local TC images in development mode."""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "static", "images"),
        filename
    )

if __name__ == "__main__":
    # Auto-create DB with TC products on first run
    if not USE_MYSQL and not os.path.exists(SQLITE_PATH):
        from db_init import init_db
        init_db()
    print(f"  Mode:    {'MySQL (RDS)' if USE_MYSQL else 'SQLite (local)'}")
    print(f"  Storage: {'S3 (' + S3_BUCKET + ')' if USE_S3 else 'Local images (static/images/)'}")
    app.run(debug=True, port=5111)
