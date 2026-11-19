"""Admin panel – secure login, dashboard, catalogue, orders, reports, settings."""
import csv
import hashlib
import io
import secrets
import time
from datetime import datetime, timedelta

from flask import (Blueprint, g, request, session, redirect, url_for, render_template, abort,
                   flash, current_app, make_response)
from werkzeug.security import generate_password_hash, check_password_hash

import db as dbm
import sec
import util
from db import q, q1, ex, ORDER_STATUSES

bp = Blueprint("admin", __name__)
PUBLIC = {"admin.login", "admin.forgot", "admin.reset"}
IDLE_SECONDS = 2 * 60 * 60
PER_PAGE = 20
_DUMMY_HASH = generate_password_hash("not-the-password")  # equalises timing for unknown usernames


# ===================================================================== auth
@bp.before_request
def guard():
    if request.endpoint in PUBLIC:
        return None
    aid = session.get("admin_id")
    row = q1("SELECT * FROM admins WHERE id=?", (aid,)) if aid else None
    if (not row or session.get("admin_fp") != sec.pw_fingerprint(row["password_hash"])
            or time.time() - session.get("admin_ts", 0) > IDLE_SECONDS):
        session.pop("admin_id", None)
        if request.method == "GET":
            return redirect(url_for("admin.login", next=request.path))
        return redirect(url_for("admin.login"))
    session["admin_ts"] = int(time.time())
    g.admin = row
    return None


@bp.context_processor
def _admin_ctx():
    pending = 0
    if session.get("admin_id"):
        pending = q1("SELECT COUNT(*) AS c FROM orders WHERE status='pending'")["c"]
    # the admin panel always shows English digits so numbers are easy to scan and copy
    return dict(pending_orders=pending, admin_user=g.get("admin"), lang="en",
                money=lambda n: util.money(n, "en"), num=lambda n: util.num(n, "en"),
                fdate=lambda v, t=True: util.fmt_date(v, "en", t))


