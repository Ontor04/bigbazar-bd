"""Small helpers: time, number formatting, images, phone validation, mail."""
import os
import re
import secrets
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 30_000_000  # protects against decompression bombs

BD_TZ = timezone(timedelta(hours=6))
log = logging.getLogger("bigbazar")

_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
             "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def now_bd():
    return datetime.now(BD_TZ).strftime("%Y-%m-%d %H:%M:%S")


def today_bd():
    return datetime.now(BD_TZ).strftime("%Y-%m-%d")


def bn_digits(s):
    return str(s).translate(_BN)


def en_digits(s):
    return str(s).translate(_EN)


def group_indian(n):
    """1250000 -> 12,50,000 (Bangladesh/South-Asian grouping)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    neg = n < 0
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + s


def money(n, lang="en"):
    s = "৳" + group_indian(n or 0)
    return bn_digits(s) if lang == "bn" else s


def num(n, lang="en"):
    s = group_indian(n or 0)
    return bn_digits(s) if lang == "bn" else s


def fmt_date(value, lang="en", with_time=True):
    if not value:
        return ""
    try:
        d = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            d = datetime.strptime(str(value)[:10], "%Y-%m-%d")
            with_time = False
        except ValueError:
            return str(value)
    if lang == "bn":
        out = f"{d.day} {BN_MONTHS[d.month - 1]} {d.year}"
        if with_time:
            out += f", {d.strftime('%I:%M %p')}"
        return bn_digits(out)
    out = f"{d.day} {EN_MONTHS[d.month - 1]} {d.year}"
    if with_time:
        out += f", {d.strftime('%I:%M %p')}"
    return out


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60]


def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_phone(raw):
    """Return a valid Bangladeshi mobile number like 01XXXXXXXXX, or None."""
    p = en_digits(raw or "")
    p = re.sub(r"[\s\-()]", "", p)
    if p.startswith("+880"):
        p = "0" + p[4:]
    elif p.startswith("880"):
        p = "0" + p[3:]
    return p if re.fullmatch(r"01[3-9]\d{8}", p) else None


def wa_number(raw):
    """01897140249 -> 8801897140249 for wa.me links."""
    p = normalize_phone(raw)
    return ("88" + p) if p else re.sub(r"\D", "", raw or "")


# ---------------------------------------------------------------- images
ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".png"}


class UploadError(Exception):
    pass


def save_image(file_storage, upload_dir, subdir, max_px=1400, keep_alpha=False):
    """Validate + re-encode an uploaded image. Returns 'subdir/name.ext'.

    * checks the real file content with Pillow (not just the extension)
    * strips metadata by re-encoding
    * SVG and everything else is rejected
    """
    if not file_storage or not file_storage.filename:
        return None
    try:
        img = Image.open(file_storage.stream)
        fmt = img.format
        if fmt not in ALLOWED_FORMATS:
            raise UploadError("Only JPG, PNG, WEBP or GIF images are allowed.")
        img.load()
    except UploadError:
        raise
    except Exception:
        raise UploadError("This file is not a valid image.")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_px, max_px))
    has_alpha = img.mode in ("RGBA", "LA", "P") and (keep_alpha or fmt in ("PNG", "GIF", "WEBP"))
    folder = os.path.join(upload_dir, subdir)
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8)
    if has_alpha and keep_alpha:
        img = img.convert("RGBA")
        name += ".png"
        img.save(os.path.join(folder, name), "PNG", optimize=True)
    else:
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        name += ".jpg"
        img.save(os.path.join(folder, name), "JPEG", quality=86, optimize=True)
    return f"{subdir}/{name}"


def delete_upload(upload_dir, rel):
    """Delete a previously uploaded file (never anything outside uploads/)."""
    if not rel or rel.startswith("static/"):
        return
    root = os.path.realpath(upload_dir)
    path = os.path.realpath(os.path.join(root, rel))
    if path.startswith(root + os.sep) and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------------ mail
def send_mail(to, subject, body, data_dir):
    """Send through SMTP if configured via env, otherwise write to an outbox log.

    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS, SMTP_FROM
    """
    host = os.environ.get("SMTP_HOST")
    if not host:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "outbox.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {now_bd()} ---\nTo: {to}\nSubject: {subject}\n\n{body}\n\n")
        log.warning("SMTP not configured; email saved to data/outbox.log (To: %s, Subject: %s)", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "noreply@localhost"))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
        return True
    except Exception as e:  # never break the request because mail failed
        log.error("Mail send failed: %s", e)
        return False
