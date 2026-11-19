"""BIG BAZAR BD – customer storefront + app factory.

Run:  python app.py            (development / small VPS)
      gunicorn wsgi:app        (production)
"""
import os
import re
import sys
import time
import secrets
import getpass
from urllib.parse import quote

from flask import (Flask, g, request, session, redirect, url_for, render_template, abort,
                   flash, jsonify, send_from_directory, make_response)
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

import db as dbm
import sec
import util
from db import q, q1, ex, settings, annotate, PRODUCT_SELECT, ORDER_STATUSES, STATUS_BN

BASE = os.path.dirname(os.path.abspath(__file__))
PER_PAGE = 12
MAX_QTY = 20


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    data_dir = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
    os.makedirs(data_dir, exist_ok=True)

    # secret key: env var, else a random key persisted outside the source code
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        kf = os.path.join(data_dir, "secret.key")
        if not os.path.exists(kf):
            with open(kf, "w") as f:
                f.write(secrets.token_hex(32))
            try:
                os.chmod(kf, 0o600)
            except OSError:
                pass
        secret = open(kf).read().strip()

    admin_path = "/" + os.environ.get("ADMIN_PATH", "/admin").strip("/")
    https_only = os.environ.get("FORCE_HTTPS") == "1"
    app.config.update(
        SECRET_KEY=secret,
        DATA_DIR=data_dir,
        DB_PATH=os.path.join(data_dir, "bigbazar.db"),
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", os.path.join(data_dir, "uploads")),
        ADMIN_PATH=admin_path,
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        SESSION_COOKIE_NAME="bbd_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=https_only,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
        JSON_AS_ASCII=False,
        TEMPLATES_AUTO_RELOAD=bool(os.environ.get("DEBUG")),
    )
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    if os.environ.get("TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    dbm.init_db(app)
    dbm.ensure_admin(app)
    app.teardown_appcontext(dbm.close_db)

    # ---------------------------------------------------------- hooks
    @app.before_request
    def _before():
        lang = request.cookies.get("lang", "bn")
        g.lang = lang if lang in ("bn", "en") else "bn"
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not sec.csrf_ok():
            abort(400)

    @app.after_request
    def _after(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; script-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        if https_only:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        p = request.path
        if p.startswith(admin_path) or p.startswith(("/cart", "/checkout", "/order", "/track", "/api")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------------------------------------------------- template helpers
    def L(bn, en):
        return bn if g.get("lang", "bn") == "bn" else en

    def pick(row, field):
        """Pick the bn/en variant of a column, falling back to the other language."""
        try:
            bn, en = row[field + "_bn"] or "", row[field + "_en"] or ""
        except (KeyError, IndexError, TypeError):
            return ""
        return (bn or en) if g.lang == "bn" else (en or bn)

    def img_url(path, default="static/img/placeholder.svg"):
        path = path or default
        if path.startswith("static/"):
            return url_for("static", filename=path[7:])
        return url_for("uploads", path=path)

    def cart_count():
        return sum(_cart().values())

    @app.context_processor
    def _ctx():
        lang = g.get("lang", "bn")
        return dict(
            lang=lang, L=L, pick=pick, img_url=img_url, S=settings(),
            money=lambda n: util.money(n, lang), num=lambda n: util.num(n, lang),
            bn=lambda s: util.bn_digits(s) if lang == "bn" else str(s),
            fdate=lambda v, t=True: util.fmt_date(v, lang, t),
            csrf_token=sec.csrf_token, cart_count=cart_count, admin_path=admin_path,
            page_url=lambda n: url_for(request.endpoint, **{**(request.view_args or {}),
                                                              **{k: v for k, v in request.args.items() if k != 'page' and v}, 'page': n}),
            nav_categories=q("SELECT * FROM categories WHERE active=1 ORDER BY sort, id"),
            wa_link=lambda text="": "https://wa.me/%s%s" % (
                util.wa_number(settings()["whatsapp"]), ("?text=" + quote(text)) if text else ""),
            STATUSES=ORDER_STATUSES, STATUS_BN=STATUS_BN, year=util.now_bd()[:4],
        )

    @app.template_filter("rich")
    def rich(text):
        """Plain text -> safe HTML paragraphs; lines starting with '- ' become bullets."""
        out, bullets = [], []

        def flush():
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets.clear()

        for line in (text or "").replace("\r", "").split("\n"):
            line = line.strip()
            if line.startswith("- "):
                bullets.append(str(escape(line[2:])))
            elif not line:
                flush()
            else:
                flush()
                out.append(f"<p>{escape(line)}</p>")
        flush()
        return Markup("".join(out))

    # ----------------------------------------------------------- cart utils
    def _cart():
        raw = session.get("cart") or {}
        cart = {}
        for k, v in raw.items():
            try:
                cart[int(k)] = max(1, min(MAX_QTY, int(v)))
            except (TypeError, ValueError):
                continue
        return cart

    def _save_cart(cart):
        session["cart"] = {str(k): v for k, v in cart.items() if v > 0}
        session.permanent = True

    def cart_items():
        cart = _cart()
        if not cart:
            return [], 0
        ph = ",".join("?" * len(cart))
        rows = annotate(q(PRODUCT_SELECT + f" WHERE p.id IN ({ph})", tuple(cart)))
        items, subtotal = [], 0
        for p in rows:
            if not p["in_stock"]:
                continue
            qty = min(cart[p["id"]], p["stock"], MAX_QTY)
            line = p["sale"] * qty
            subtotal += line
            items.append(dict(p=p, qty=qty, line=line))
        return items, subtotal

    def delivery_for(area, subtotal):
        free_min = dbm.int_setting("free_delivery_min", 0)
        if free_min and subtotal >= free_min:
            return 0
        key = "delivery_dhaka" if area == "dhaka" else "delivery_outside"
        return dbm.int_setting(key, 0)

    # ================================================================ SHOP
    @app.route("/uploads/<path:path>")
    def uploads(path):
        if not path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            abort(404)
        resp = send_from_directory(app.config["UPLOAD_DIR"], path, max_age=60 * 60 * 24 * 7)
        return resp

    @app.route("/lang/<code>")
    def set_lang(code):
        resp = make_response(redirect(sec.safe_next(request.args.get("next"), "/")))
        if code in ("bn", "en"):
            resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="Lax", secure=https_only)
        return resp

    @app.route("/")
    def home():
        heroes = q("SELECT * FROM banners WHERE kind='hero' AND active=1 ORDER BY sort, id")
        promos = q("SELECT * FROM banners WHERE kind='promo' AND active=1 ORDER BY sort, id")
        cats = q("SELECT * FROM categories WHERE active=1 ORDER BY sort, id")
        featured = annotate(q(PRODUCT_SELECT + " WHERE p.featured=1 ORDER BY p.id DESC LIMIT 8"))
        trending = annotate(q(PRODUCT_SELECT + " WHERE p.trending=1 ORDER BY p.id DESC LIMIT 8"))
        newest = annotate(q(PRODUCT_SELECT + " ORDER BY p.id DESC LIMIT 8"))
        pool = annotate(q(PRODUCT_SELECT + " WHERE p.available=1 AND p.stock>0 ORDER BY p.id DESC LIMIT 80"))
        deals = sorted([p for p in pool if p["percent_off"]], key=lambda p: -p["percent_off"])[:8]
        reviews = q("""SELECT r.*, p.name_bn, p.name_en FROM reviews r JOIN products p ON p.id=r.product_id
                       WHERE r.status='approved' ORDER BY r.id DESC LIMIT 6""")
        return render_template("shop/home.html", heroes=heroes, promos=promos, cats=cats,
                               featured=featured, trending=trending, newest=newest, deals=deals,
                               reviews=reviews)

    def _search_where(text, args, where):
        for tok in [t for t in re.split(r"\s+", text.strip()) if t][:6]:
            like = "%" + util.like_escape(tok) + "%"
            where.append("(p.name_en LIKE ? ESCAPE '\\' OR p.name_bn LIKE ? ESCAPE '\\' OR p.brand LIKE ? ESCAPE '\\'"
                         " OR p.keywords LIKE ? ESCAPE '\\' OR c.name_en LIKE ? ESCAPE '\\' OR c.name_bn LIKE ? ESCAPE '\\')")
            args.extend([like] * 6)

    @app.route("/shop")
    @app.route("/category/<slug>")
    def shop(slug=None):
        text = request.args.get("q", "").strip()[:80]
        cat_slug = slug or request.args.get("cat", "")
        brand = request.args.get("brand", "").strip()[:60]
        sort = request.args.get("sort", "new")
        only_stock = request.args.get("stock") == "1"
        try:
            pmin = max(0, int(request.args.get("min") or 0))
            pmax = max(0, int(request.args.get("max") or 0))
        except ValueError:
            pmin = pmax = 0
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        where, args = ["1=1"], []
        category = None
        if cat_slug:
            category = q1("SELECT * FROM categories WHERE slug=? AND active=1", (cat_slug,))
            if not category:
                abort(404)
            where.append("p.category_id=?")
            args.append(category["id"])
        if text:
            _search_where(text, args, where)
        if brand:
            where.append("p.brand=?")
            args.append(brand)
        if pmin:
            where.append("p.price>=?")
            args.append(pmin)
        if pmax:
            where.append("p.price<=?")
            args.append(pmax)
        if only_stock:
            where.append("p.available=1 AND p.stock>0")
        order = {
            "new": "p.id DESC",
            "price_asc": "p.price ASC",
            "price_desc": "p.price DESC",
            "discount": "(p.old_price-p.price) DESC, p.id DESC",
            "popular": "(SELECT COALESCE(SUM(oi.qty),0) FROM order_items oi WHERE oi.product_id=p.id) DESC, p.id DESC",
        }.get(sort, "p.id DESC")
        base = PRODUCT_SELECT + " WHERE " + " AND ".join(where)
        total = q1("SELECT COUNT(*) AS c FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE "
                   + " AND ".join(where), args)["c"]
        pages = max(1, -(-total // PER_PAGE))
        page = min(page, pages)
        products = annotate(q(base + f" ORDER BY {order} LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}", args))
        brands = [r["brand"] for r in q("SELECT DISTINCT brand FROM products WHERE brand!='' ORDER BY brand")]
        qs = {k: v for k, v in request.args.items() if k != "page" and v}
        return render_template("shop/shop.html", products=products, total=total, page=page, pages=pages,
                               category=category, text=text, brand=brand, brands=brands, sort=sort,
                               pmin=pmin or "", pmax=pmax or "", only_stock=only_stock, qs=qs, cat_slug=cat_slug)

    @app.route("/api/search")
    def api_search():
        text = request.args.get("q", "").strip()[:60]
        if not text:  # focus on an empty box -> show popular picks
            cats = q("SELECT slug, name_bn, name_en FROM categories WHERE active=1 ORDER BY sort, id LIMIT 6")
            pop = annotate(q(PRODUCT_SELECT + " WHERE p.trending=1 OR p.featured=1 ORDER BY p.id DESC LIMIT 4"))
            return jsonify(q="", popular=True,
                           products=[dict(id=p["id"], name=pick(p, "name"), price=util.money(p["sale"], g.lang),
                                          old=util.money(p["compare"], g.lang) if p["compare"] else "",
                                          image=img_url(p["image"]), url=url_for("product", pid=p["id"]),
                                          in_stock=p["in_stock"]) for p in pop],
                           categories=[dict(name=pick(c, "name"), url=url_for("shop", slug=c["slug"])) for c in cats],
                           brands=[])
        where, args = ["1=1"], []
        _search_where(text, args, where)
        first = util.like_escape(text.split()[0]) + "%"
        rows = annotate(q(PRODUCT_SELECT + " WHERE " + " AND ".join(where) +
                          " ORDER BY (p.name_en LIKE ? ESCAPE '\\' OR p.name_bn LIKE ? ESCAPE '\\') DESC, p.id DESC LIMIT 6",
                          args + [first, first]))
        like = "%" + util.like_escape(text) + "%"
        cats = q("SELECT slug, name_bn, name_en FROM categories WHERE active=1 AND "
                 "(name_bn LIKE ? ESCAPE '\\' OR name_en LIKE ? ESCAPE '\\') LIMIT 3", (like, like))
        brands = q("SELECT DISTINCT brand FROM products WHERE brand!='' AND brand LIKE ? ESCAPE '\\' LIMIT 3", (like,))
        return jsonify(
            q=text,
            products=[dict(id=p["id"], name=pick(p, "name"), price=util.money(p["sale"], g.lang),
                           old=util.money(p["compare"], g.lang) if p["compare"] else "",
                           image=img_url(p["image"]), url=url_for("product", pid=p["id"]),
                           in_stock=p["in_stock"]) for p in rows],
            categories=[dict(name=pick(c, "name"), url=url_for("shop", slug=c["slug"])) for c in cats],
            brands=[dict(name=b["brand"], url=url_for("shop", brand=b["brand"])) for b in brands],
        )

    @app.route("/product/<int:pid>")
    def product(pid):
        row = q1(PRODUCT_SELECT + " WHERE p.id=?", (pid,))
        if not row:
            abort(404)
        p = annotate([row])[0]
        reviews = q("SELECT * FROM reviews WHERE product_id=? AND status='approved' ORDER BY id DESC", (pid,))
        related = annotate(q(PRODUCT_SELECT + " WHERE p.category_id=? AND p.id!=? ORDER BY p.id DESC LIMIT 4",
                             (p["category_id"], pid)))
        return render_template("shop/product.html", p=p, reviews=reviews, related=related)

    @app.route("/product/<int:pid>/review", methods=["POST"])
    def add_review(pid):
        if not q1("SELECT id FROM products WHERE id=?", (pid,)):
            abort(404)
        name = request.form.get("name", "").strip()[:60]
        comment = request.form.get("comment", "").strip()[:600]
        try:
            rating = int(request.form.get("rating", 0))
        except ValueError:
            rating = 0
        ident = "review|" + sec.ip_hash()
        if request.form.get("website"):  # honeypot
            return redirect(url_for("product", pid=pid))
        if not name or not (1 <= rating <= 5):
            flash(L("নাম ও রেটিং দিন।", "Please enter your name and a rating."), "error")
        elif sec.rate_count(ident, 3600) >= 5:
            flash(L("অনেক বেশি রিভিউ জমা হয়েছে, পরে চেষ্টা করুন।", "Too many reviews, please try later."), "error")
        else:
            sec.rate_hit(ident)
            ex("INSERT INTO reviews(product_id,name,rating,comment,ip_hash,created_at) VALUES(?,?,?,?,?,?)",
               (pid, name, rating, comment, sec.ip_hash(), util.now_bd()))
            flash(L("ধন্যবাদ! আপনার রিভিউ যাচাইয়ের পর প্রকাশ করা হবে।",
                    "Thank you! Your review will appear after approval."), "success")
        g.db.commit()
        return redirect(url_for("product", pid=pid) + "#reviews")

    # ------------------------------------------------------------- cart
    def _wants_json():
        return request.headers.get("X-Requested-With") == "fetch"

    @app.route("/cart")
    def cart():
        items, subtotal = cart_items()
        return render_template("shop/cart.html", items=items, subtotal=subtotal,
                               free_min=dbm.int_setting("free_delivery_min", 0))

    @app.route("/cart/add", methods=["POST"])
    def cart_add():
        try:
            pid = int(request.form.get("pid", 0))
            qty = max(1, min(MAX_QTY, int(request.form.get("qty", 1))))
        except ValueError:
            abort(400)
        row = q1("SELECT id, stock, available FROM products WHERE id=?", (pid,))
        ok, msg = False, L("পণ্যটি স্টকে নেই।", "This product is out of stock.")
        cart = _cart()
        if row and row["available"] and row["stock"] > 0:
            cart[pid] = min(cart.get(pid, 0) + qty, row["stock"], MAX_QTY)
            _save_cart(cart)
            ok, msg = True, L("কার্টে যোগ হয়েছে ✓", "Added to cart ✓")
        if _wants_json():
            return jsonify(ok=ok, message=msg, count=sum(_cart().values()))
        flash(msg, "success" if ok else "error")
        return redirect(sec.safe_next(request.form.get("next"), url_for("cart")))

    @app.route("/cart/update", methods=["POST"])
    def cart_update():
        cart = _cart()
        for key, val in request.form.items():
            if key.startswith("qty_"):
                try:
                    pid, qty = int(key[4:]), int(val)
                except ValueError:
                    continue
                if pid in cart:
                    cart[pid] = max(0, min(MAX_QTY, qty))
        _save_cart(cart)
        return redirect(url_for("cart"))

    @app.route("/cart/remove", methods=["POST"])
    def cart_remove():
        cart = _cart()
        try:
            cart.pop(int(request.form.get("pid", 0)), None)
        except ValueError:
            pass
        _save_cart(cart)
        return redirect(url_for("cart"))

    @app.route("/buy-now", methods=["POST"])
    def buy_now():
        try:
            pid = int(request.form.get("pid", 0))
            qty = max(1, min(MAX_QTY, int(request.form.get("qty", 1))))
        except ValueError:
            abort(400)
        row = q1("SELECT id, stock, available FROM products WHERE id=?", (pid,))
        if not row or not row["available"] or row["stock"] < 1:
            flash(L("পণ্যটি স্টকে নেই।", "This product is out of stock."), "error")
            return redirect(url_for("product", pid=pid))
        _save_cart({pid: min(qty, row["stock"])})
        return redirect(url_for("checkout"))

    # --------------------------------------------------------- checkout
    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        items, subtotal = cart_items()
        if not items:
            flash(L("আপনার কার্ট খালি।", "Your cart is empty."), "error")
            return redirect(url_for("cart"))
        saved = session.get("checkout", {})
        form = dict(name=saved.get("name", ""), phone=saved.get("phone", ""), address=saved.get("address", ""),
                    area=saved.get("area", "dhaka"), note="")
        errors = {}
        if request.method == "POST":
            form = {k: request.form.get(k, "").strip() for k in ("name", "phone", "address", "area", "note")}
            if request.form.get("website"):  # honeypot field – bots fill it in
                abort(400)
            if len(form["name"]) < 2:
                errors["name"] = L("আপনার নাম লিখুন", "Please enter your name")
            phone = util.normalize_phone(form["phone"])
            if not phone:
                errors["phone"] = L("সঠিক মোবাইল নম্বর দিন (যেমন 017XXXXXXXX)", "Enter a valid mobile number (e.g. 017XXXXXXXX)")
            if len(form["address"]) < 10:
                errors["address"] = L("সম্পূর্ণ ঠিকানা লিখুন (এলাকা, থানা, জেলা)", "Enter your full address (area, thana, district)")
            if form["area"] not in ("dhaka", "outside"):
                form["area"] = "dhaka"
            form["name"], form["address"], form["note"] = form["name"][:80], form["address"][:300], form["note"][:300]
            ihash = sec.ip_hash()
            if not errors and sec.rate_count("order|" + ihash, 3600) >= 8:
                errors["form"] = L("অনেক বেশি অর্ডার করা হয়েছে। কিছুক্ষণ পর চেষ্টা করুন বা আমাদের কল করুন।",
                                   "Too many orders from this connection. Please try later or call us.")
            if not errors:
                number = _place_order(items, form, phone, ihash, errors)
                if number:
                    session["last_order"] = number
                    session["checkout"] = dict(name=form["name"], phone=phone, address=form["address"], area=form["area"])
                    _save_cart({})
                    return redirect(url_for("order_done", number=number))
        delivery = delivery_for(form["area"], subtotal)
        return render_template("shop/checkout.html", items=items, subtotal=subtotal, form=form, errors=errors,
                               delivery=delivery, total=subtotal + delivery,
                               d_dhaka=delivery_for("dhaka", subtotal), d_out=delivery_for("outside", subtotal))

    def _place_order(items, form, phone, ihash, errors):
        db = dbm.get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            # re-check stock inside the transaction – prices always come from the database
            lines, subtotal = [], 0
            for it in items:
                row = db.execute("SELECT * FROM products WHERE id=?", (it["p"]["id"],)).fetchone()
                if not row or not row["available"] or row["stock"] < it["qty"]:
                    db.execute("ROLLBACK")
                    pname = pick(dict(row), "name") if row else L("একটি পণ্য", "an item")
                    errors["form"] = L("দুঃখিত, '%s' এর স্টক শেষ বা কম আছে। কার্ট আপডেট করুন।" % pname,
                                       "Sorry, '%s' is out of stock or low. Please update your cart." % pname)
                    return None
                p = annotate([row])[0]
                lines.append((row, p["sale"], it["qty"]))
                subtotal += p["sale"] * it["qty"]
            delivery = delivery_for(form["area"], subtotal)
            now = util.now_bd()
            db.execute("""INSERT INTO customers(name,phone,address,created_at) VALUES(?,?,?,?)
                          ON CONFLICT(phone) DO UPDATE SET name=excluded.name, address=excluded.address""",
                       (form["name"], phone, form["address"], now))
            cust = db.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone()["id"]
            while True:
                number = "BBD-%s-%s" % (now[2:10].replace("-", ""), "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)))
                if not db.execute("SELECT 1 FROM orders WHERE number=?", (number,)).fetchone():
                    break
            cur = db.execute(
                """INSERT INTO orders(number,customer_id,name,phone,address,area,note,subtotal,delivery,total,payment,status,ip_hash,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,'cod','pending',?,?)""",
                (number, cust, form["name"], phone, form["address"], form["area"], form["note"], subtotal,
                 delivery, subtotal + delivery, ihash, now))
            oid = cur.lastrowid
            for row, price, qty in lines:
                name = row["name_bn"] or row["name_en"]
                if row["name_en"] and row["name_bn"]:
                    name = f"{row['name_en']} / {row['name_bn']}"
                db.execute("INSERT INTO order_items(order_id,product_id,name,price,qty) VALUES(?,?,?,?,?)",
                           (oid, row["id"], name, price, qty))
                db.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, row["id"]))
            db.execute("INSERT INTO order_history(order_id,status,note,admin,created_at) VALUES(?,?,?,?,?)",
                       (oid, "pending", "Order placed by customer", "", now))
            db.execute("INSERT INTO login_attempts(ident,ts) VALUES(?,?)", ("order|" + ihash, int(time.time())))
            db.execute("COMMIT")
        except Exception:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
            app.logger.exception("order failed")
            errors["form"] = L("দুঃখিত, অর্ডার সম্পন্ন হয়নি। আবার চেষ্টা করুন।", "Sorry, we could not place the order. Please try again.")
            return None
        if os.environ.get("SMTP_HOST") and settings().get("email"):
            util.send_mail(settings()["email"], f"New order {number}",
                           f"{form['name']} / {phone}\n{form['address']}\nTotal: {subtotal + delivery} BDT (COD)",
                           app.config["DATA_DIR"])
        return number

    @app.route("/order/<number>")
    def order_done(number):
        if session.get("last_order") != number:
            return redirect(url_for("track", number=number))
        order = q1("SELECT * FROM orders WHERE number=?", (number,))
        if not order:
            abort(404)
        items = q("SELECT * FROM order_items WHERE order_id=?", (order["id"],))
        lines = "\n".join(f"- {i['name']} x{i['qty']}" for i in items)
        wa_text = f"Order {order['number']}\n{lines}\nTotal: {order['total']} BDT (COD)\nName: {order['name']}\nPhone: {order['phone']}"
        return render_template("shop/order.html", order=order, items=items, wa_text=wa_text)

    @app.route("/track", methods=["GET", "POST"])
    def track():
        order, history, items, error = None, [], [], None
        number = (request.values.get("number") or "").strip().upper()[:30]
        if request.method == "POST":
            ident = "track|" + sec.ip_hash()
            phone = util.normalize_phone(request.form.get("phone", ""))
            if sec.rate_count(ident, 600) >= 15:
                error = L("অনেকবার চেষ্টা হয়েছে, কিছুক্ষণ পর আবার চেষ্টা করুন।", "Too many attempts, try again shortly.")
            else:
                sec.rate_hit(ident)
                order = q1("SELECT * FROM orders WHERE number=? AND phone=?", (number, phone or "")) if phone else None
                if order:
                    history = q("SELECT * FROM order_history WHERE order_id=? ORDER BY id", (order["id"],))
                    items = q("SELECT * FROM order_items WHERE order_id=?", (order["id"],))
                else:
                    error = L("অর্ডার নম্বর ও মোবাইল নম্বর মিলছে না।", "Order number and mobile number do not match.")
            g.db.commit()
        return render_template("shop/track.html", order=order, history=history, items=items, error=error, number=number)

    # ------------------------------------------------------------ pages
    @app.route("/about")
    def about():
        return render_template("shop/page.html", title=L("আমাদের সম্পর্কে", "About Us"),
                               body=settings()["about_" + g.lang], kind="about")

    @app.route("/contact")
    def contact():
        return render_template("shop/contact.html")

    @app.route("/return-policy")
    def return_policy():
        return render_template("shop/page.html", title=L("রিটার্ন ও রিফান্ড পলিসি", "Return & Refund Policy"),
                               body=settings()["return_" + g.lang], kind="policy")

    @app.route("/privacy-policy")
    def privacy_policy():
        return render_template("shop/page.html", title=L("প্রাইভেসি পলিসি", "Privacy Policy"),
                               body=settings()["privacy_" + g.lang], kind="policy")

    # ---------------------------------------------------------- errors
    @app.errorhandler(400)
    def e400(_e):
        return render_template("shop/error.html", code=400,
                               msg=L("অনুরোধটি সম্পন্ন করা যায়নি। পেজটি রিফ্রেশ করে আবার চেষ্টা করুন।",
                                     "The request could not be completed. Please refresh the page and try again.")), 400

    @app.errorhandler(404)
    def e404(_e):
        return render_template("shop/error.html", code=404, msg=L("পেজটি খুঁজে পাওয়া যায়নি।", "Page not found.")), 404

    @app.errorhandler(413)
    def e413(_e):
        return render_template("shop/error.html", code=413, msg=L("ফাইলটি অনেক বড়।", "The file is too large.")), 413

    @app.errorhandler(500)
    def e500(_e):
        return render_template("shop/error.html", code=500, msg=L("সাময়িক সমস্যা হয়েছে। একটু পরে চেষ্টা করুন।", "Something went wrong. Please try again soon.")), 500

    # ------------------------------------------------------------ admin
    from admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix=admin_path)
    return app


app = create_app()


def _cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        host = os.environ.get("HOST", "127.0.0.1")
        port = int(os.environ.get("PORT", "5000"))
        print(f"\n  BIG BAZAR BD running →  http://{host}:{port}   (admin: {app.config['ADMIN_PATH']}/login)\n")
        app.run(host=host, port=port, debug=bool(os.environ.get("DEBUG")), threaded=True)
    elif cmd in ("create-admin", "reset-password"):
        import sqlite3
        username = input("Admin username: ").strip() or "admin"
        pw = getpass.getpass("New password (min 10 chars, letters+numbers): ")
        problem = sec.password_problem(pw)
        if problem:
            sys.exit(problem)
        if pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
        conn = sqlite3.connect(app.config["DB_PATH"])
        row = conn.execute("SELECT id FROM admins WHERE username=?", (username,)).fetchone()
        if row:
            conn.execute("UPDATE admins SET password_hash=? WHERE id=?", (generate_password_hash(pw), row[0]))
            print("Password updated for", username)
        else:
            email = input("Email: ").strip()
            conn.execute("INSERT INTO admins(username,email,password_hash,created_at) VALUES(?,?,?,?)",
                         (username, email, generate_password_hash(pw), util.now_bd()))
            print("Admin created:", username)
        conn.commit()
    else:
        print("Usage: python app.py [run | create-admin | reset-password]")


if __name__ == "__main__":
    _cli()
