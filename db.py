"""Database layer (SQLite) – schema, helpers, demo data."""
import os
import sqlite3
import secrets

from flask import g, current_app
from werkzeug.security import generate_password_hash

from util import now_bd, today_bd, log

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY,
  name_bn TEXT NOT NULL, name_en TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  image TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  name_bn TEXT NOT NULL DEFAULT '', name_en TEXT NOT NULL DEFAULT '',
  brand TEXT NOT NULL DEFAULT '',
  desc_bn TEXT NOT NULL DEFAULT '', desc_en TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL, old_price INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0,
  available INTEGER NOT NULL DEFAULT 1,
  image TEXT NOT NULL DEFAULT '',
  featured INTEGER NOT NULL DEFAULT 0,
  trending INTEGER NOT NULL DEFAULT 0,
  keywords TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category_id);
CREATE TABLE IF NOT EXISTS banners(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'hero',            -- hero | promo
  title_bn TEXT NOT NULL DEFAULT '', title_en TEXT NOT NULL DEFAULT '',
  sub_bn TEXT NOT NULL DEFAULT '', sub_en TEXT NOT NULL DEFAULT '',
  button_bn TEXT NOT NULL DEFAULT '', button_en TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '/shop',
  image TEXT NOT NULL DEFAULT '',
  theme TEXT NOT NULL DEFAULT 'orange',          -- orange | brown | yellow
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS campaigns(
  id INTEGER PRIMARY KEY,
  title_bn TEXT NOT NULL DEFAULT '', title_en TEXT NOT NULL DEFAULT '',
  percent INTEGER NOT NULL,
  category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,  -- NULL = all products
  start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
  address TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  customer_id INTEGER REFERENCES customers(id),
  name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL,
  area TEXT NOT NULL DEFAULT 'dhaka',            -- dhaka | outside
  note TEXT NOT NULL DEFAULT '',
  subtotal INTEGER NOT NULL, delivery INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
  payment TEXT NOT NULL DEFAULT 'cod',
  status TEXT NOT NULL DEFAULT 'pending',
  ip_hash TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
  name TEXT NOT NULL, price INTEGER NOT NULL, qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS order_history(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  admin TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name TEXT NOT NULL, rating INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | approved | rejected
  ip_hash TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts(
  id INTEGER PRIMARY KEY, ident TEXT NOT NULL, ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(ident, ts);
CREATE TABLE IF NOT EXISTS reset_tokens(
  id INTEGER PRIMARY KEY,
  admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
"""

ORDER_STATUSES = ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled"]
STATUS_BN = {"pending": "অপেক্ষমাণ", "confirmed": "কনফার্মড", "processing": "প্রসেসিং",
             "shipped": "শিপড", "delivered": "ডেলিভারড", "cancelled": "বাতিল"}

DEFAULT_SETTINGS = {
    "site_name": "BIG BAZAR BD",
    "slogan_bn": "আপনার বিশ্বস্ত অনলাইন শপিং গন্তব্য",
    "slogan_en": "Your Trusted Online Shopping Destination",
    "announcement_bn": "সারা বাংলাদেশে ক্যাশ অন ডেলিভারি • ৩ দিনের মধ্যে রিটার্ন সুবিধা",
    "announcement_en": "Cash on Delivery all over Bangladesh • 3-day return facility",
    "whatsapp": "01897140249",
    "phone": "01897140249",
    "email": "md.ontor22514@gmail.com",
    "facebook": "https://www.facebook.com/share/1Zcqrj5b7X/",
    "address_bn": "অনলাইন স্টোর – বাংলাদেশ",
    "address_en": "Online Store – Bangladesh",
    "delivery_dhaka": "70",
    "delivery_outside": "130",
    "free_delivery_min": "0",
    "delivery_time_bn": "২–৫ কর্মদিবস",
    "delivery_time_en": "2–5 working days",
    "bkash": "",
    "nagad": "",
    "logo": "static/img/logo.png",
    "about_bn": (
        "BIG BAZAR BD বাংলাদেশের আপনার বিশ্বস্ত অনলাইন শপিং গন্তব্য। আমরা সাশ্রয়ী দামে মানসম্মত পণ্যের বিশাল সংগ্রহ নিয়ে এসেছি। "
        "ইলেকট্রনিক্স ও ফ্যাশন থেকে শুরু করে ঘরের প্রয়োজনীয় ও লাইফস্টাইল পণ্য — সবকিছু একই জায়গায়।\n\n"
        "আমাদের লক্ষ্য: অনলাইন শপিংকে সবার জন্য সহজ, সুবিধাজনক ও নির্ভরযোগ্য করে তোলা।\n\n"
        "আমাদের লক্ষ্য: মানসম্মত পণ্য, সাশ্রয়ী দাম এবং গ্রাহকের সন্তুষ্টি।"
    ),
    "about_en": (
        "BIG BAZAR BD is your trusted online shopping destination in Bangladesh. We offer a wide range of quality products at affordable prices. "
        "From electronics and fashion to home essentials and lifestyle products, we aim to make online shopping easy, convenient and reliable for everyone.\n\n"
        "Our Goal: Quality Products, Affordable Prices and Customer Satisfaction."
    ),
    "return_bn": (
        "পণ্য হাতে পাওয়ার ৩ দিনের মধ্যে রিটার্ন বা এক্সচেঞ্জের জন্য আমাদের জানাতে হবে।\n\n"
        "রিটার্ন/এক্সচেঞ্জের শর্ত:\n"
        "- পণ্যটি অব্যবহৃত, অক্ষত এবং আসল প্যাকেজিংসহ থাকতে হবে।\n"
        "- ডেলিভারির সময় ভুল বা ত্রুটিপূর্ণ পণ্য পেলে প্রমাণসহ (ছবি/ভিডিও) জানাতে হবে।\n"
        "- ব্যবহৃত, ক্ষতিগ্রস্ত বা ট্যাগ খোলা পণ্য রিটার্নযোগ্য নয়।\n"
        "- আমাদের ভুলে ভুল/ত্রুটিপূর্ণ পণ্য গেলে ডেলিভারি চার্জ আমরা বহন করব।\n\n"
        "রিফান্ড: রিটার্ন গৃহীত হলে পণ্য ফেরত পাওয়ার পর আপনার সম্মতিতে এক্সচেঞ্জ বা টাকা ফেরত দেওয়া হবে।\n\n"
        "যোগাযোগ করুন: হোয়াটসঅ্যাপ বা ফোনে আমাদের জানান।"
    ),
    "return_en": (
        "Please contact us within 3 days of receiving your product to request a return or exchange.\n\n"
        "Conditions:\n"
        "- The product must be unused, undamaged and in its original packaging.\n"
        "- If you receive a wrong or defective item, tell us with proof (photo/video) at the time of delivery.\n"
        "- Used, damaged or opened-tag items cannot be returned.\n"
        "- If the mistake is ours, we bear the delivery charge.\n\n"
        "Refund: once a return is accepted and the item is back with us, we will exchange it or refund the amount with your agreement.\n\n"
        "To start a return, message us on WhatsApp or call us."
    ),
    "privacy_bn": (
        "আপনার তথ্যের গোপনীয়তা আমাদের কাছে গুরুত্বপূর্ণ।\n\n"
        "আমরা কী তথ্য সংগ্রহ করি:\n"
        "- অর্ডারের সময় আপনার নাম, মোবাইল নম্বর ও ডেলিভারি ঠিকানা।\n"
        "- আপনার দেওয়া রিভিউ।\n\n"
        "তথ্য কীভাবে ব্যবহার করি:\n"
        "- অর্ডার প্রক্রিয়া ও ডেলিভারির জন্য এবং অর্ডার সংক্রান্ত যোগাযোগের জন্য।\n"
        "- আমরা আপনার তথ্য তৃতীয় পক্ষের কাছে বিক্রি করি না। শুধু ডেলিভারির প্রয়োজনে কুরিয়ার সার্ভিসকে প্রয়োজনীয় তথ্য দেওয়া হতে পারে।\n\n"
        "নিরাপত্তা: আপনার তথ্য সুরক্ষিত ডাটাবেসে রাখা হয় এবং শুধু অনুমোদিত অ্যাডমিন দেখতে পারেন।\n\n"
        "আপনার তথ্য মুছে ফেলতে চাইলে আমাদের সাথে যোগাযোগ করুন।"
    ),
    "privacy_en": (
        "Your privacy matters to us.\n\n"
        "What we collect:\n"
        "- Your name, mobile number and delivery address when you place an order.\n"
        "- Reviews you submit.\n\n"
        "How we use it:\n"
        "- To process and deliver your order and to contact you about it.\n"
        "- We do not sell your data. Only the details needed for delivery may be shared with the courier service.\n\n"
        "Security: your information is stored in a protected database and is visible only to authorised administrators.\n\n"
        "If you want your information deleted, please contact us."
    ),
}


# --------------------------------------------------------------- plumbing
def get_db():
    if "db" not in g:
        # autocommit mode: every statement commits itself; multi-step jobs use explicit BEGIN/COMMIT
        conn = sqlite3.connect(current_app.config["DB_PATH"], timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def q1(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def ex(sql, args=()):
    cur = get_db().execute(sql, args)
    return cur


def settings():
    if "settings" not in g:
        d = dict(DEFAULT_SETTINGS)
        for r in q("SELECT key, value FROM settings"):
            d[r["key"]] = r["value"]
        g.settings = d
    return g.settings


def set_setting(key, value):
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, value))
    g.pop("settings", None)


def int_setting(key, default=0):
    try:
        return int(settings().get(key) or default)
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------- campaigns/prices
def active_campaigns():
    if "campaigns" not in g:
        t = today_bd()
        g.campaigns = [dict(r) for r in q(
            "SELECT * FROM campaigns WHERE active=1 AND (start_date='' OR start_date<=?) AND (end_date='' OR end_date>=?)",
            (t, t))]
    return g.campaigns


def annotate(rows):
    """Add sale price / compare price / percent / in_stock to product rows."""
    camps = active_campaigns()
    out = []
    for r in rows:
        p = dict(r)
        best = 0
        for c in camps:
            if c["category_id"] in (None, p.get("category_id")):
                best = max(best, c["percent"])
        sale = p["price"]
        compare = p["old_price"] if p["old_price"] and p["old_price"] > p["price"] else 0
        if best:
            sale = max(1, round(p["price"] * (100 - best) / 100))
            compare = max(compare, p["price"])
        p["sale"] = sale
        p["compare"] = compare if compare > sale else 0
        p["percent_off"] = round((p["compare"] - sale) * 100 / p["compare"]) if p["compare"] else 0
        p["in_stock"] = bool(p["available"]) and p["stock"] > 0
        out.append(p)
    return out


PRODUCT_SELECT = """
SELECT p.*, c.name_bn AS cat_bn, c.name_en AS cat_en, c.slug AS cat_slug,
  (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.product_id=p.id AND r.status='approved') AS rating,
  (SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id AND r.status='approved') AS rating_count
FROM products p LEFT JOIN categories c ON c.id=p.category_id
"""


# --------------------------------------------------------------- bootstrap
def init_db(app):
    os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    first_run = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0 and \
        conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
    if first_run:
        seed_demo(conn)
    conn.commit()
    conn.close()


def seed_demo(conn):
    now = now_bd()
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    cats = [
        ("ইলেকট্রনিক্স ও গ্যাজেট", "Electronics & Gadgets", "electronics", "powerbank"),
        ("ফ্যাশন ও লাইফস্টাইল", "Fashion & Lifestyle", "fashion", "tshirt"),
        ("হোম ও কিচেন", "Home & Kitchen", "home-kitchen", "bottle"),
        ("বিউটি ও পার্সোনাল কেয়ার", "Beauty & Personal Care", "beauty", "facewash"),
        ("ঘড়ি ও অ্যাকসেসরিজ", "Watches & Accessories", "watches", "analogwatch"),
        ("স্পোর্টস ও ফিটনেস", "Sports & Fitness", "sports", "yogamat"),
        ("ট্রেন্ডিং ও ভাইরাল পণ্য", "Trending & Viral Products", "trending", "neckfan"),
    ]
    ids = {}
    for i, (bn, en, slug, img) in enumerate(cats, 1):
        cur = conn.execute("INSERT INTO categories(name_bn,name_en,slug,image,sort) VALUES(?,?,?,?,?)",
                           (bn, en, slug, f"static/img/demo/{img}.svg", i))
        ids[slug] = cur.lastrowid
    # (cat, name_bn, name_en, brand, price, old, stock, image, featured, trending, keywords, desc_bn, desc_en)
    prods = [
        ("electronics", "ওয়্যারলেস ব্লুটুথ ইয়ারবাডস", "Wireless Bluetooth Earbuds", "Soundly", 850, 1200, 40, "earbuds", 1, 1,
         "earphone earbud headphone bluetooth wireless ইয়ারফোন ইয়ারবাড হেডফোন ব্লুটুথ ওয়্যারলেস",
         "পরিষ্কার সাউন্ড, আরামদায়ক ডিজাইন ও দীর্ঘ ব্যাটারি লাইফসহ উন্নত মানের ওয়্যারলেস ইয়ারবাডস।",
         "High-quality wireless earbuds with clear sound, comfortable design and long battery life."),
        ("electronics", "ফাস্ট চার্জিং পাওয়ার ব্যাংক", "Fast Charging Power Bank", "Voltix", 1250, 1600, 30, "powerbank", 1, 0,
         "powerbank power bank charger battery পাওয়ারব্যাংক পাওয়ার ব্যাংক চার্জার ব্যাটারি",
         "একাধিক চার্জিং পোর্ট ও সেফটি প্রোটেকশনসহ বহনযোগ্য পাওয়ার ব্যাংক।",
         "Portable power bank with multiple charging ports and safety protection."),
        ("electronics", "স্মার্ট ওয়াচ", "Smart Watch", "Chronos", 1450, 1900, 25, "smartwatch", 1, 1,
         "smartwatch smart watch watch fitness band স্মার্টওয়াচ স্মার্ট ঘড়ি ওয়াচ ঘড়ি",
         "দরকারি স্মার্ট ফিচারসহ স্টাইলিশ ও আধুনিক ডিজাইনের স্মার্ট ওয়াচ।",
         "Stylish smart watch with useful smart features and a modern design."),
        ("home-kitchen", "আরজিবি এলইডি স্ট্রিপ লাইট", "RGB LED Strip Light", "Glowy", 650, 950, 50, "ledstrip", 1, 1,
         "led strip light rgb lighting decoration এলইডি লাইট স্ট্রিপ বাতি আলো সাজসজ্জা",
         "রিমোট কন্ট্রোল ও একাধিক লাইটিং মোডসহ রঙিন এলইডি স্ট্রিপ লাইট।",
         "Colorful LED strip light with remote control and multiple lighting modes."),
        ("fashion", "পুরুষদের ক্যাজুয়াল টি-শার্ট", "Men's Casual T-Shirt", "Urbanwear", 450, 650, 60, "tshirt", 1, 0,
         "tshirt t-shirt shirt men cotton টিশার্ট টি-শার্ট শার্ট জামা পুরুষ পোশাক",
         "প্রতিদিনের ব্যবহারের জন্য আরামদায়ক ও স্টাইলিশ ক্যাজুয়াল টি-শার্ট।",
         "Comfortable and stylish casual T-shirt for everyday use."),
        # extra demo products so every category looks alive – delete/edit freely in the admin panel
        ("beauty", "হারবাল ফেস ওয়াশ", "Herbal Face Wash", "Pure Leaf", 280, 380, 45, "facewash", 0, 0,
         "face wash facewash skin care herbal cleanser ফেস ওয়াশ স্কিন কেয়ার হারবাল",
         "ত্বক পরিষ্কার ও সতেজ রাখতে হারবাল ফেস ওয়াশ।", "Herbal face wash that keeps your skin clean and fresh."),
        ("watches", "অ্যানালগ রিস্ট ওয়াচ", "Analog Wrist Watch", "Chronos", 990, 1400, 20, "analogwatch", 1, 0,
         "watch wrist analog ghori ঘড়ি রিস্ট ওয়াচ হাতঘড়ি অ্যানালগ",
         "ক্লাসিক ডিজাইনের মজবুত অ্যানালগ রিস্ট ওয়াচ।", "Classic analog wrist watch with a durable build."),
        ("sports", "নন-স্লিপ যোগ ম্যাট", "Non-Slip Yoga Mat", "FitLife", 750, 1000, 35, "yogamat", 0, 0,
         "yoga mat exercise fitness gym যোগ ম্যাট ব্যায়াম ফিটনেস জিম",
         "ব্যায়াম ও যোগাসনের জন্য পুরু, নন-স্লিপ যোগ ম্যাট।", "Thick non-slip yoga mat for workouts and yoga."),
        ("home-kitchen", "স্টেইনলেস স্টিল পানির বোতল", "Stainless Steel Water Bottle", "Hydro", 420, 600, 55, "bottle", 0, 1,
         "bottle water flask steel thermos বোতল পানির বোতল ফ্লাস্ক স্টিল",
         "দীর্ঘক্ষণ ঠান্ডা/গরম রাখে এমন মজবুত স্টেইনলেস স্টিল বোতল।",
         "Durable stainless steel bottle that keeps drinks cold or hot for hours."),
        ("trending", "মিনি পোর্টেবল নেক ফ্যান", "Mini Portable Neck Fan", "Breezy", 550, 800, 38, "neckfan", 1, 1,
         "fan neck fan portable mini usb cooling ফ্যান নেক ফ্যান পোর্টেবল ছোট পাখা",
         "গলায় ঝুলিয়ে ব্যবহার করার রিচার্জেবল মিনি ফ্যান।", "Rechargeable mini fan you wear around your neck."),
    ]
    for (cat, bn, en, brand, price, old, stock, img, feat, trend, kw, dbn, den) in prods:
        conn.execute(
            "INSERT INTO products(category_id,name_bn,name_en,brand,desc_bn,desc_en,price,old_price,stock,available,image,featured,trending,keywords,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)",
            (ids[cat], bn, en, brand, dbn, den, price, old, stock, f"static/img/demo/{img}.svg", feat, trend, kw, now))
    banners = [
        ("hero", "সেরা দামে সেরা পণ্য", "Best Products at Best Prices",
         "সারা বাংলাদেশে ক্যাশ অন ডেলিভারি — পণ্য হাতে পেয়ে টাকা দিন", "Cash on Delivery all over Bangladesh — pay when you receive",
         "এখনই কিনুন", "Shop Now", "/shop", "orange", 1),
        ("hero", "ইলেকট্রনিক্স ও গ্যাজেট অফার", "Electronics & Gadgets Deals",
         "ইয়ারবাডস, পাওয়ার ব্যাংক, স্মার্ট ওয়াচ — আকর্ষণীয় ছাড়ে", "Earbuds, power banks, smart watches — at great discounts",
         "অফার দেখুন", "View Offers", "/category/electronics", "brown", 2),
        ("promo", "ফ্যাশন ও লাইফস্টাইল", "Fashion & Lifestyle", "নতুন কালেকশন", "New collection",
         "দেখুন", "Explore", "/category/fashion", "yellow", 1),
        ("promo", "ঘর সাজান আলোয়", "Light up your home", "এলইডি স্ট্রিপ লাইট ও আরও অনেক কিছু", "LED strip lights and more",
         "দেখুন", "Explore", "/category/home-kitchen", "brown", 2),
    ]
    for (kind, tbn, ten, sbn, sen, bbn, ben, link, theme, sort) in banners:
        conn.execute(
            "INSERT INTO banners(kind,title_bn,title_en,sub_bn,sub_en,button_bn,button_en,link,theme,sort) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (kind, tbn, ten, sbn, sen, bbn, ben, link, theme, sort))


def ensure_admin(app):
    """Create the first admin if none exists. Password comes from env or is random + printed once."""
    conn = sqlite3.connect(app.config["DB_PATH"])
    n = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if n:
        conn.close()
        return None
    username = os.environ.get("ADMIN_USERNAME", "admin")
    email = os.environ.get("ADMIN_EMAIL", "md.ontor22514@gmail.com")
    password = os.environ.get("ADMIN_PASSWORD")
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    conn.execute("INSERT INTO admins(username,email,password_hash,created_at) VALUES(?,?,?,?)",
                 (username, email, generate_password_hash(password), now_bd()))
    conn.commit()
    conn.close()
    if generated:
        bar = "=" * 62
        msg = (f"\n{bar}\n  FIRST-TIME ADMIN LOGIN (shown only once – save it now!)\n"
               f"  Username : {username}\n  Password : {password}\n"
               f"  Login at : {app.config['ADMIN_PATH']}/login\n"
               f"  (Change it later in Admin → Account)\n{bar}\n")
        print(msg, flush=True)
        log.warning("First admin created: %s", username)
    return username