def _page(total):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, -(-total // PER_PAGE))
    page = min(page, pages)
    return page, pages, (page - 1) * PER_PAGE


def _int(name, default=0, lo=None, hi=None):
    try:
        v = int(str(request.form.get(name, default)).strip() or default)
    except ValueError:
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _upload_dir():
    return current_app.config["UPLOAD_DIR"]


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id") and request.method == "GET":
        return redirect(url_for("admin.dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()[:60]
        password = request.form.get("password", "")[:200]
        ih = sec.ip_hash()
        id_ip, id_user = f"login|{ih}", f"login|{ih}|{username.lower()}"
        if sec.rate_count(id_ip, 900) >= 20 or sec.rate_count(id_user, 900) >= 5:
            error = "Too many failed attempts. Please wait 15 minutes and try again."
        else:
            row = q1("SELECT * FROM admins WHERE username=?", (username,))
            ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password) and bool(row)
            if ok:
                session.clear()                       # prevents session fixation
                session["admin_id"] = row["id"]
                session["admin_fp"] = sec.pw_fingerprint(row["password_hash"])
                session["admin_ts"] = int(time.time())
                sec.csrf_token()
                sec.rate_clear(id_user)
                nxt = request.args.get("next", "")
                if nxt.startswith(current_app.config["ADMIN_PATH"] + "/") and sec.safe_next(nxt, "") == nxt:
                    return redirect(nxt)
                return redirect(url_for("admin.dashboard"))
            sec.rate_hit(id_ip)
            sec.rate_hit(id_user)
            error = "Invalid username or password."
    return render_template("admin/login.html", error=error)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("admin.login"))


def _public_url():
    import os
    return (os.environ.get("PUBLIC_URL") or request.host_url).rstrip("/")


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent = False
    if request.method == "POST":
        ident = "forgot|" + sec.ip_hash()
        if sec.rate_count(ident, 3600) < 5:
            sec.rate_hit(ident)
            who = request.form.get("who", "").strip()[:120]
            row = q1("SELECT * FROM admins WHERE username=? OR email=?", (who, who)) if who else None
            if row:
                token = secrets.token_urlsafe(32)
                ex("INSERT INTO reset_tokens(admin_id, token_hash, expires) VALUES(?,?,?)",
                   (row["id"], hashlib.sha256(token.encode()).hexdigest(), int(time.time()) + 1800))
                link = f"{_public_url()}{current_app.config['ADMIN_PATH']}/reset/{token}"
                util.send_mail(row["email"], "BIG BAZAR BD – reset your admin password",
                               f"Open this link within 30 minutes to set a new password:\n\n{link}\n\n"
                               "If you did not ask for this, ignore this message.", current_app.config["DATA_DIR"])
        sent = True  # same answer whether or not the account exists
    return render_template("admin/forgot.html", sent=sent)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    th = hashlib.sha256(token.encode()).hexdigest()
    row = q1("SELECT * FROM reset_tokens WHERE token_hash=? AND used=0 AND expires>?", (th, int(time.time())))
    if not row:
        return render_template("admin/reset.html", invalid=True, error=None)
    error = None
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        error = sec.password_problem(pw) or (None if pw == pw2 else "Passwords do not match.")
        if not error:
            ex("UPDATE admins SET password_hash=? WHERE id=?", (generate_password_hash(pw), row["admin_id"]))
            ex("UPDATE reset_tokens SET used=1 WHERE admin_id=?", (row["admin_id"],))
            session.clear()
            flash("Password changed. Please log in.", "success")
            return redirect(url_for("admin.login"))
    return render_template("admin/reset.html", invalid=False, error=error)


@bp.route("/account", methods=["GET", "POST"])
def account():
    error = None
    if request.method == "POST":
        cur, pw, pw2 = request.form.get("current", ""), request.form.get("password", ""), request.form.get("password2", "")
        email = request.form.get("email", "").strip()[:120]
        if not check_password_hash(g.admin["password_hash"], cur):
            error = "Current password is wrong."
        elif pw and (sec.password_problem(pw) or pw != pw2):
            error = sec.password_problem(pw) or "New passwords do not match."
        elif "@" not in email:
            error = "Enter a valid email address."
        else:
            new_hash = generate_password_hash(pw) if pw else g.admin["password_hash"]
            ex("UPDATE admins SET password_hash=?, email=? WHERE id=?", (new_hash, email, g.admin["id"]))
            session["admin_fp"] = sec.pw_fingerprint(new_hash)
            flash("Account updated.", "success")
            return redirect(url_for("admin.account"))
    return render_template("admin/account.html", error=error)


# ================================================================ dashboard
def _series(days=14):
    end = datetime.now(util.BD_TZ).date()
    start = end - timedelta(days=days - 1)
    rows = q("""SELECT substr(created_at,1,10) d, COUNT(*) n, COALESCE(SUM(total),0) s FROM orders
                WHERE status!='cancelled' AND substr(created_at,1,10)>=? GROUP BY d""", (start.isoformat(),))
    m = {r["d"]: r for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        out.append(dict(date=d, label=d[8:] + "/" + d[5:7], orders=m[d]["n"] if d in m else 0,
                        revenue=m[d]["s"] if d in m else 0))
    return out


def _best_sellers(limit=5, since=None, until=None):
    sql = """SELECT oi.name, SUM(oi.qty) AS qty, SUM(oi.qty*oi.price) AS revenue, MAX(oi.product_id) AS pid
             FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status!='cancelled'"""
    args = []
    if since:
        sql += " AND substr(o.created_at,1,10)>=?"
        args.append(since)
    if until:
        sql += " AND substr(o.created_at,1,10)<=?"
        args.append(until)
    sql += " GROUP BY oi.name ORDER BY qty DESC, revenue DESC LIMIT ?"
    return q(sql, args + [limit])


@bp.route("/")
def dashboard():
    rev = q1("SELECT COALESCE(SUM(total),0) s FROM orders WHERE status!='cancelled'")["s"]
    stats = dict(
        revenue=rev,
        orders=q1("SELECT COUNT(*) c FROM orders")["c"],
        sold=q1("""SELECT COALESCE(SUM(oi.qty),0) c FROM order_items oi JOIN orders o ON o.id=oi.order_id
                   WHERE o.status!='cancelled'""")["c"],
        customers=q1("SELECT COUNT(*) c FROM customers")["c"],
        pending=q1("SELECT COUNT(*) c FROM orders WHERE status='pending'")["c"],
        delivered=q1("SELECT COUNT(*) c FROM orders WHERE status='delivered'")["c"],
        low=q1("SELECT COUNT(*) c FROM products WHERE stock<=5")["c"],
    )
    by_status = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM orders GROUP BY status")}
    recent = q("SELECT * FROM orders ORDER BY id DESC LIMIT 8")
    chart = dict(series=_series(14), status=[dict(s=s, n=by_status.get(s, 0)) for s in ORDER_STATUSES])
    return render_template("admin/dashboard.html", stats=stats, recent=recent, chart=chart,
                           best=_best_sellers(5), low_products=q("SELECT id,name_en,name_bn,stock FROM products WHERE stock<=5 ORDER BY stock LIMIT 5"))


# =================================================================== products
def _categories():
    return q("SELECT id, name_en, name_bn FROM categories ORDER BY sort, id")


@bp.route("/products")
def products():
    text = request.args.get("q", "").strip()[:80]
    cat = request.args.get("cat", "")
    stock = request.args.get("stock", "")
    where, args = ["1=1"], []
    if text:
        like = "%" + util.like_escape(text) + "%"
        where.append("(p.name_en LIKE ? ESCAPE '\\' OR p.name_bn LIKE ? ESCAPE '\\' OR p.brand LIKE ? ESCAPE '\\')")
        args += [like] * 3
    if cat.isdigit():
        where.append("p.category_id=?")
        args.append(int(cat))
    if stock == "out":
        where.append("(p.stock<=0 OR p.available=0)")
    elif stock == "low":
        where.append("p.stock>0 AND p.stock<=5")
    elif stock == "in":
        where.append("p.stock>0 AND p.available=1")
    cond = " AND ".join(where)
    total = q1(f"SELECT COUNT(*) c FROM products p WHERE {cond}", args)["c"]
    page, pages, off = _page(total)
    rows = q(f"""SELECT p.*, c.name_en AS cat_en, c.name_bn AS cat_bn FROM products p
                 LEFT JOIN categories c ON c.id=p.category_id WHERE {cond}
                 ORDER BY p.id DESC LIMIT {PER_PAGE} OFFSET {off}""", args)
    return render_template("admin/products.html", rows=rows, total=total, page=page, pages=pages,
                           cats=_categories(), text=text, cat=cat, stock=stock,
                           qs={k: v for k, v in request.args.items() if k != "page" and v})


def _read_product(existing=None):
    f = request.form
    data = dict(
        name_bn=f.get("name_bn", "").strip()[:150], name_en=f.get("name_en", "").strip()[:150],
        brand=f.get("brand", "").strip()[:60], keywords=f.get("keywords", "").strip()[:500],
        desc_bn=f.get("desc_bn", "").strip()[:3000], desc_en=f.get("desc_en", "").strip()[:3000],
        price=_int("price", 0, 0, 10_000_000), old_price=_int("old_price", 0, 0, 10_000_000),
        stock=_int("stock", 0, 0, 1_000_000),
        category_id=_int("category_id", 0) or None,
        available=1 if f.get("available") else 0, featured=1 if f.get("featured") else 0,
        trending=1 if f.get("trending") else 0,
    )
    errors = []
    if not (data["name_bn"] or data["name_en"]):
        errors.append("Enter a product name (Bangla or English).")
    if data["price"] < 1:
        errors.append("Price must be at least ৳1.")
    if data["old_price"] and data["old_price"] <= data["price"]:
        errors.append("Previous price must be higher than the selling price (or leave it 0).")
    return data, errors


@bp.route("/products/new", methods=["GET", "POST"])
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def product_form(pid=None):
    existing = q1("SELECT * FROM products WHERE id=?", (pid,)) if pid else None
    if pid and not existing:
        abort(404)
    data = dict(existing) if existing else dict(available=1, stock=10, price="", old_price=0, category_id=None)
    errors = []
    if request.method == "POST":
        data, errors = _read_product(existing)
        data["image"] = existing["image"] if existing else ""
        new_img = None
        try:
            new_img = util.save_image(request.files.get("image"), _upload_dir(), "products")
        except util.UploadError as e:
            errors.append(str(e))
        if not errors:
            if new_img:
                util.delete_upload(_upload_dir(), data["image"])
                data["image"] = new_img
            cols = ["category_id", "name_bn", "name_en", "brand", "desc_bn", "desc_en", "price", "old_price",
                    "stock", "available", "image", "featured", "trending", "keywords"]
            if existing:
                ex(f"UPDATE products SET {','.join(c + '=?' for c in cols)} WHERE id=?",
                   [data[c] for c in cols] + [pid])
                flash("Product updated.", "success")
            else:
                ex(f"INSERT INTO products({','.join(cols)},created_at) VALUES({','.join('?' * len(cols))},?)",
                   [data[c] for c in cols] + [util.now_bd()])
                flash("Product added.", "success")
            return redirect(url_for("admin.products"))
        elif new_img:
            util.delete_upload(_upload_dir(), new_img)
        data["id"] = pid
        data["image"] = existing["image"] if existing else ""
    return render_template("admin/product_form.html", d=data, errors=errors, cats=_categories(), editing=bool(pid))


@bp.route("/products/<int:pid>/stock", methods=["POST"])
def product_stock(pid):
    row = q1("SELECT * FROM products WHERE id=?", (pid,))
    if not row:
        abort(404)
    action = request.form.get("action", "save")
    if action == "toggle":
        ex("UPDATE products SET available=? WHERE id=?", (0 if row["available"] else 1, pid))
    else:
        ex("UPDATE products SET stock=? WHERE id=?", (_int("stock", row["stock"], 0, 1_000_000), pid))
    flash("Stock updated.", "success")
    return redirect(util_back("admin.products"))


def util_back(default_endpoint):
    return sec.safe_next(request.form.get("next"), url_for(default_endpoint))


@bp.route("/products/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    row = q1("SELECT * FROM products WHERE id=?", (pid,))
    if row:
        ex("DELETE FROM products WHERE id=?", (pid,))
        util.delete_upload(_upload_dir(), row["image"])
        flash("Product deleted.", "success")
    return redirect(url_for("admin.products"))


# ======================================== categories / banners / campaigns
class Fld:
    def __init__(self, name, label, kind="text", required=False, help="", choices=None, default="", maxlen=200,
                 lo=None, hi=None):
        self.name, self.label, self.kind, self.required = name, label, kind, required
        self.help, self.choices, self.default, self.maxlen, self.lo, self.hi = help, choices, default, maxlen, lo, hi


RES = {
    "categories": dict(
        table="categories", singular="Category", title="Categories", bn="ক্যাটাগরি", image="image", subdir="categories",
        order="sort, id",
        fields=[Fld("name_bn", "Name (Bangla)", required=True, maxlen=80), Fld("name_en", "Name (English)", required=True, maxlen=80),
                Fld("sort", "Sort order", "number", default=0, help="Smaller number shows first."),
                Fld("active", "Show on website", "checkbox", default=1),
                Fld("image", "Category image", "image", help="Square image looks best (shown as a circle on the homepage).")],
        cols=[("image", "Image", "image"), ("name_en", "Name", "text2"), ("sort", "Order", "text"), ("active", "Visible", "bool")]),
    "banners": dict(
        table="banners", singular="Banner", title="Banners & Offers", bn="ব্যানার ও অফার", image="image", subdir="banners",
        order="kind, sort, id",
        fields=[Fld("kind", "Type", "select", choices=[("hero", "Hero slider (top of homepage)"), ("promo", "Promo card (middle of homepage)")], default="hero"),
                Fld("title_bn", "Title (Bangla)", maxlen=120), Fld("title_en", "Title (English)", maxlen=120),
                Fld("sub_bn", "Sub-text (Bangla)", maxlen=200), Fld("sub_en", "Sub-text (English)", maxlen=200),
                Fld("button_bn", "Button text (Bangla)", maxlen=40), Fld("button_en", "Button text (English)", maxlen=40),
                Fld("link", "Link", default="/shop", help="Example: /shop or /category/electronics or a full https:// link."),
                Fld("theme", "Colour theme (used when no image)", "select", choices=[("orange", "Orange"), ("brown", "Dark brown"), ("yellow", "Yellow")], default="orange"),
                Fld("sort", "Sort order", "number", default=0), Fld("active", "Show on website", "checkbox", default=1),
                Fld("image", "Banner image (optional)", "image", help="Wide image ~1400×500 for hero, ~700×400 for promo. If empty, the colour theme + text is used.")],
        cols=[("image", "Image", "image"), ("title_en", "Title", "text2"), ("kind", "Type", "text"), ("sort", "Order", "text"), ("active", "Visible", "bool")]),
    "campaigns": dict(
        table="campaigns", singular="Campaign", title="Discount Campaigns", bn="ডিসকাউন্ট ক্যাম্পেইন", image=None, subdir=None,
        order="id DESC",
        sql="SELECT t.*, COALESCE(c.name_en,'All products') AS cat_name FROM campaigns t LEFT JOIN categories c ON c.id=t.category_id ORDER BY t.id DESC",
        fields=[Fld("title_bn", "Campaign name (Bangla)", maxlen=100), Fld("title_en", "Campaign name (English)", required=True, maxlen=100),
                Fld("percent", "Discount %", "number", required=True, lo=1, hi=90, help="Applied automatically on top of the product's selling price."),
                Fld("category_id", "Applies to", "select", choices="categories", help="Choose one category or all products."),
                Fld("start_date", "Start date", "date", help="Leave empty to start immediately."),
                Fld("end_date", "End date", "date", help="Leave empty for no end date."),
                Fld("active", "Active", "checkbox", default=1)],
        cols=[("title_en", "Campaign", "text2"), ("percent", "Discount", "pct"), ("cat_name", "Applies to", "text"),
              ("end_date", "Ends", "text"), ("active", "Active", "bool")]),
}


def _res(res):
    if res not in RES:
        abort(404)
    return RES[res]


@bp.route("/<res>", endpoint="res_list")
def res_list(res):
    cfg = _res(res)
    rows = q(cfg.get("sql") or f"SELECT * FROM {cfg['table']} ORDER BY {cfg['order']}")
    return render_template("admin/list.html", res=res, cfg=cfg, rows=rows)


def _fld_choices(f):
    if f.choices == "categories":
        return [("0", "All products")] + [(str(c["id"]), f"{c['name_en']} / {c['name_bn']}") for c in _categories()]
    return f.choices


@bp.route("/<res>/new", methods=["GET", "POST"], endpoint="res_form")
@bp.route("/<res>/<int:rid>/edit", methods=["GET", "POST"], endpoint="res_form")
def res_form(res, rid=None):
    cfg = _res(res)
    existing = q1(f"SELECT * FROM {cfg['table']} WHERE id=?", (rid,)) if rid else None
    if rid and not existing:
        abort(404)
    data = dict(existing) if existing else {f.name: f.default for f in cfg["fields"]}
    if data.get("category_id") is None and res == "campaigns":
        data["category_id"] = 0
    errors = []
    if request.method == "POST":
        vals = {}
        for f in cfg["fields"]:
            if f.kind == "image":
                continue
            raw = request.form.get(f.name, "")
            if f.kind == "checkbox":
                vals[f.name] = 1 if request.form.get(f.name) else 0
            elif f.kind == "number" or (f.kind == "select" and f.choices == "categories"):
                try:
                    vals[f.name] = int(raw or 0)
                except ValueError:
                    vals[f.name] = 0
                    errors.append(f"{f.label}: enter a whole number.")
                else:
                    if f.lo is not None and vals[f.name] < f.lo or f.hi is not None and vals[f.name] > f.hi:
                        errors.append(f"{f.label}: must be between {f.lo} and {f.hi}.")
            else:
                vals[f.name] = raw.strip()[:f.maxlen]
                if f.kind == "select" and f.choices != "categories" and vals[f.name] not in [c[0] for c in f.choices]:
                    errors.append(f"{f.label}: invalid choice.")
            if f.required and not vals.get(f.name) and f.kind != "checkbox":
                errors.append(f"{f.label} is required.")
        if res == "banners":
            link = vals.get("link", "")
            if not ((link.startswith("/") and not link.startswith("//")) or link.startswith(("http://", "https://"))):
                errors.append("Link must start with / or https://")
        if res == "campaigns":
            vals["category_id"] = vals.get("category_id") or None
            s, e = vals.get("start_date", ""), vals.get("end_date", "")
            if s and e and e < s:
                errors.append("End date must be after the start date.")
        new_img = None
        if cfg["image"]:
            try:
                new_img = util.save_image(request.files.get("image"), _upload_dir(), cfg["subdir"])
            except util.UploadError as e:
                errors.append(str(e))
        if not errors:
            if cfg["image"]:
                vals["image"] = existing[cfg["image"]] if existing else ""
                if new_img:
                    util.delete_upload(_upload_dir(), vals["image"])
                    vals["image"] = new_img
                elif request.form.get("remove_image") and vals["image"]:
                    util.delete_upload(_upload_dir(), vals["image"])
                    vals["image"] = ""
            if res == "categories" and not existing:
                base = util.slugify(vals["name_en"]) or "category"
                slug, n = base, 1
                while q1("SELECT 1 FROM categories WHERE slug=?", (slug,)):
                    n += 1
                    slug = f"{base}-{n}"
                vals["slug"] = slug
            cols = list(vals)
            if existing:
                ex(f"UPDATE {cfg['table']} SET {','.join(c + '=?' for c in cols)} WHERE id=?", [vals[c] for c in cols] + [rid])
            else:
                ex(f"INSERT INTO {cfg['table']}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [vals[c] for c in cols])
            flash(f"{cfg['singular']} saved.", "success")
            return redirect(url_for("admin.res_list", res=res))
        if new_img:
            util.delete_upload(_upload_dir(), new_img)
        data = {**data, **{k: v for k, v in request.form.items()}}
        for f in cfg["fields"]:
            if f.kind == "checkbox":
                data[f.name] = 1 if request.form.get(f.name) else 0
    choices = {f.name: _fld_choices(f) for f in cfg["fields"] if f.kind == "select"}
    return render_template("admin/form.html", res=res, cfg=cfg, d=data, errors=errors, choices=choices, editing=bool(rid), rid=rid)


@bp.route("/<res>/<int:rid>/delete", methods=["POST"], endpoint="res_delete")
def res_delete(res, rid):
    cfg = _res(res)
    row = q1(f"SELECT * FROM {cfg['table']} WHERE id=?", (rid,))
    if row:
        ex(f"DELETE FROM {cfg['table']} WHERE id=?", (rid,))
        if cfg["image"]:
            util.delete_upload(_upload_dir(), row[cfg["image"]])
        flash(f"{cfg['singular']} deleted.", "success")
    return redirect(url_for("admin.res_list", res=res))


# ===================================================================== orders
def _order_filters():
    text = request.args.get("q", "").strip()[:60]
    status = request.args.get("status", "")
    d_from, d_to = request.args.get("from", ""), request.args.get("to", "")
    area = request.args.get("area", "")
    where, args = ["1=1"], []
    if text:
        like = "%" + util.like_escape(text) + "%"
        where.append("(o.number LIKE ? ESCAPE '\\' OR o.name LIKE ? ESCAPE '\\' OR o.phone LIKE ? ESCAPE '\\')")
        args += [like] * 3
    if status in ORDER_STATUSES:
        where.append("o.status=?")
        args.append(status)
    if area in ("dhaka", "outside"):
        where.append("o.area=?")
        args.append(area)
    if d_from:
        where.append("substr(o.created_at,1,10)>=?")
        args.append(d_from[:10])
    if d_to:
        where.append("substr(o.created_at,1,10)<=?")
        args.append(d_to[:10])
    return " AND ".join(where), args, dict(q=text, status=status, area=area, **{"from": d_from, "to": d_to})


@bp.route("/orders")
def orders():
    cond, args, f = _order_filters()
    total = q1(f"SELECT COUNT(*) c FROM orders o WHERE {cond}", args)["c"]
    page, pages, off = _page(total)
    rows = q(f"""SELECT o.*, (SELECT COALESCE(SUM(qty),0) FROM order_items WHERE order_id=o.id) AS items
                 FROM orders o WHERE {cond} ORDER BY o.id DESC LIMIT {PER_PAGE} OFFSET {off}""", args)
    counts = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM orders GROUP BY status")}
    return render_template("admin/orders.html", rows=rows, total=total, page=page, pages=pages, f=f, counts=counts,
                           all_count=sum(counts.values()), qs={k: v for k, v in request.args.items() if k != "page" and v})


@bp.route("/orders/<int:oid>")
def order_detail(oid):
    o = q1("SELECT * FROM orders WHERE id=?", (oid,))
    if not o:
        abort(404)
    return render_template("admin/order_detail.html", o=o, items=q("SELECT * FROM order_items WHERE order_id=?", (oid,)),
                           history=q("SELECT * FROM order_history WHERE order_id=? ORDER BY id DESC", (oid,)))


@bp.route("/orders/<int:oid>/invoice")
def order_invoice(oid):
    o = q1("SELECT * FROM orders WHERE id=?", (oid,))
    if not o:
        abort(404)
    return render_template("admin/invoice.html", o=o, items=q("SELECT * FROM order_items WHERE order_id=?", (oid,)))


@bp.route("/orders/<int:oid>/status", methods=["POST"])
def order_status(oid):
    new = request.form.get("status", "")
    note = request.form.get("note", "").strip()[:200]
    if new not in ORDER_STATUSES:
        abort(400)
    db = dbm.get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        o = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            db.execute("ROLLBACK")
            abort(404)
        old = o["status"]
        if new != old:
            items = db.execute("SELECT * FROM order_items WHERE order_id=? AND product_id IS NOT NULL", (oid,)).fetchall()
            if new == "cancelled":
                for it in items:
                    db.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))
            elif old == "cancelled":
                for it in items:
                    p = db.execute("SELECT stock, name_en FROM products WHERE id=?", (it["product_id"],)).fetchone()
                    if p and p["stock"] < it["qty"]:
                        db.execute("ROLLBACK")
                        flash(f"Cannot re-open: not enough stock for '{p['name_en']}'. Update stock first.", "error")
                        return redirect(url_for("admin.order_detail", oid=oid))
                for it in items:
                    db.execute("UPDATE products SET stock=stock-? WHERE id=?", (it["qty"], it["product_id"]))
            db.execute("UPDATE orders SET status=? WHERE id=?", (new, oid))
            db.execute("INSERT INTO order_history(order_id,status,note,admin,created_at) VALUES(?,?,?,?,?)",
                       (oid, new, note, g.admin["username"], util.now_bd()))
        elif note:
            db.execute("INSERT INTO order_history(order_id,status,note,admin,created_at) VALUES(?,?,?,?,?)",
                       (oid, new, note, g.admin["username"], util.now_bd()))
        db.execute("COMMIT")
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    flash("Order updated.", "success")
    return redirect(sec.safe_next(request.form.get("next"), url_for("admin.order_detail", oid=oid)))


# ================================================================== customers
@bp.route("/customers")
def customers():
    text = request.args.get("q", "").strip()[:60]
    where, args = "1=1", []
    if text:
        like = "%" + util.like_escape(text) + "%"
        where, args = "(c.name LIKE ? ESCAPE '\\' OR c.phone LIKE ? ESCAPE '\\' OR c.address LIKE ? ESCAPE '\\')", [like] * 3
    total = q1(f"SELECT COUNT(*) c FROM customers c WHERE {where}", args)["c"]
    page, pages, off = _page(total)
    rows = q(f"""SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) AS orders,
                 (SELECT COALESCE(SUM(total),0) FROM orders o WHERE o.customer_id=c.id AND o.status!='cancelled') AS spent,
                 (SELECT MAX(created_at) FROM orders o WHERE o.customer_id=c.id) AS last_order
                 FROM customers c WHERE {where} ORDER BY c.id DESC LIMIT {PER_PAGE} OFFSET {off}""", args)
    return render_template("admin/customers.html", rows=rows, total=total, page=page, pages=pages, text=text,
                           qs={k: v for k, v in request.args.items() if k != "page" and v})


@bp.route("/customers/<int:cid>")
def customer_detail(cid):
    c = q1("SELECT * FROM customers WHERE id=?", (cid,))
    if not c:
        abort(404)
    rows = q("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC", (cid,))
    return render_template("admin/customer_detail.html", c=c, rows=rows,
                           spent=sum(r["total"] for r in rows if r["status"] != "cancelled"))


# =================================================================== reviews
@bp.route("/reviews")
def reviews():
    status = request.args.get("status", "pending")
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    where = "" if status == "all" else "WHERE r.status=?"
    rows = q(f"""SELECT r.*, p.name_en, p.name_bn FROM reviews r JOIN products p ON p.id=r.product_id
                 {where} ORDER BY r.id DESC LIMIT 200""", () if status == "all" else (status,))
    counts = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM reviews GROUP BY status")}
    return render_template("admin/reviews.html", rows=rows, status=status, counts=counts)


@bp.route("/reviews/<int:rid>/<action>", methods=["POST"])
def review_action(rid, action):
    if action == "delete":
        ex("DELETE FROM reviews WHERE id=?", (rid,))
    elif action in ("approve", "reject"):
        ex("UPDATE reviews SET status=? WHERE id=?", ("approved" if action == "approve" else "rejected", rid))
    else:
        abort(404)
    flash("Review updated.", "success")
    return redirect(sec.safe_next(request.form.get("next"), url_for("admin.reviews")))


# =================================================================== settings
SETTING_FIELDS = {
    "general": ["site_name", "slogan_bn", "slogan_en", "announcement_bn", "announcement_en", "about_bn", "about_en"],
    "contact": ["whatsapp", "phone", "email", "facebook", "address_bn", "address_en", "bkash", "nagad"],
    "delivery": ["delivery_dhaka", "delivery_outside", "free_delivery_min", "delivery_time_bn", "delivery_time_en"],
    "policies": ["return_bn", "return_en", "privacy_bn", "privacy_en"],
}


@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    tab = request.args.get("tab", "general")
    if tab not in SETTING_FIELDS and tab != "logo":
        tab = "general"
    errors = []
    if request.method == "POST":
        tab = request.form.get("tab", tab)
        if tab == "logo":
            try:
                new = util.save_image(request.files.get("logo"), _upload_dir(), "site", max_px=900, keep_alpha=True)
            except util.UploadError as e:
                new = None
                errors.append(str(e))
            if new:
                util.delete_upload(_upload_dir(), dbm.settings()["logo"])
                dbm.set_setting("logo", new)
                flash("Logo updated.", "success")
            elif request.form.get("reset_logo"):
                util.delete_upload(_upload_dir(), dbm.settings()["logo"])
                dbm.set_setting("logo", "static/img/logo.png")
                flash("Default logo restored.", "success")
            elif not errors:
                errors.append("Choose an image first.")
        elif tab in SETTING_FIELDS:
            vals = {k: request.form.get(k, "").strip()[:6000] for k in SETTING_FIELDS[tab]}
            for k in ("delivery_dhaka", "delivery_outside", "free_delivery_min"):
                if k in vals:
                    if not vals[k].isdigit():
                        errors.append(f"{k.replace('_', ' ').title()}: enter a whole number (0 or more).")
            for k in ("whatsapp", "phone"):
                if vals.get(k) and not util.normalize_phone(vals[k]):
                    errors.append(f"{k.title()}: enter a valid Bangladeshi mobile number like 01XXXXXXXXX.")
            if vals.get("email") and "@" not in vals["email"]:
                errors.append("Enter a valid email address.")
            if vals.get("facebook") and not vals["facebook"].startswith(("https://", "http://")):
                errors.append("Facebook link must start with https://")
            if not errors:
                for k, v in vals.items():
                    dbm.set_setting(k, v)
                flash("Settings saved.", "success")
        if not errors:
            return redirect(url_for("admin.settings_page", tab=tab))
    return render_template("admin/settings.html", tab=tab, errors=errors, fields=SETTING_FIELDS)


# =================================================================== reports
def _range_start(kind):
    today = datetime.now(util.BD_TZ).date()
    if kind == "weekly":
        return (today - timedelta(weeks=11, days=today.weekday())).isoformat()
    if kind == "monthly":
        start = today.replace(day=1)
        for _ in range(11):
            start = (start - timedelta(days=1)).replace(day=1)
        return start.isoformat()
    return (today - timedelta(days=29)).isoformat()


@bp.route("/reports")
def reports():
    kind = request.args.get("range", "daily")
    if kind not in ("daily", "weekly", "monthly"):
        kind = "daily"
    start = _range_start(kind)
    key = {"daily": "substr(o.created_at,1,10)", "weekly": "strftime('%Y-W%W', o.created_at)",
           "monthly": "substr(o.created_at,1,7)"}[kind]
    rows = q(f"""SELECT {key} AS period, COUNT(*) AS orders,
                 COALESCE(SUM(CASE WHEN o.status!='cancelled' THEN o.total END),0) AS revenue,
                 COALESCE(SUM(CASE WHEN o.status!='cancelled' THEN o.delivery END),0) AS delivery,
                 SUM(CASE WHEN o.status='delivered' THEN 1 ELSE 0 END) AS delivered,
                 SUM(CASE WHEN o.status='cancelled' THEN 1 ELSE 0 END) AS cancelled
                 FROM orders o WHERE substr(o.created_at,1,10)>=? GROUP BY period ORDER BY period DESC""", (start,))
    totals = dict(orders=sum(r["orders"] for r in rows), revenue=sum(r["revenue"] for r in rows),
                  delivered=sum(r["delivered"] for r in rows), cancelled=sum(r["cancelled"] for r in rows))
    chart = [dict(label=r["period"][-5:] if kind == "daily" else r["period"], revenue=r["revenue"], orders=r["orders"])
             for r in reversed(rows)]
    return render_template("admin/reports.html", kind=kind, rows=rows, totals=totals, chart=chart, since=start,
                           best=_best_sellers(10, since=start))


def _csv_cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s   # blocks spreadsheet formula injection


@bp.route("/reports/export")
def export_csv():
    kind = request.args.get("type", "orders")
    d_from, d_to = request.args.get("from", "")[:10], request.args.get("to", "")[:10]
    buf = io.StringIO()
    w = csv.writer(buf)
    cond, args = "1=1", []
    if d_from:
        cond += " AND substr(created_at,1,10)>=?"
        args.append(d_from)
    if d_to:
        cond += " AND substr(created_at,1,10)<=?"
        args.append(d_to)
    if kind == "orders":
        w.writerow(["Order No", "Date", "Customer", "Phone", "Address", "Area", "Subtotal", "Delivery", "Total", "Status", "Payment"])
        for r in q(f"SELECT * FROM orders WHERE {cond} ORDER BY id DESC", args):
            w.writerow([_csv_cell(x) for x in (r["number"], r["created_at"], r["name"], r["phone"], r["address"], r["area"],
                                               r["subtotal"], r["delivery"], r["total"], r["status"], r["payment"])])
    elif kind == "products":
        w.writerow(["ID", "Name (EN)", "Name (BN)", "Brand", "Category", "Price", "Previous price", "Stock", "Available"])
        for r in q("SELECT p.*, c.name_en cat FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.id"):
            w.writerow([_csv_cell(x) for x in (r["id"], r["name_en"], r["name_bn"], r["brand"], r["cat"], r["price"],
                                               r["old_price"], r["stock"], "yes" if r["available"] else "no")])
    elif kind == "customers":
        w.writerow(["Name", "Phone", "Address", "Orders", "Total spent"])
        for r in q("""SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) n,
                      (SELECT COALESCE(SUM(total),0) FROM orders o WHERE o.customer_id=c.id AND o.status!='cancelled') s
                      FROM customers c ORDER BY c.id"""):
            w.writerow([_csv_cell(x) for x in (r["name"], r["phone"], r["address"], r["n"], r["s"])])
    elif kind == "bestsellers":
        w.writerow(["Product", "Units sold", "Revenue"])
        for r in _best_sellers(500, d_from or None, d_to or None):
            w.writerow([_csv_cell(x) for x in (r["name"], r["qty"], r["revenue"])])
    else:
        abort(404)
    resp = make_response("﻿" + buf.getvalue())     # BOM so Excel shows Bangla correctly
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f"attachment; filename=bigbazar-{kind}-{util.today_bd()}.csv"
    return resp
