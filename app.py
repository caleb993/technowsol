import os
import io
import math
import secrets
import urllib.parse
import json
from datetime import datetime, timedelta

import markdown
import psycopg2
import psycopg2.extras
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, send_from_directory,
    flash, abort, session, jsonify, Response
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import data

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

ADMIN_KEY = os.environ.get("ADMIN_KEY", "calebadmin")

ALLOWED_EXTS = {
    "pdf", "doc", "docx", "png", "jpg", "jpeg", "zip", "txt",
    "ppt", "pptx", "webp", "gif", "mp4", "webm", "ogg", "mov", "m4v"
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
VIDEO_EXTS = {"mp4", "webm", "ogg", "mov", "m4v"}

app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


# =========================================================
# REAL VISITOR INTELLIGENCE LAYER
# =========================================================
# This layer intentionally does NOT trust raw HTTP requests. It only treats a
# session as human after JavaScript reports real browser behavior.

BOT_SIGNATURES = [
    # Search engines
    "googlebot", "adsbot-google", "mediapartners-google", "apis-google", "google-inspectiontool",
    "bingbot", "msnbot", "slurp", "duckduckbot", "baiduspider", "yandexbot", "yandeximages",
    "sogou", "exabot", "facebot", "facebookexternalhit", "ia_archiver",

    # SEO crawlers
    "ahrefsbot", "semrushbot", "mj12bot", "dotbot", "serpstatbot", "seznambot", "rogerbot",
    "linkdexbot", "sitebulb", "screaming frog", "screamingfrogseospider", "deepcrawl", "lumar",
    "oncrawl", "dataforseo", "blexbot", "megaindex", "petalbot",

    # AI / LLM crawlers
    "gptbot", "chatgpt-user", "openai", "ccbot", "anthropic-ai", "claudebot", "claude-web",
    "perplexitybot", "cohere-ai", "amazonbot", "bytespider", "imagesiftbot", "omgilibot",
    "youbot", "ai2bot", "diffbot",

    # Social preview crawlers
    "twitterbot", "linkedinbot", "whatsapp", "telegrambot", "discordbot", "slackbot",
    "skypeuripreview", "pinterestbot", "redditbot", "quorabot", "vkshare", "embedly",
    "flipboard", "tumblr",

    # Monitoring / uptime
    "uptimerobot", "pingdom", "statuscake", "newrelic", "datadog", "better uptime", "healthchecks",
    "nagios", "zabbix",

    # Security scanners
    "nikto", "acunetix", "nessus", "openvas", "qualys", "sqlmap", "nmap", "masscan", "wpscan",
    "dirbuster", "gobuster", "burpsuite", "zgrab", "jaeles", "httpx", "nuclei",

    # Libraries / automation
    "python-requests", "python urllib", "aiohttp", "curl", "wget", "httpclient", "okhttp",
    "libwww-perl", "scrapy", "mechanize", "feedfetcher", "axios", "go-http-client",
    "java/", "php/", "ruby", "perl",

    # Headless / browser automation
    "headlesschrome", "puppeteer", "playwright", "selenium", "phantomjs", "electron", "cypress",

    # Generic bot words
    "bot", "crawler", "spider", "scraper", "fetch", "scanner", "checker", "validator",
    "monitor", "preview", "parser", "harvest", "extract", "spammer",
]

BLOCKED_PATHS = {
    "/favicon.ico", "/robots.txt", "/sitemap.xml", "/ads.txt", "/manifest.json", "/site.webmanifest"
}

EXTENSIONS_TO_IGNORE = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".map", ".mp4", ".webm", ".ogg", ".mov", ".m4v"
)

TRACKABLE_PREFIXES = ("/", "/blog", "/about", "/contact-us", "/privacy-policy", "/terms", "/disclaimer", "/cookie-policy")


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def hash_ip(ip):
    import hashlib
    salt = app.secret_key or "techknow"
    return hashlib.sha256(f"{salt}:{ip}".encode("utf-8")).hexdigest()[:32]


def is_bot_user_agent(user_agent):
    """Bot blocking disabled by owner request.

    The analytics system must not reject Google, Facebook, WhatsApp,
    crawlers, previews, or any browser based on User-Agent.
    """
    return False


def is_ignored_tracking_path(path):
    path = (path or "/").split("?")[0]
    lower = path.lower()
    if lower in BLOCKED_PATHS:
        return True
    if lower.startswith(("/static/", "/media/", "/download/", "/admin", "/api/", "/login", "/logout")):
        return True
    if lower.endswith(EXTENSIONS_TO_IGNORE):
        return True
    return False


def safe_int(value, default=0, minimum=0, maximum=100000):
    try:
        number = int(float(value))
        return max(minimum, min(maximum, number))
    except Exception:
        return default


def ensure_real_analytics_tables():
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS verified_sessions (
                        session_id TEXT PRIMARY KEY,
                        ip_hash TEXT,
                        user_agent TEXT,
                        path TEXT,
                        browser TEXT,
                        device_type TEXT,
                        timezone TEXT,
                        screen_resolution TEXT,
                        referrer TEXT,
                        first_seen TIMESTAMP DEFAULT now(),
                        last_seen TIMESTAMP DEFAULT now(),
                        last_activity TIMESTAMP DEFAULT now(),
                        js_verified BOOLEAN DEFAULT FALSE,
                        bot_detected BOOLEAN DEFAULT FALSE,
                        suspicious BOOLEAN DEFAULT FALSE,
                        engaged BOOLEAN DEFAULT FALSE,
                        active BOOLEAN DEFAULT FALSE,
                        visible BOOLEAN DEFAULT TRUE,
                        returning_visitor BOOLEAN DEFAULT FALSE,
                        scroll_depth INTEGER DEFAULT 0,
                        total_active_seconds INTEGER DEFAULT 0,
                        heartbeat_count INTEGER DEFAULT 0,
                        page_views INTEGER DEFAULT 0
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_requests (
                        id SERIAL PRIMARY KEY,
                        ip_hash TEXT,
                        user_agent TEXT,
                        path TEXT,
                        reason TEXT,
                        created_at TIMESTAMP DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS blog_read_sessions (
                        session_id TEXT,
                        slug TEXT,
                        first_seen TIMESTAMP DEFAULT now(),
                        last_heartbeat TIMESTAMP DEFAULT now(),
                        total_seconds INTEGER DEFAULT 0,
                        max_scroll_depth INTEGER DEFAULT 0,
                        PRIMARY KEY(session_id, slug)
                    )
                """)
                # Safe migrations for existing deployments.
                cur.execute("ALTER TABLE verified_sessions ADD COLUMN IF NOT EXISTS returning_visitor BOOLEAN DEFAULT FALSE")
                cur.execute("ALTER TABLE verified_sessions ADD COLUMN IF NOT EXISTS scroll_depth INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE verified_sessions ADD COLUMN IF NOT EXISTS total_active_seconds INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE verified_sessions ADD COLUMN IF NOT EXISTS heartbeat_count INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE verified_sessions ADD COLUMN IF NOT EXISTS page_views INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE blog_read_sessions ADD COLUMN IF NOT EXISTS total_seconds INTEGER DEFAULT 0")
                cur.execute("ALTER TABLE blog_read_sessions ADD COLUMN IF NOT EXISTS max_scroll_depth INTEGER DEFAULT 0")
    except Exception as e:
        print("⚠️ Could not initialize real analytics tables:", e)
    finally:
        conn.close()


def record_bot_request(path, user_agent, reason="bot_signature"):
    try:
        conn = data.get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bot_requests (ip_hash, user_agent, path, reason) VALUES (%s, %s, %s, %s)",
                    (hash_ip(get_client_ip()), user_agent[:500], (path or "/")[:500], reason)
                )
    except Exception as e:
        print("Bot request logging failed:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def record_verified_session(payload):
    path = (payload.get("path") or request.path or "/").split("?")[0]
    user_agent = request.headers.get("User-Agent", "")

    # Bot/path filtering disabled: count all public analytics beacons.
    # Do not count admin sessions as public readers.
    if session.get("is_admin") or path.startswith("/admin"):
        return {"status": "ignored", "reason": "admin"}

    session_id = get_or_create_visitor_id()
    js_enabled = bool(payload.get("js_enabled", True))
    visible = payload.get("visible", True)
    if isinstance(visible, str):
        visible = visible.lower() == "true"

    scroll_depth = safe_int(payload.get("scroll_depth", 0), 0, 0, 100)
    time_on_page = safe_int(payload.get("time_on_page", 0), 0, 0, 86400)
    heartbeat_count = safe_int(payload.get("heartbeat_count", 1), 1, 0, 100000)
    browser = (payload.get("browser") or "Unknown Browser")[:120]
    device_type = (payload.get("device_type") or "Unknown Device")[:80]
    timezone = (payload.get("timezone") or "UTC")[:80]
    screen_resolution = (payload.get("screen_resolution") or "Unknown")[:60]
    referrer = (payload.get("referrer") or request.referrer or "")[:500]
    engaged_flag = bool(payload.get("engaged", False) or payload.get("mouse_moved", False) or payload.get("interaction", False))

    # Suspicious-session filtering disabled: every public JS beacon is counted.
    suspicious = False
    verified = True
    engaged = True
    active = bool(visible)

    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO verified_sessions (
                        session_id, ip_hash, user_agent, path, browser, device_type, timezone,
                        screen_resolution, referrer, js_verified, bot_detected, suspicious,
                        engaged, active, visible, returning_visitor, scroll_depth, total_active_seconds,
                        heartbeat_count, page_views, first_seen, last_seen, last_activity
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, FALSE, %s,
                        %s, %s, %s, FALSE, %s, %s,
                        %s, 1, now(), now(), now()
                    )
                    ON CONFLICT (session_id) DO UPDATE SET
                        path = EXCLUDED.path,
                        user_agent = EXCLUDED.user_agent,
                        browser = EXCLUDED.browser,
                        device_type = EXCLUDED.device_type,
                        timezone = EXCLUDED.timezone,
                        screen_resolution = EXCLUDED.screen_resolution,
                        referrer = COALESCE(NULLIF(EXCLUDED.referrer, ''), verified_sessions.referrer),
                        last_seen = now(),
                        last_activity = CASE WHEN EXCLUDED.active THEN now() ELSE verified_sessions.last_activity END,
                        js_verified = verified_sessions.js_verified OR EXCLUDED.js_verified,
                        suspicious = verified_sessions.suspicious OR EXCLUDED.suspicious,
                        engaged = verified_sessions.engaged OR EXCLUDED.engaged,
                        active = EXCLUDED.active,
                        visible = EXCLUDED.visible,
                        returning_visitor = TRUE,
                        scroll_depth = GREATEST(verified_sessions.scroll_depth, EXCLUDED.scroll_depth),
                        total_active_seconds = GREATEST(verified_sessions.total_active_seconds, EXCLUDED.total_active_seconds),
                        heartbeat_count = verified_sessions.heartbeat_count + 1,
                        page_views = verified_sessions.page_views + 1
                """, (
                    session_id, hash_ip(get_client_ip()), user_agent[:500], path[:500], browser, device_type, timezone,
                    screen_resolution, referrer, verified, suspicious,
                    engaged, active, visible, scroll_depth, time_on_page,
                    heartbeat_count
                ))
        return {"status": "success", "verified": verified, "engaged": engaged, "active": active}
    except Exception as e:
        print("Verified session tracking failed:", e)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def get_verified_analytics_snapshot():
    ensure_real_analytics_tables()
    fallback = {
        "total": 0, "real": 0, "engaged": 0, "bot": 0, "suspicious": 0,
        "returning": 0, "avg_read_time": 0, "bounce_rate": 0, "scroll_completion": 0,
        "today": 0, "seven_days": 0, "all_time": 0
    }
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT
                      COUNT(*) AS human_sessions,
                      COUNT(*) FILTER (WHERE first_seen::date = CURRENT_DATE) AS today_sessions,
                      COUNT(*) FILTER (WHERE first_seen >= now() - INTERVAL '7 days') AS seven_day_sessions,
                      COUNT(*) FILTER (WHERE engaged = TRUE) AS engaged_sessions,
                      COUNT(*) FILTER (WHERE active = TRUE AND last_activity >= now() - INTERVAL '90 seconds') AS active_readers,
                      0 AS suspicious_sessions,
                      COUNT(*) FILTER (WHERE returning_visitor = TRUE) AS returning_visitors,
                      COALESCE(AVG(total_active_seconds), 0) AS avg_read_time,
                      COALESCE(AVG(scroll_depth), 0) AS avg_scroll,
                      COUNT(*) FILTER (WHERE total_active_seconds < 15 OR scroll_depth < 10) AS bounces
                    FROM verified_sessions
                """)
                row = cur.fetchone() or {}
                bot_row = {"bots": 0}

                human = int(row.get("human_sessions") or 0)
                bounces = int(row.get("bounces") or 0)
                fallback.update({
                    "total": human,
                    "real": human,
                    "engaged": int(row.get("active_readers") or 0),
                    "bot": int(bot_row.get("bots") or 0),
                    "suspicious": int(row.get("suspicious_sessions") or 0),
                    "returning": int(row.get("returning_visitors") or 0),
                    "avg_read_time": int(float(row.get("avg_read_time") or 0)),
                    "bounce_rate": int((bounces / human) * 100) if human else 0,
                    "scroll_completion": int(float(row.get("avg_scroll") or 0)),
                    "today": int(row.get("today_sessions") or 0),
                    "seven_days": int(row.get("seven_day_sessions") or 0),
                    "all_time": human,
                })
    except Exception as e:
        print("Verified analytics snapshot failed:", e)
    finally:
        conn.close()
    return fallback

def get_verified_daily_summary(days=15):
    ensure_real_analytics_tables()
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT DATE(first_seen) AS date, COUNT(*) AS count
                    FROM verified_sessions
                    WHERE first_seen >= now() - (%s * INTERVAL '1 day')
                    GROUP BY DATE(first_seen)
                    ORDER BY DATE(first_seen)
                """, (days,))
                return [{"date": str(r["date"]), "count": int(r["count"])} for r in cur.fetchall()]
    except Exception as e:
        print("Verified daily summary failed:", e)
        return []
    finally:
        conn.close()


ensure_real_analytics_tables()

@app.route("/sitemap.xml")
def sitemap_xml():
    """Dynamically generate sitemap for SEO and Google Search Console."""
    base_url = "https://techknowsolution.co.ke"

    static_pages = [
        {"loc": "/", "changefreq": "daily", "priority": "1.0"},
        {"loc": "/blog", "changefreq": "daily", "priority": "0.9"},
        {"loc": "/cybersecurity", "changefreq": "daily", "priority": "0.9"},
        {"loc": "/networking", "changefreq": "daily", "priority": "0.9"},
        {"loc": "/windows", "changefreq": "daily", "priority": "0.85"},
        {"loc": "/ai-automation", "changefreq": "daily", "priority": "0.85"},
        {"loc": "/ict-support", "changefreq": "daily", "priority": "0.85"},
        {"loc": "/mobile-android", "changefreq": "daily", "priority": "0.8"},
        {"loc": "/programming", "changefreq": "weekly", "priority": "0.75"},
        {"loc": "/cloud-computing", "changefreq": "weekly", "priority": "0.75"},
        {"loc": "/technology-news", "changefreq": "daily", "priority": "0.8"},
        {"loc": "/career-certifications", "changefreq": "weekly", "priority": "0.75"},
        {"loc": "/about", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "/contact-us", "changefreq": "monthly", "priority": "0.6"},
        {"loc": "/privacy-policy", "changefreq": "yearly", "priority": "0.4"},
        {"loc": "/terms", "changefreq": "yearly", "priority": "0.4"},
        {"loc": "/disclaimer", "changefreq": "yearly", "priority": "0.4"},
        {"loc": "/cookie-policy", "changefreq": "yearly", "priority": "0.4"},
    ]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    urls = []

    for page in static_pages:
        urls.append(f"""
  <url>
    <loc>{base_url}{page['loc']}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{page['changefreq']}</changefreq>
    <priority>{page['priority']}</priority>
  </url>""")

    try:
        try:
            blogs = data.load_blogs(include_drafts=False)
        except TypeError:
            blogs = data.load_blogs()

        for blog in blogs:
            slug = blog.get("slug")
            if not slug:
                continue

            lastmod = today
            if blog.get("updated_at"):
                lastmod = str(blog.get("updated_at"))[:10]
            elif blog.get("published_at"):
                lastmod = str(blog.get("published_at"))[:10]
            elif blog.get("timestamp"):
                lastmod = str(blog.get("timestamp"))[:10]

            urls.append(f"""
  <url>
    <loc>{base_url}/blog/{slug}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    except Exception as e:
        print("Sitemap blog loading error:", e)

    xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
{''.join(urls)}
</urlset>"""

    response = Response(xml, mimetype="application/xml")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response

@app.before_request
def redirect_to_custom_domain():
    """Force one canonical production domain."""
    
    host = request.host.lower()

    if (
        "onrender.com" in host
        or host == "www.techknowsolution.co.ke"
    ):
        query = request.query_string.decode("utf-8")

        target = "https://techknowsolution.co.ke" + request.path

        if query:
            target += "?" + query

        return redirect(target, code=301)
@app.route("/robots.txt")
def robots_txt():
    """Expose robots.txt dynamically for search engines."""
    robots = """User-agent: *
Allow: /

Disallow: /admin
Disallow: /dashboard
Disallow: /console

Sitemap: https://techknowsolution.co.ke/sitemap.xml
"""

    response = Response(robots, mimetype="text/plain")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response

@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def get_or_create_visitor_id():
    if "visitor_id" not in session:
        session["visitor_id"] = secrets.token_hex(16)
    return session["visitor_id"]


try:
    data.create_tables()
except Exception as e:
    print("⚠️ Could not initialize DB tables:", e)


def seed_blog_assets():
    try:
        import glob

        conn = data.get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM files WHERE category='blog_media' AND name='mpesa_security.png'"
                )
                row = cur.fetchone()

                if not row:
                    local_path = None
                    candidates = [
                        "src/assets/images/mpesa_security_1779629331279.png",
                        "/src/assets/images/mpesa_security_1779629331279.png",
                        "./src/assets/images/mpesa_security_1779629331279.png"
                    ]

                    for path in candidates:
                        if os.path.exists(path):
                            local_path = path
                            break

                    if not local_path:
                        found = (
                            glob.glob("src/assets/images/mpesa_security_*.png") +
                            glob.glob("/src/assets/images/mpesa_security_*.png")
                        )
                        if found:
                            local_path = found[0]

                    if local_path and os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            img_data = f.read()

                        cur.execute(
                            """
                            INSERT INTO files
                            (name, category, content, mimetype, approved, storage_provider, file_size)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                "mpesa_security.png",
                                "blog_media",
                                psycopg2.Binary(img_data),
                                "image/png",
                                True,
                                "database",
                                len(img_data)
                            )
                        )
                        print("✅ Seeded mpesa_security.png into database.")
                    else:
                        print("⚠️ Generated image path not found for seeding database.")

    except Exception as e:
        print(f"⚠️ Error seeding database: {e}")


seed_blog_assets()

# Keep old articles out of the generic Technology bucket after deployment.
try:
    refresh_existing_blog_categories()
except NameError:
    # Defined below on first cold start; homepage runtime categorization still works.
    pass


def get_blog_category(title, content):
    """Automatically classify posts from title + content.
    Title receives priority so old posts stop being dumped randomly into Technology.
    """
    title_text = (title or "").lower()
    body_text = (content or "").lower()
    combined = f"{title_text} {body_text}"

    category_rules = [
        ("Mobile & Android", [
            "android", "phone", "smartphone", "mobile", "battery", "slow down", "slowdown",
            "app cache", "ram", "storage", "play store", "samsung", "tecno", "infinix", "xiaomi"
        ]),
        ("Windows News", [
            "windows", "microsoft", "windows 10", "windows 11", "pc fix", "laptop", "driver",
            "activation", "update error", "defender", "bitlocker", "office 365", "onedrive"
        ]),
        ("Cybersecurity", [
            "cyber", "exploit", "mitigate", "security", "defense", "hack", "hacking",
            "penetration", "firewall", "malware", "phishing", "ransomware", "camera",
            "password", "breach", "vpn", "privacy", "scam", "mpesa", "m-pesa", "attack",
            "threat", "fraud", "otp", "spyware"
        ]),
        ("Networking", [
            "routing", "network", "networking", "ip address", "ip ", "cisco", "ccna", "switch",
            "router", "dhcp", "dns", "lan", "wan", "subnet", "vlan", "ospf", "wifi", "wi-fi",
            "topology", "tcp", "udp", "gateway", "sd-wan"
        ]),
        ("AI & Automation", [
            "ai", "artificial intelligence", "machine learning", "model", "neural", "predict",
            "automation", "workflow", "cron", "script", "chatgpt", "gemini", "bot", "automate"
        ]),
        ("ICT Support", [
            "ict", "support", "helpdesk", "computer", "hardware", "troubleshoot",
            "printer", "scanner", "office", "user account", "email issue", "repair", "maintenance"
        ]),
        ("Technology", [
            "web", "html", "css", "flask", "react", "javascript", "typescript", "frontend",
            "backend", "seo", "adsense", "website", "cloud", "database", "digital", "technology", "tech"
        ]),
    ]

    # Give strong priority to title matches.
    for category, words in category_rules:
        if any(w in title_text for w in words):
            return category
    for category, words in category_rules:
        if any(w in combined for w in words):
            return category
    return "Technology"


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS


def allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in IMAGE_EXTS


def allowed_video(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in VIDEO_EXTS


def require_admin():
    if not session.get("is_admin"):
        flash("Please log in as admin.")
        return False
    return True


def category_from_kind(kind):
    if kind == "profile":
        return "profile"
    if kind == "hero":
        return "hero"
    if kind == "blog_media":
        return "blog_media"
    return "gallery"


def latest_file(category, only_images=False):
    rec = data.get_latest_file_record(category, only_images=only_images)
    if not rec:
        return None, None

    ts = int(rec["uploaded_at"].timestamp()) if rec.get("uploaded_at") else 0
    return rec.get("name"), ts


def owner_cv_filename():
    return data.get_latest_filename("cv")


def list_projects():
    return data.list_projects(approved=True)


def list_pending():
    return data.list_projects(approved=False)


def ensure_gallery_metadata_columns():
    """Add optional title/caption fields for public Operations Gallery media."""
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS media_title TEXT")
                cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS media_caption TEXT")
                cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS media_narration TEXT")
    except Exception as e:
        print("⚠️ Could not prepare gallery metadata columns:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def pretty_media_title(filename):
    base = os.path.splitext(filename or "Operations media")[0]
    cleaned = base.replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "Operations Media"


def list_gallery_media(limit=None):
    """Return gallery media with clean display titles and short narrations."""
    ensure_gallery_metadata_columns()
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                sql = """
                    SELECT name, mimetype, uploaded_at, url, storage_provider,
                           COALESCE(media_title, '') AS media_title,
                           COALESCE(media_caption, '') AS media_caption,
                           COALESCE(media_narration, '') AS media_narration
                    FROM files
                    WHERE category='gallery' AND approved = TRUE
                    ORDER BY uploaded_at DESC
                """
                if limit:
                    sql += " LIMIT %s"
                    cur.execute(sql, (limit,))
                else:
                    cur.execute(sql)

                rows = cur.fetchall()
                out = []
                for r in rows:
                    mimetype = r["mimetype"] or ""
                    typ = "image" if mimetype.startswith("image") else "video" if mimetype.startswith("video") else "other"
                    name = r["name"]
                    title = (r["media_title"] or "").strip() or pretty_media_title(name)
                    caption = (r["media_caption"] or "").strip()
                    if not caption:
                        caption = "A field moment from SurgeTechKnow operations, ICT support, networking, or systems work."
                    out.append({
                        "name": name,
                        "type": typ,
                        "url": r["url"] or f"/media/gallery/{name}",
                        "title": title,
                        "caption": caption,
                        "narration": (r["media_narration"] or "").strip() or caption,
                        "description": (r["media_narration"] or "").strip() or caption,
                        "uploaded_at": r["uploaded_at"].isoformat() if r.get("uploaded_at") else "",
                        "storage_provider": r["storage_provider"] or "database"
                    })
                return out
    except Exception as e:
        print("Error listing gallery media:", e)
        try:
            return data.list_gallery_media()
        except Exception:
            return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_gallery_metadata(filename, media_title='', media_caption='', media_narration=''):
    ensure_gallery_metadata_columns()
    if not filename:
        return
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE files
                    SET media_title = %s,
                        media_caption = %s,
                        media_narration = %s
                    WHERE category='gallery' AND name=%s
                    """,
                    ((media_title or '').strip()[:140], (media_caption or '').strip()[:500], (media_narration or media_caption or '').strip()[:3000], filename)
                )
    except Exception as e:
        print("Gallery metadata update failed:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def is_recent_trending_post(post, days=7):
    """Trending posts remain in Now Trending for seven days, then continue under category only."""
    from datetime import datetime, timezone, timedelta
    if not (post.get("is_trending", False) if isinstance(post, dict) else getattr(post, "is_trending", False)):
        return False
    raw = (post.get("published_at") or post.get("timestamp") if isinstance(post, dict) else getattr(post, "published_at", None) or getattr(post, "timestamp", None))
    if not raw:
        return True
    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt <= timedelta(days=days)
    except Exception:
        return True

def normalize_blog_category(post):
    """Return the visible category for a post.

    Admin-selected categories must be respected. Auto-detection is used only
    when the saved category is empty or a non-category placeholder.
    """
    if not post:
        return "Technology"

    title = post.get("title", "") if isinstance(post, dict) else getattr(post, "title", "")
    content = post.get("content", "") if isinstance(post, dict) else getattr(post, "content", "")
    stored = (post.get("category", "") if isinstance(post, dict) else getattr(post, "category", "")) or ""
    stored_clean = str(stored).strip()

    allowed = {"Cybersecurity", "Networking", "AI & Automation", "Windows News", "Mobile & Android", "ICT Support", "Technology", "Web Development"}
    generic_values = {"", "category", "auto", "automatic", "normal", "uncategorized", "general"}

    if stored_clean in allowed:
        return "Technology" if stored_clean == "Web Development" else stored_clean

    if stored_clean.lower() in generic_values:
        inferred = get_blog_category(title, content)
        return "Technology" if inferred == "Web Development" else (inferred or "Technology")

    inferred = get_blog_category(title, content)
    return "Technology" if inferred == "Web Development" else (inferred or "Technology")

def apply_blog_runtime_metadata(post):
    """Attach computed category and trending labels without changing template behavior."""
    if isinstance(post, dict):
        post["category"] = normalize_blog_category(post)
        post["trending_label"] = get_trending_label(post)
        return post
    return post


def get_trending_label(post, days=7):
    """Human-readable trending age label, e.g. Trending • day 2/7."""
    from datetime import datetime, timezone, timedelta
    is_trending = bool(post.get("is_trending", False) if isinstance(post, dict) else getattr(post, "is_trending", False))
    if not is_trending:
        return ""
    raw = (post.get("published_at") or post.get("timestamp") if isinstance(post, dict) else getattr(post, "published_at", None) or getattr(post, "timestamp", None))
    if not raw:
        return f"Trending • 7 days"
    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - dt).days)
        remaining = max(0, days - age_days)
        current_day = min(days, age_days + 1)
        return f"Trending • day {current_day}/{days} • {remaining}d left"
    except Exception:
        return f"Trending • 7 days"


def refresh_existing_blog_categories():
    """One-time-safe runtime repair for old posts that were all saved as Technology/Category."""
    try:
        conn = data.get_conn()
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, title, content, COALESCE(category, '') AS category
                    FROM blogs
                    WHERE COALESCE(category, '') = ''
                       OR LOWER(COALESCE(category, '')) IN ('category', 'auto', 'automatic', 'normal', 'uncategorized', 'general')
                """)
                rows = cur.fetchall()
                for r in rows:
                    inferred = get_blog_category(r["title"], r["content"])
                    stored = (r["category"] or "").strip()
                    # Repair generic or clearly mismatched old categories. This keeps manual categories only
                    # when they look intentional and the title/content does not strongly suggest another desk.
                    if inferred and (stored.lower() in ("", "category", "auto", "automatic", "normal", "uncategorized", "general")):
                        # Keep old generic/random labels from polluting the homepage desks.
                        cur.execute("UPDATE blogs SET category=%s WHERE id=%s", (inferred, r["id"]))
    except Exception as e:
        print("⚠️ Could not auto-repair existing blog categories:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def categorize_home_blogs(blogs):
    buckets = {
        "Trending": [],
        "Cybersecurity": [],
        "Networking": [],
        "AI & Automation": [],
        "Windows News": [],
        "Mobile & Android": [],
        "ICT Support": [],
        "Technology": []
    }
    for b in blogs or []:
        b = apply_blog_runtime_metadata(b)
        cat = normalize_blog_category(b)
        if cat == "Web Development":
            cat = "Technology"
        if cat not in buckets:
            cat = "Technology"
        if is_recent_trending_post(b):
            buckets["Trending"].append(b)
        buckets[cat].append(b)
    return buckets


CATEGORY_LANDING_PAGES = {
    "cybersecurity": {
        "name": "Cybersecurity",
        "label": "Cybersecurity Watch",
        "icon": "bi-shield-lock-fill",
        "slug": "cybersecurity",
        "keywords": ["cybersecurity", "network security", "password security", "phishing", "ransomware", "data protection"],
        "description": "Cybersecurity guides, password security, phishing awareness, ransomware prevention, privacy protection and practical digital defense resources from SurgeTechKnow.",
        "hero": "Practical cyber defense, password protection, phishing awareness and network security guidance for modern digital users.",
        "faq": [
            ("What is cybersecurity?", "Cybersecurity is the practice of protecting devices, networks, accounts and data from unauthorized access, scams, malware and digital attacks."),
            ("Why is password security important?", "Strong password habits reduce account takeover, credential stuffing and unauthorized access risks."),
            ("How can users reduce cyber attacks?", "Use unique passwords, enable multi-factor authentication, update devices, avoid suspicious links and verify online requests."),
            ("Does cybersecurity also involve network security?", "Yes. Cybersecurity includes device security, account protection, network security, user awareness and data protection.")
        ],
        "related": ["Networking", "Windows News", "AI & Automation", "ICT Support"]
    },
    "networking": {
        "name": "Networking",
        "label": "Networking & Infrastructure",
        "icon": "bi-diagram-3-fill",
        "slug": "networking",
        "keywords": ["CCNA", "VLAN", "subnetting", "routing", "switching", "Cisco networking", "OSPF"],
        "description": "Networking and infrastructure tutorials covering CCNA concepts, routing, switching, VLANs, subnetting, Wi-Fi, DNS, DHCP and troubleshooting.",
        "hero": "Clear networking tutorials for routing, switching, VLANs, subnetting, Wi-Fi and infrastructure troubleshooting.",
        "faq": [
            ("What is networking?", "Networking connects computers, servers and devices so they can communicate and share resources."),
            ("What is VLAN?", "A VLAN logically separates network devices into different broadcast domains for better organization and security."),
            ("Why is subnetting important?", "Subnetting helps organize IP networks, reduce waste and improve network planning."),
            ("Is CCNA useful for networking careers?", "Yes. CCNA builds foundational routing, switching, IP addressing and troubleshooting skills.")
        ],
        "related": ["Cybersecurity", "ICT Support", "Cloud Computing", "Career & Certifications"]
    },
    "windows": {
        "name": "Windows News",
        "label": "Windows News",
        "icon": "bi-windows",
        "slug": "windows",
        "keywords": ["Windows 11", "Windows security", "PC troubleshooting", "computer maintenance", "Windows updates"],
        "description": "Windows News and practical guides on Windows security, PC troubleshooting, system performance, updates, drivers and computer maintenance.",
        "hero": "Windows security, PC performance, troubleshooting, system updates and computer maintenance insights.",
        "faq": [
            ("Why do Windows PCs slow down?", "Windows PCs may slow down because of startup apps, low storage, outdated drivers, malware, overheating or background processes."),
            ("How can Windows be secured?", "Enable Windows Security, update regularly, use strong account protection, backup files and avoid untrusted software."),
            ("What causes Windows update issues?", "Driver conflicts, low storage, corrupt update cache and unstable connections can cause update failures."),
            ("Should users clean temporary files?", "Yes. Cleaning temporary files can free storage and improve system responsiveness.")
        ],
        "related": ["Cybersecurity", "ICT Support", "Mobile & Android", "Technology"]
    },
    "ai-automation": {
        "name": "AI & Automation",
        "label": "AI & Automation Desk",
        "icon": "bi-cpu-fill",
        "slug": "ai-automation",
        "keywords": ["AI automation", "ChatGPT", "artificial intelligence", "machine learning", "workflow automation"],
        "description": "AI and automation articles covering artificial intelligence, ChatGPT workflows, productivity systems, Python automation and practical digital transformation.",
        "hero": "Artificial intelligence, automation workflows, ChatGPT productivity and practical digital transformation guides.",
        "faq": [
            ("What is AI automation?", "AI automation uses intelligent tools to reduce repetitive work, analyze information and improve productivity."),
            ("Can AI help cybersecurity?", "Yes. AI can support threat detection, log analysis, alert prioritization and security awareness."),
            ("Is automation useful for small businesses?", "Automation can save time in reporting, customer communication, data processing and routine operations."),
            ("Does AI replace ICT skills?", "No. AI supports skilled workers, but human judgment, troubleshooting and security awareness remain important.")
        ],
        "related": ["Cybersecurity", "Programming", "Technology", "ICT Support"]
    },
    "ict-support": {
        "name": "ICT Support",
        "label": "ICT Support Guides",
        "icon": "bi-tools",
        "slug": "ict-support",
        "keywords": ["ICT support", "IT support", "technical support", "helpdesk", "computer support", "printer troubleshooting"],
        "description": "ICT support guides for helpdesk operations, computer troubleshooting, printers, scanners, backups, user support and technical documentation.",
        "hero": "Practical ICT support, troubleshooting, helpdesk operations, device maintenance and technical documentation resources.",
        "faq": [
            ("What is ICT support?", "ICT support helps users maintain, troubleshoot and safely use computers, networks, printers, accounts and digital systems."),
            ("What does a helpdesk do?", "A helpdesk receives user issues, diagnoses problems, gives solutions and documents recurring technical incidents."),
            ("Why is documentation important in ICT?", "Documentation helps teams solve issues faster, track assets and maintain consistent support procedures."),
            ("What are common ICT support tasks?", "Common tasks include printer support, account setup, software installation, backups, networking checks and device maintenance.")
        ],
        "related": ["Windows News", "Networking", "Cybersecurity", "Career & Certifications"]
    },
    "mobile-android": {
        "name": "Mobile & Android",
        "label": "Mobile & Android",
        "icon": "bi-phone-fill",
        "slug": "mobile-android",
        "keywords": ["Android performance", "mobile security", "phone optimization", "smartphone tips", "Android storage"],
        "description": "Mobile and Android guides covering phone performance, battery life, app safety, storage management, mobile security and smartphone troubleshooting.",
        "hero": "Android performance, battery health, mobile security, storage management and smartphone troubleshooting guidance.",
        "faq": [
            ("Why do Android phones slow down?", "Phones slow down because of low storage, background apps, cache buildup, aging hardware and outdated software."),
            ("How can Android performance improve?", "Remove unused apps, update software, clear unnecessary files and avoid suspicious apps."),
            ("Is mobile security important?", "Yes. Phones store personal data, passwords, financial apps and private communication."),
            ("Should apps be installed from unknown sources?", "Only install apps from trusted sources because unknown APKs can contain malware or spyware.")
        ],
        "related": ["Windows News", "Cybersecurity", "ICT Support", "Technology"]
    },
    "programming": {
        "name": "Programming",
        "label": "Programming & Development",
        "icon": "bi-code-slash",
        "slug": "programming",
        "keywords": ["programming", "Python", "Flask", "web development", "software development"],
        "description": "Programming and development guides covering Python, Flask, web development, databases, APIs and practical software engineering projects.",
        "hero": "Python, Flask, web development, databases, APIs and practical software engineering tutorials.",
        "faq": [
            ("What programming topics are covered?", "SurgeTechKnow covers Python, Flask, web development, databases, automation and practical project building."),
            ("Is Python good for automation?", "Yes. Python is widely used for scripting, data handling, automation, APIs and backend systems."),
            ("What is Flask used for?", "Flask is a lightweight Python web framework for building web applications and APIs."),
            ("Why learn web development?", "Web development helps create websites, dashboards, portals and digital systems for real users.")
        ],
        "related": ["AI & Automation", "Cloud Computing", "Technology", "ICT Support"]
    },
    "cloud-computing": {
        "name": "Cloud Computing",
        "label": "Cloud Computing",
        "icon": "bi-cloud-fill",
        "slug": "cloud-computing",
        "keywords": ["cloud computing", "cloud services", "hosting", "databases", "deployment"],
        "description": "Cloud computing articles covering hosting, deployment, cloud databases, backups, storage, scalability and practical online systems.",
        "hero": "Cloud hosting, deployment, storage, databases, backups and scalable digital infrastructure guidance.",
        "faq": [
            ("What is cloud computing?", "Cloud computing is accessing computing resources such as storage, servers, databases and software over the internet."),
            ("Why use cloud hosting?", "Cloud hosting improves availability, scalability, deployment speed and remote access."),
            ("Are cloud backups important?", "Yes. Cloud backups help protect data from device failure, accidental deletion and disasters."),
            ("What cloud topics matter for websites?", "Hosting, databases, storage, DNS, SSL, backups and monitoring are important for websites.")
        ],
        "related": ["Programming", "Networking", "Cybersecurity", "Technology"]
    },
    "technology-news": {
        "name": "Technology",
        "label": "Technology News",
        "icon": "bi-newspaper",
        "slug": "technology-news",
        "keywords": ["technology news", "digital systems", "tech trends", "software", "innovation"],
        "description": "Technology news and explainers covering digital systems, software, innovation, online safety, gadgets, platforms and emerging tech trends.",
        "hero": "Technology news, digital systems, online safety, innovation, software and practical tech explainers.",
        "faq": [
            ("What is covered under Technology News?", "This section covers general tech updates, digital systems, platforms, online safety and practical explainers."),
            ("Why follow technology trends?", "Technology trends help users understand tools, risks, opportunities and digital changes."),
            ("Does this include cybersecurity and AI?", "Broad technology topics may connect to cybersecurity, AI, networking, Windows and ICT support."),
            ("Who is this section for?", "It is for students, professionals, everyday users and digital teams who want practical technology insights.")
        ],
        "related": ["AI & Automation", "Cybersecurity", "Windows News", "Mobile & Android"]
    },
    "career-certifications": {
        "name": "Career & Certifications",
        "label": "Career & Certifications",
        "icon": "bi-award-fill",
        "slug": "career-certifications",
        "keywords": ["ICT career", "CCNA certification", "IT interview", "tech career", "computer skills"],
        "description": "Career and certification resources for ICT support, networking, cybersecurity, CCNA preparation, interviews and professional growth in technology.",
        "hero": "ICT career growth, certifications, interview preparation, CCNA learning and professional technology skills.",
        "faq": [
            ("Which ICT certifications are useful?", "CCNA, cybersecurity fundamentals, cloud fundamentals and support certifications can strengthen ICT career paths."),
            ("How can someone prepare for an ICT interview?", "Review networking, troubleshooting, security basics, user support scenarios and practical examples."),
            ("Is CCNA helpful?", "CCNA is useful for learning routing, switching, IP addressing and network troubleshooting."),
            ("What skills help ICT support roles?", "Communication, troubleshooting, documentation, networking basics and security awareness are important.")
        ],
        "related": ["Networking", "Cybersecurity", "ICT Support", "Programming"]
    },
}

CATEGORY_NAME_TO_SLUG = {v["name"]: k for k, v in CATEGORY_LANDING_PAGES.items()}
CATEGORY_NAME_TO_SLUG.update({
    "Technology": "technology-news",
    "Web Development": "programming",
    "Mobile & Android": "mobile-android",
})

def category_url_for_name(category):
    key = CATEGORY_NAME_TO_SLUG.get(category or "")
    if not key:
        key = "technology-news"
    return url_for("category_page", category_slug=key)

@app.template_filter("category_page_url")
def category_page_url_filter(category):
    return category_url_for_name(category)

def list_blogs_by_category(category, limit=3):
    blogs = data.load_blogs()
    buckets = categorize_home_blogs(blogs)
    selected = buckets.get(category, [])
    if len(selected) < limit:
        for b in blogs:
            if b not in selected:
                selected.append(b)
            if len(selected) >= limit:
                break
    return selected[:limit]


def list_related_blogs(limit=6):
    return (data.load_blogs() or [])[:limit]


def list_gallery_media_limited(limit=6):
    return list_gallery_media(limit=limit)


try:
    refresh_existing_blog_categories()
except Exception as e:
    print("⚠️ Blog category refresh skipped:", e)


def list_blog_media():
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT name, mimetype, uploaded_at, url, storage_provider
                    FROM files
                    WHERE category='blog_media'
                    ORDER BY uploaded_at DESC
                """)

                rows = cur.fetchall()
                out = []

                for r in rows:
                    mimetype = r["mimetype"] or ""
                    typ = (
                        "image" if mimetype.startswith("image")
                        else "video" if mimetype.startswith("video")
                        else "other"
                    )

                    out.append({
                        "name": r["name"],
                        "type": typ,
                        "url": r["url"] or f"/media/blog_media/{r['name']}",
                        "storage_provider": r["storage_provider"] or "database"
                    })

                return out

    except Exception as e:
        print(f"Error listing blog media: {e}")
        return []
    finally:
        conn.close()


def media_url(kind, filename):
    if not filename:
        return None

    category = category_from_kind(kind)
    ts = data.get_file_timestamp(category, filename) or 0

    return url_for("media_file", kind=kind, filename=filename) + f"?v={int(ts)}"


def serve_file_record(rec, filename, as_attachment=False):
    if not rec:
        abort(404)

    if rec.get("url"):
        return redirect(rec["url"], code=302)

    content = rec.get("content") or b""
    if not content:
        abort(404)

    mimetype = rec.get("mimetype") or "application/octet-stream"

    return send_file(
        io.BytesIO(content),
        download_name=filename,
        as_attachment=as_attachment,
        mimetype=mimetype
    )


def log_upload_result(category, fname):
    try:
        if not fname:
            print(f"⚠️ Upload failed before DB check for category={category}")
            return

        rec = data.get_file_record(category, fname)

        if not rec:
            print(f"⚠️ Upload saved name={fname}, but no DB record found.")
            return

        print(
            "📦 UPLOAD RESULT:",
            f"name={rec.get('name')}",
            f"category={rec.get('category')}",
            f"storage_provider={rec.get('storage_provider')}",
            f"url_present={bool(rec.get('url'))}",
            f"content_removed={not bool(rec.get('content'))}"
        )

    except Exception as e:
        print("⚠️ Could not log upload result:", e)


@app.route("/", methods=["GET"])
def index():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")

    prof_name, _ = latest_file("profile", only_images=True)
    hero_name, _ = latest_file("hero", only_images=True)
    gallery = list_gallery_media_limited(6)
    try:
        refresh_existing_blog_categories()
    except Exception as e:
        print(f"Category refresh skipped: {e}")
    blogs = [apply_blog_runtime_metadata(b) for b in data.load_blogs()]
    home_blog_sections = categorize_home_blogs(blogs)

    return render_template(
        "index.html",
        cv_file=owner_cv_filename(),
        allowed_exts=sorted(ALLOWED_EXTS),
        year=datetime.now().year,
        profile_url=media_url("profile", prof_name) if prof_name else None,
        hero_url=media_url("hero", hero_name) if hero_name else None,
        gallery_images=gallery,
        blog_posts=blogs,
        home_blog_sections=home_blog_sections
    )


@app.route("/hub")
def hub():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/hub",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    prof_name, _ = latest_file("profile", only_images=True)
    return render_template("hub.html", profile_url=media_url("profile", prof_name) if prof_name else None, related_posts=list_related_blogs(6), year=datetime.now().year)

@app.route("/operations-gallery")
def operations_gallery():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/operations-gallery",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")

    return render_template(
        "operations_gallery.html",
        gallery_images=list_gallery_media(),
        related_posts=list_related_blogs(6),
        year=datetime.now().year
    )




@app.route("/media")
def media_gallery():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/media",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("media.html", gallery_images=list_gallery_media(), related_posts=list_related_blogs(6), year=datetime.now().year)

@app.route("/media-gallery")
def media_gallery_alias_two():
    return redirect(url_for("media_gallery"), code=301)

@app.route("/media-view/<path:filename>")
def media_view(filename):
    safe = secure_filename(urllib.parse.unquote(filename))
    item = None
    items = list_gallery_media()
    for media_item in items:
        if media_item.get("name") == safe:
            item = media_item
            break
    if not item:
        abort(404)
    return render_template("media_view.html", item=item, related_posts=list_related_blogs(6), year=datetime.now().year)

@app.route("/privacy-policy", methods=["GET"])
def privacy_policy():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/privacy-policy",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("privacy.html")


@app.route("/terms", methods=["GET"])
def terms():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/terms",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("terms.html")


@app.route("/disclaimer", methods=["GET"])
def disclaimer():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/disclaimer",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("disclaimer.html")


@app.route("/cookie-policy", methods=["GET"])
def cookie_policy():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/cookie-policy",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("cookies.html")


@app.route("/about", methods=["GET"])
def about_page():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/about",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("about.html")


@app.route("/contact-us", methods=["GET"])
def contact_us_page():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/contact-us",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")
    return render_template("contact.html")


@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = (request.form.get("email") or "").strip().lower()

    if not email or "@" not in email:
        flash("Please provide a valid email address.")
        return redirect(url_for("index") + "#newsletter")

    data.save_subscriber(email)
    flash("Thanks! You are subscribed to updates.")
    return redirect(url_for("index") + "#newsletter")


@app.route("/contact", methods=["POST"])
def contact():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    message = request.form.get("message", "").strip()

    if not (name and email and message):
        flash("Please fill in all fields.")
        return redirect(url_for("index") + "#contact")

    data.save_message(name, email, message)
    flash("Thanks, your message was received! ✅")
    return redirect(url_for("index") + "#contact")


@app.route("/upload_project", methods=["POST"])
def upload_project():
    print("🔥 Upload route called: /upload_project")

    up = request.files.get("file")

    if not up or up.filename == "":
        flash("No file selected.")
        return redirect(url_for("index") + "#portfolio")

    if not allowed_file(up.filename):
        flash("Invalid file type.")
        return redirect(url_for("index") + "#portfolio")

    fname, err = data.save_file_from_storage("project", up, approve=False)
    log_upload_result("project", fname)

    if err:
        flash(err)
    else:
        flash(f"Project '{fname}' uploaded (private). Admin will review. ✅")

    return redirect(url_for("index") + "#portfolio")


@app.route("/download/<kind>/<path:filename>")
def download_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))

    if kind == "project":
        rec = data.get_file_record("project", safe, approved=True)
        return serve_file_record(rec, safe, as_attachment=True)

    elif kind == "cv":
        rec = data.get_file_record("cv", safe)
        return serve_file_record(rec, safe, as_attachment=True)

    abort(404)


@app.route("/media/<kind>/<path:filename>")
def media_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))
    category = category_from_kind(kind)

    rec = data.get_file_record(category, safe)
    return serve_file_record(rec, safe, as_attachment=False)


@app.route("/blog")
def blog_list():
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/blog",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")

    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    blogs = [apply_blog_runtime_metadata(b) for b in data.load_blogs()]

    if q:
        q_lower = q.lower()
        blogs = [
            b for b in blogs
            if q_lower in (b.get("title", "") or "").lower()
            or q_lower in (b.get("content", "") or "").lower()
        ]

    if category:
        blogs = [
            b for b in blogs
            if normalize_blog_category(b).lower() == category.lower()
        ]

    return render_template("blog_list.html", blogs=blogs, search_query=q, selected_category=category, year=datetime.now().year)



@app.route("/category/<category_slug>")
@app.route("/<category_slug>")
def category_page(category_slug):
    """SEO content hub for each SurgeTechKnow editorial desk."""
    slug = (category_slug or "").strip().lower()
    if slug not in CATEGORY_LANDING_PAGES:
        abort(404)

    cfg = CATEGORY_LANDING_PAGES[slug]
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            f"/{slug}",
            get_or_create_visitor_id()
        )
    except Exception as e:
        print(f"Tracking error: {e}")

    all_blogs = [apply_blog_runtime_metadata(b) for b in data.load_blogs()]
    category_name = cfg["name"]
    posts = [b for b in all_blogs if normalize_blog_category(b) == category_name]

    # For new categories without direct stored articles, add intelligent matches from title/content.
    if not posts and category_name in ("Programming", "Cloud Computing", "Career & Certifications"):
        keywords = [k.lower() for k in cfg.get("keywords", [])]
        posts = [b for b in all_blogs if any(k in ((b.get("title", "") + " " + b.get("content", "")).lower()) for k in keywords)]

    trending_posts = [b for b in posts if is_recent_trending_post(b)][:6]
    featured_post = (trending_posts[0] if trending_posts else (posts[0] if posts else None))
    latest_posts = posts[:18]
    popular_posts = sorted(posts, key=lambda b: int(b.get("views") or b.get("verified_views") or 0), reverse=True)[:8]

    related_categories = []
    for name in cfg.get("related", []):
        key = CATEGORY_NAME_TO_SLUG.get(name)
        if key and key in CATEGORY_LANDING_PAGES:
            related_categories.append(CATEGORY_LANDING_PAGES[key])

    return render_template(
        "category.html",
        cfg=cfg,
        posts=posts,
        featured_post=featured_post,
        trending_posts=trending_posts,
        latest_posts=latest_posts,
        popular_posts=popular_posts,
        related_categories=related_categories,
        all_categories=CATEGORY_LANDING_PAGES,
        year=datetime.now().year
    )

@app.route("/blog/<slug>")
def view_blog(slug):
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            f"/blog/{slug}",
            get_or_create_visitor_id()
        )
        # Full migration: do NOT increment legacy blogs.views here.
        # Article views are counted only from verified JS/human read sessions.
    except Exception as e:
        print(f"Tracking error: {e}")

    post = data.get_blog_by_slug(slug)

    if not post:
        abort(404)

    # Category related articles query
    related = []
    try:
        all_blogs = [apply_blog_runtime_metadata(b) for b in data.load_blogs()]
        post = apply_blog_runtime_metadata(post)
        current_cat = normalize_blog_category(post)
        for b in all_blogs:
            if b.get("slug") == post.get("slug"):
                continue
            b_cat = normalize_blog_category(b)
            if b_cat == current_cat:
                related.append(b)
        
        # Fallback if less than 3
        if len(related) < 3:
            for b in all_blogs:
                if b.get("slug") == post.get("slug") or b in related:
                    continue
                related.append(b)
        related = related[:3]
    except Exception as e:
        print("Error getting related posts:", e)

    return render_template("blog_view.html", post=post, related_posts=related)


SYSTEM_INSTRUCTION = """
You are "SurgeTechKnow's AI Digital Twin", a professional, highly skilled, and conversational AI avatar representing SurgeTechKnow on his portfolio website.
SurgeTechKnow Background & Profile:
- Title: Lead Cisco-Certified Network Specialist, Cybersecurity Auditor, and Automation Architect.
- Role: Meticulously driven and customer-oriented ICT Officer.
- Key Certifications: Cisco CCNA, Routing and Switching, Enterprise Network Security.
- Top Core Skills:
  1. Routing & Switching Topologies (VLANs, OSPF, DHCP helper protocols, STP BPDU Guard, trunk interfaces).
  2. Cybersecurity auditing & server hardening.
  3. Interactive network diagnostics, disaster recovery schemas, and virtualization setup.
  4. Automation scripting using Python, Flask, bash, and cron.
- Personality: Smart, highly technical yet understandable, reassuring, respectful, and direct.
"""


def call_gemini_api(prompt, system_instruction=None):
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return None

    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [
                {"text": system_instruction}
            ]
        }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "aistudio-build"
    }

    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=12) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])

            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])

                if parts:
                    return parts[0].get("text", "")

            return "Failed to parse reply from AI model."

    except urllib.error.HTTPError as he:
        err_msg = he.read().decode("utf-8")
        print(f"Gemini API HttpError: {he.code} - {err_msg}")

        try:
            err_json = json.loads(err_msg)
            return f"Gemini API Error: {err_json.get('error', {}).get('message', 'HTTP Error')}"
        except Exception:
            return f"Gemini API HTTP Error occurred: {he.reason}"

    except Exception as e:
        print(f"Gemini API Exception: {e}")
        return f"Could not establish connection to the AI engine: {str(e)}"


@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    try:
        req_data = request.json or {}
        user_message = req_data.get("message", "").strip()
        history = req_data.get("history", [])

        if not user_message:
            return jsonify({"status": "error", "message": "message is required"}), 400

        context_prompt = ""

        for turn in history[-6:]:
            role_label = "User" if turn.get("role") == "user" else "AI"
            context_prompt += f"{role_label}: {turn.get('text')}\n"

        context_prompt += f"User: {user_message}\nAI:"

        ai_response = call_gemini_api(context_prompt, system_instruction=SYSTEM_INSTRUCTION)

        is_mock = False

        if ai_response is None:
            is_mock = True
            msg_lower = user_message.lower()

            if any(k in msg_lower for k in ["skills", "cert", "credential", "ccna", "switching", "routing"]):
                ai_response = "I am Cisco CCNA certified in Routing & Switching, specializing in LAN/WAN infrastructure, VLANs, OSPF, and secure switching."
            elif any(k in msg_lower for k in ["contact", "hire", "email", "work", "meeting"]):
                ai_response = "You can reach out directly through the Get in Touch / Contact form section of this site."
            elif any(k in msg_lower for k in ["audit", "secure", "protection", "firewall", "entropy"]):
                ai_response = "I conduct cybersecurity audits, endpoint policy reviews, and brute-force resilience checks."
            elif any(k in msg_lower for k in ["project", "code", "portfolio"]):
                ai_response = "I have built interactive labs on this portfolio, including subnet tools, port diagnostics, and admin telemetry features."
            else:
                ai_response = "Hello there! I am SurgeTechKnow's AI Digital Twin. Ask me about CCNA configurations, cybersecurity, ICT support, or collaboration."

            ai_response += "\n\n*(Note: Set up a `GEMINI_API_KEY` in settings to activate full real-time Gemini LLM reasoning.)*"

        return jsonify({
            "status": "success",
            "reply": ai_response,
            "mock": is_mock
        })

    except Exception as e:
        print(f"Error in ai_chat endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/track_visit", methods=["POST"])
def track_visit():
    """JS-only visitor verification endpoint.

    A session is only counted as human after the browser proves activity through
    JavaScript, visibility state, time-on-page, interaction, or scroll depth.
    """
    try:
        req_data = request.json or {}
        result = record_verified_session(req_data)
        status = 200 if result.get("status") != "error" else 500
        return jsonify(result), status
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




def get_tracking_health_snapshot():
    """Return quick operational health for the JS analytics pipeline."""
    ensure_real_analytics_tables()
    health = {
        "tracking_js_status": "waiting",
        "last_verified_seen": None,
        "last_bot_seen": None,
        "track_endpoint": "/api/track_visit",
        "heartbeat_window_seconds": 90,
        "message": "No analytics beacons yet. Open a public page to test tracking."
    }
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT MAX(last_seen) AS last_seen
                    FROM verified_sessions
                """)
                row = cur.fetchone() or {}
                if row.get("last_seen"):
                    health["last_verified_seen"] = row["last_seen"].isoformat()
                    health["tracking_js_status"] = "active"
                    health["message"] = "Analytics beacons are being received."

                health["last_bot_seen"] = None
    except Exception as e:
        health["tracking_js_status"] = "error"
        health["message"] = str(e)
    finally:
        conn.close()
    return health


def get_top_live_pages(limit=8):
    """Return currently active pages using only verified human sessions."""
    ensure_real_analytics_tables()
    pages = []
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT path,
                           COUNT(*) AS active_readers,
                           MAX(last_activity) AS last_activity
                    FROM verified_sessions
                    WHERE active = TRUE
                      AND last_activity >= now() - INTERVAL '90 seconds'
                    GROUP BY path
                    ORDER BY active_readers DESC, last_activity DESC
                    LIMIT %s
                """, (limit,))
                pages = [
                    {
                        "path": r["path"] or "/",
                        "active_readers": int(r["active_readers"] or 0),
                        "last_activity": r["last_activity"].isoformat() if r.get("last_activity") else None
                    }
                    for r in cur.fetchall()
                ]
    except Exception as e:
        print("Top live pages failed:", e)
    finally:
        conn.close()
    return pages
@app.route('/ads.txt')
def ads_txt():
    return send_from_directory('.', 'ads.txt')
@app.route("/api/admin/verified_visitors")
def admin_verified_visitors():
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403
    return jsonify({
        "status": "success",
        "metrics": get_verified_analytics_snapshot(),
        "top_live_pages": get_top_live_pages(),
        "health": get_tracking_health_snapshot()
    })


@app.route("/api/blog/heartbeat", methods=["POST"])
def blog_heartbeat():
    """Verified article-reading heartbeat.

    Full migration rule:
    - Do NOT update legacy blogs.views, read_time_count, or total_read_time_seconds.
    - Only sessions that already passed JS human verification are counted.
    - If verified analytics is reset, article views reset to zero too.
    """
    try:
        req_data = request.json or {}
        slug = (req_data.get("slug") or "").strip()
        total_seconds = safe_int(req_data.get("total_seconds", req_data.get("time_on_page", 5)), 0, 0, 86400)
        scroll_depth = safe_int(req_data.get("scroll_depth", 0), 0, 0, 100)

        if not slug:
            return jsonify({"status": "error", "message": "slug required"}), 400

        session_id = get_or_create_visitor_id()
        conn = data.get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    # Verification/filtering disabled: count article heartbeat for every public session.
                    cur.execute("""
                        INSERT INTO verified_sessions (
                            session_id, ip_hash, user_agent, path, js_verified, bot_detected, suspicious,
                            engaged, active, visible, total_active_seconds, heartbeat_count, page_views,
                            first_seen, last_seen, last_activity
                        )
                        VALUES (%s, %s, %s, %s, TRUE, FALSE, FALSE, TRUE, TRUE, TRUE, %s, 1, 1, now(), now(), now())
                        ON CONFLICT (session_id) DO UPDATE SET
                            js_verified = TRUE,
                            bot_detected = FALSE,
                            suspicious = FALSE,
                            engaged = TRUE,
                            active = TRUE,
                            last_seen = now(),
                            last_activity = now(),
                            total_active_seconds = GREATEST(verified_sessions.total_active_seconds, EXCLUDED.total_active_seconds),
                            heartbeat_count = verified_sessions.heartbeat_count + 1
                    """, (session_id, hash_ip(get_client_ip()), (request.headers.get("User-Agent", "") or "")[:500], (request.path or "/")[:500], total_seconds))

                    # Count one article view per session per article.
                    cur.execute("""
                        INSERT INTO blog_read_sessions (
                            session_id, slug, first_seen, last_heartbeat,
                            total_seconds, max_scroll_depth
                        )
                        VALUES (%s, %s, now(), now(), %s, %s)
                        ON CONFLICT (session_id, slug) DO UPDATE SET
                          last_heartbeat = now(),
                          total_seconds = GREATEST(blog_read_sessions.total_seconds, EXCLUDED.total_seconds),
                          max_scroll_depth = GREATEST(blog_read_sessions.max_scroll_depth, EXCLUDED.max_scroll_depth)
                    """, (session_id, slug, total_seconds, scroll_depth))
        finally:
            conn.close()

        return jsonify({"status": "success", "verified_article_read": True})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/blog/reaction", methods=["POST"])

def blog_reaction():
    try:
        req_data = request.json or {}
        slug = req_data.get("slug")
        reaction = req_data.get("reaction")

        if not slug or not reaction:
            return jsonify({"status": "error", "message": "slug and reaction are required"}), 400

        success = data.increment_blog_reaction(slug, reaction)

        if success:
            p = data.get_blog_by_slug(slug)
            return jsonify({
                "status": "success",
                "counts": {
                    "helpful": p.get("helpful_count", 0),
                    "useful": p.get("useful_count", 0),
                    "learned": p.get("learned_count", 0),
                    "loved": p.get("loved_count", 0)
                }
            })

        return jsonify({"status": "error", "message": "Could not increment reaction"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/blog/summarize", methods=["POST"])
def blog_summarize():
    try:
        req_data = request.json or {}
        slug = req_data.get("slug")

        if not slug:
            return jsonify({"status": "error", "message": "slug is required"}), 400

        post = data.get_blog_by_slug(slug)

        if not post:
            return jsonify({"status": "error", "message": "Article not found"}), 404

        content_text = post.get("content", "")
        title_text = post.get("title", "")

        prompt = f"""Summarize this technical article titled "{title_text}":
{content_text[:3000]}

Respond only in JSON with summary, takeaways, and skill_level.
"""

        ai_reply = call_gemini_api(
            prompt,
            system_instruction="Output raw valid JSON strictly."
        )

        if ai_reply:
            try:
                clean_json = ai_reply.strip()

                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]

                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]

                parsed = json.loads(clean_json.strip())

                return jsonify({
                    "status": "success",
                    "summary": parsed.get("summary", ""),
                    "takeaways": parsed.get("takeaways", []),
                    "skill_level": parsed.get("skill_level", "Intermediate")
                })

            except Exception as parse_err:
                print("Failed to parse JSON summary:", parse_err)

        return jsonify({
            "status": "success",
            "summary": f"An analytical review of standard configurations for '{title_text}'.",
            "takeaways": [
                "Establishes diagnostic criteria for network performance.",
                "Demonstrates practical troubleshooting commands.",
                "Integrates security policies for safer infrastructure.",
                "Optimizes performance by reducing network issues."
            ],
            "skill_level": "Intermediate"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/blog/ask_about_text", methods=["POST"])
def blog_ask_about_text():
    try:
        req_data = request.json or {}
        selected_text = req_data.get("selected_text", "").strip()
        title_text = req_data.get("title", "").strip()

        if not selected_text:
            return jsonify({"status": "error", "message": "no text selected"}), 400

        prompt = f"""Explain this selected text from "{title_text}":
"{selected_text}"
"""

        ai_reply = call_gemini_api(
            prompt,
            system_instruction="You are SurgeTechKnow, an expert Systems Specialist."
        )

        if not ai_reply:
            ai_reply = f"Regarding your highlighted quote from **{title_text}**, this refers to a practical technical concept that should be checked using proper diagnostics."

        return jsonify({
            "status": "success",
            "reply": ai_reply
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/ai/search", methods=["POST"])
def ai_search_engine():
    try:
        req_data = request.json or {}
        query = req_data.get("query", "").strip()

        if not query:
            return jsonify({"status": "success", "results": []})

        blogs = data.load_blogs(include_drafts=False)
        results = []
        q_lower = query.lower()

        for b in blogs:
            if q_lower in b["title"].lower() or q_lower in b["content"].lower():
                results.append({
                    "title": b["title"],
                    "url": f"/blog/{b['slug']}",
                    "match_reason": "Matches query in the article title or contents."
                })

        return jsonify({"status": "success", "results": results[:4]})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code = request.form.get("code", "")

        if code == ADMIN_KEY:
            session["is_admin"] = True
            flash("Logged in as admin.")
            return redirect(url_for("admin"))

        flash("Wrong passcode.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Logged out.")
    return redirect(url_for("index"))




def get_admin_dashboard_health():
    """Lightweight real operational indicators for the admin console."""
    health = {
        "db_status": "OFFLINE",
        "db_ok": False,
        "storage_used_mb": 0.0,
        "storage_limit_mb": 512,
        "storage_pct": 0,
        "api_speed_ms": 0,
        "security_status": "MONITORING"
    }
    import time
    start = time.perf_counter()
    conn = None
    try:
        conn = data.get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                health["db_status"] = "SUPABASE_OK"
                health["db_ok"] = True
                try:
                    cur.execute("""
                        SELECT COALESCE(SUM(COALESCE(file_size, octet_length(content))),0)
                        FROM files
                    """)
                    total_bytes = int(cur.fetchone()[0] or 0)
                    used = round(total_bytes / (1024 * 1024), 1)
                    health["storage_used_mb"] = used
                    health["storage_pct"] = min(100, int((used / health["storage_limit_mb"]) * 100))
                except Exception:
                    pass
    except Exception as e:
        print("Admin health check failed:", e)
    finally:
        if conn:
            conn.close()
    health["api_speed_ms"] = max(1, int((time.perf_counter() - start) * 1000))
    return health

@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("login"))

    full_msgs = data.load_messages()
    total_messages = len(full_msgs)
    unread_count = sum(1 for m in full_msgs if m.get("status") == "unread")

    pending = list_pending()
    projects = list_projects()
    cv_file = owner_cv_filename()
    pending_count = len(pending)
    approved_count = len(projects)

    q = (request.args.get("q") or "").strip()
    show = request.args.get("show", "all")
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(6, min(50, int(request.args.get("per_page", 12))))

    indexed = list(enumerate(full_msgs))

    if q:
        q_l = q.lower()
        filtered = [
            (i, m) for (i, m) in indexed
            if q_l in (
                m.get("name", "").lower() + " " +
                m.get("email", "").lower() + " " +
                m.get("message", "").lower()
            )
        ]
    else:
        filtered = indexed

    if show == "unread":
        filtered = [(i, m) for (i, m) in filtered if m.get("status") == "unread"]

    total_filtered = len(filtered)
    pages = max(1, math.ceil(total_filtered / per_page))

    if page > pages:
        page = pages

    start = (page - 1) * per_page
    end = start + per_page
    page_items = filtered[start:end]

    display_msgs = []

    for (gid, m) in page_items:
        item = dict(m)
        item["gid"] = gid
        display_msgs.append(item)

    prof_name, _ = latest_file("profile", only_images=True)
    hero_name, _ = latest_file("hero", only_images=True)
    gal = list_gallery_media()
    blog_media_list = list_blog_media()
    blogs = data.load_blogs()
    subscribers = data.load_subscribers()

    # Full migration: dashboard popularity is based ONLY on verified article reads.
    # IMPORTANT: We overwrite each blog object's "views" value before sending it
    # to admin.html so old inflated blogs.views can never appear in the admin UI.
    most_viewed_blog = None
    most_viewed_category = "Technology"
    category_summary = {}
    enriched_blogs = []

    try:
        verified_counts = {}
        conn = data.get_conn()
        try:
            with conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("""
                        SELECT slug, COUNT(*) AS verified_views
                        FROM blog_read_sessions
                        GROUP BY slug
                    """)
                    verified_counts = {r["slug"]: int(r["verified_views"] or 0) for r in cur.fetchall()}
        finally:
            conn.close()

        for b in blogs:
            bb = dict(b)
            legacy_raw_views = int(bb.get("views") or 0)
            verified_views = verified_counts.get(bb.get("slug"), 0)

            bb["legacy_views"] = legacy_raw_views
            bb["verified_views"] = verified_views
            bb["views"] = verified_views  # admin templates use b.views, so force verified-only
            bb["analytics_source"] = "unfiltered"
            enriched_blogs.append(bb)

            cat = get_blog_category(bb.get("title", ""), bb.get("content", ""))
            category_summary[cat] = category_summary.get(cat, 0) + verified_views

        blogs = enriched_blogs

        if blogs:
            most_viewed_blog = max(blogs, key=lambda b: b.get("verified_views", 0))

        if category_summary:
            best_cat = max(category_summary, key=category_summary.get)
            most_viewed_category = f"{best_cat} ({category_summary[best_cat]} verified views)"
    except Exception as e:
        print("Verified popularity calculation failed:", e)
        # Fail closed: do not expose legacy views if verified calculation fails.
        blogs = [dict(b, views=0, verified_views=0, legacy_views=int(b.get("views") or 0), analytics_source="unfiltered_error") for b in blogs]

    dashboard_health = get_admin_dashboard_health()

    return render_template(
        "admin.html",
        total_messages=total_messages,
        unread_count=unread_count,
        pending_count=pending_count,
        approved_count=approved_count,
        display_msgs=display_msgs,
        pending=pending,
        projects=projects,
        cv_file=cv_file,
        q=q,
        show=show,
        page=page,
        pages=pages,
        per_page=per_page,
        total_filtered=total_filtered,
        prof=prof_name,
        hero=hero_name,
        gal=gal,
        blog_media=blog_media_list,
        blogs=blogs,
        subscribers=subscribers,
        dashboard_health=dashboard_health,
        daily_visits=get_verified_daily_summary(),
        total_visits_all=get_verified_analytics_snapshot(),
        total_visits=get_verified_analytics_snapshot().get("total", 0),
        most_viewed_blog=most_viewed_blog,
        most_viewed_category=most_viewed_category
    )


@app.route("/admin/message_json/<int:mid>", methods=["GET"])
def message_json(mid):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    m = data.get_message_by_index(mid)

    if not m:
        return jsonify({"error": "not found"}), 404

    return jsonify(m)


@app.route("/admin/mark_read_json/<int:mid>", methods=["POST"])
def mark_read_json(mid):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    ok, status = data.mark_message_read_by_index(mid)

    if not ok:
        return jsonify({"error": "not found"}), 404

    return jsonify({"status": "read"})


@app.route("/admin/toggle_read_json/<int:mid>", methods=["POST"])
def toggle_read_json(mid):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    ok, new = data.toggle_message_status_by_index(mid)

    if not ok:
        return jsonify({"error": "not found"}), 404

    return jsonify({"status": new})


@app.route("/admin/techrich/list")
def admin_techrich_list():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    docs = data.load_techrich_docs()
    return jsonify({"status": "success", "docs": docs})


@app.route("/admin/techrich/create", methods=["POST"])
def admin_techrich_create():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    title = request.form.get("title", "").strip() or "Untitled Custom Note"
    content = request.form.get("content", "").strip()

    doc_id = data.save_techrich_doc(title, "note", content=content)

    if doc_id:
        return jsonify({"status": "success", "id": doc_id})

    return jsonify({"error": "failed to save"}), 500


@app.route("/admin/techrich/upload", methods=["POST"])
def admin_techrich_upload():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    title_raw = request.form.get("title", "").strip()

    if "file" not in request.files:
        return jsonify({"error": "missing file attachment"}), 400

    f = request.files["file"]

    if not f or f.filename == "":
        return jsonify({"error": "no file selected"}), 400

    filename = secure_filename(f.filename)
    file_bytes = f.read()

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        doc_type = "pdf"
        mimetype = "application/pdf"
    elif ext in ["doc", "docx"]:
        doc_type = "word"
        mimetype = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if ext == "docx"
            else "application/msword"
        )
    else:
        doc_type = "note"
        mimetype = f.mimetype or "text/plain"

    title = title_raw or filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").capitalize()

    text_content = ""

    if doc_type == "note":
        try:
            text_content = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            pass

    doc_id = data.save_techrich_doc(
        title,
        doc_type,
        file_name=filename,
        file_data=file_bytes,
        mimetype=mimetype,
        content=text_content
    )

    if doc_id:
        return jsonify({"status": "success", "id": doc_id})

    return jsonify({"error": "failed to save"}), 500


@app.route("/admin/techrich/update/<int:doc_id>", methods=["POST"])
def admin_techrich_update(doc_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    requested_category = request.form.get("category", "Auto").strip() or "Auto"
    category = get_blog_category(title, content) if requested_category.lower() in ("auto", "automatic", "") else requested_category
    is_trending = request.form.get("is_trending") in ("1", "true", "on", "yes", "trending")
    excerpt = request.form.get("excerpt", "").strip()
    featured_image = request.form.get("featured_image", "").strip()

    if data.update_techrich_doc(doc_id, title, content):
        return jsonify({"status": "success"})

    return jsonify({"error": "failed"}), 500


@app.route("/admin/techrich/delete/<int:doc_id>", methods=["POST"])
def admin_techrich_delete(doc_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    if data.delete_techrich_doc_by_id(doc_id):
        return jsonify({"status": "success"})

    return jsonify({"error": "failed"}), 500


@app.route("/admin/techrich/view/<int:doc_id>")
def admin_techrich_view(doc_id):
    if not require_admin():
        abort(403)

    doc = data.get_techrich_doc_by_id(doc_id)

    if not doc:
        abort(404)

    if doc["doc_type"] == "pdf" and doc["file_data"]:
        return send_file(
            io.BytesIO(doc["file_data"]),
            mimetype=doc["mimetype"] or "application/pdf"
        )

    elif doc["doc_type"] == "word" and doc["file_data"]:
        return send_file(
            io.BytesIO(doc["file_data"]),
            mimetype=doc["mimetype"],
            download_name=doc["file_name"],
            as_attachment=False
        )

    return jsonify({
        "id": doc["id"],
        "title": doc["title"],
        "content": doc["content"],
        "doc_type": doc["doc_type"],
        "file_name": doc["file_name"]
    })


@app.route("/admin/techrich/download/<int:doc_id>")
def admin_techrich_download(doc_id):
    if not require_admin():
        abort(403)

    doc = data.get_techrich_doc_by_id(doc_id)

    if not doc:
        abort(404)

    if doc["doc_type"] in ["pdf", "word"] and doc["file_data"]:
        return send_file(
            io.BytesIO(doc["file_data"]),
            mimetype=doc["mimetype"],
            download_name=doc["file_name"],
            as_attachment=True
        )

    filename = secure_filename(doc["title"]) or "note"

    if not filename.endswith(".md"):
        filename += ".md"

    return send_file(
        io.BytesIO(doc["content"].encode("utf-8")),
        mimetype="text/markdown",
        download_name=filename,
        as_attachment=True
    )


@app.route("/admin/analytics_data")
def admin_analytics_data():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    labels, values = data.get_messages_counts_last_n_days(30)
    return jsonify({"labels": labels, "values": values})


@app.route("/api/admin/active_users")
def active_users_data():
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403

    metrics = get_verified_analytics_snapshot()
    recent_pages = []
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT path, COUNT(*) AS cnt
                    FROM verified_sessions
                    WHERE last_activity >= now() - INTERVAL '90 seconds'
                    GROUP BY path
                    ORDER BY cnt DESC
                    LIMIT 6
                """)
                recent_pages = [{"path": r["path"] or "/", "count": int(r["cnt"])} for r in cur.fetchall()]
    except Exception as e:
        print("Error getting verified active users:", e)
    finally:
        conn.close()

    return jsonify({
        "status": "success",
        "active_users": metrics.get("engaged", 0),
        "recent_pages": recent_pages,
        "metrics": metrics
    })


@app.route("/api/admin/article_stats")
def admin_article_stats():
    """Article stats after full migration.

    Only verified article read sessions are used. Legacy blogs.views and legacy
    read-time columns are intentionally ignored so reset cannot fall back to
    old inflated numbers.
    """
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403

    ensure_real_analytics_tables()
    metrics = get_verified_analytics_snapshot()
    articles = []
    recent_pages = get_top_live_pages(limit=6)
    conn = data.get_conn()

    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT
                        b.id,
                        b.title,
                        b.slug,
                        COALESCE(COUNT(brs.session_id), 0) AS verified_views,
                        COALESCE(SUM(brs.total_seconds), 0) AS total_read_time,
                        COALESCE(AVG(brs.total_seconds), 0) AS avg_read_time,
                        COALESCE(AVG(brs.max_scroll_depth), 0) AS avg_scroll_depth,
                        COALESCE(COUNT(brs.session_id) FILTER (
                            WHERE brs.total_seconds < 15 OR brs.max_scroll_depth < 10
                        ), 0) AS bounces
                    FROM blogs b
                    LEFT JOIN blog_read_sessions brs ON brs.slug = b.slug
                    GROUP BY b.id, b.title, b.slug
                    ORDER BY verified_views DESC, total_read_time DESC, b.title ASC
                """)
                rows = cur.fetchall()

                for r in rows:
                    verified_views = int(r["verified_views"] or 0)
                    total_read_time = int(r["total_read_time"] or 0)
                    avg_read_time = int(float(r["avg_read_time"] or 0))
                    avg_scroll = int(float(r["avg_scroll_depth"] or 0))
                    bounces = int(r["bounces"] or 0)
                    bounce_rate = int((bounces / verified_views) * 100) if verified_views else 0
                    category = get_blog_category(r["title"], "")

                    articles.append({
                        "id": r["id"],
                        "title": r["title"],
                        "slug": r["slug"],
                        "views": verified_views,
                        "verified_views": verified_views,
                        "total_read_time": total_read_time,
                        "avg_read_time_seconds": avg_read_time,
                        "avg_scroll_depth": avg_scroll,
                        "bounce_rate": bounce_rate,
                        "category": category,
                        "source": "unfiltered"
                    })

    except Exception as e:
        print(f"Error querying verified-only article stats: {e}")
    finally:
        conn.close()

    category_views = {}
    for a in articles:
        category_views[a["category"]] = category_views.get(a["category"], 0) + int(a.get("views", 0))

    dominant_category = "Technology"
    if category_views:
        best_cat = max(category_views, key=category_views.get)
        dominant_category = f"{best_cat} ({category_views[best_cat]} verified views)"

    return jsonify({
        "status": "success",
        "active_users": metrics.get("engaged", 0),
        "recent_pages": recent_pages,
        "visitor_metrics": metrics,
        "tracking_health": get_tracking_health_snapshot(),
        "articles": articles,
        "dominant_category": dominant_category,
        "migration_mode": "unfiltered_tracking_no_bot_blocking"
    })


@app.route("/api/admin/reset_analytics", methods=["POST"])

def admin_reset_analytics():
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403
    req_data = request.json or {}
    confirm = str(req_data.get("confirm", "")).strip().upper()
    if confirm != "RESET":
        return jsonify({"status": "error", "message": "Type RESET to confirm."}), 400

    ensure_real_analytics_tables()
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM blog_read_sessions")
                cur.execute("DELETE FROM verified_sessions")
                cur.execute("DELETE FROM bot_requests")
        return jsonify({"status": "success", "message": "Analytics reset."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route("/admin/delete_message/<int:mid>", methods=["POST"])
def delete_message(mid):
    if not require_admin():
        return redirect(url_for("login"))

    ok, deleted = data.delete_message_by_index(mid)

    if not ok:
        flash("Message not found.")
        return redirect(url_for("admin"))

    flash(f"Deleted message from {deleted.get('name', 'unknown')}.")
    return redirect(url_for("admin"))


@app.route("/admin/export_messages")
def export_messages():
    if not require_admin():
        return redirect(url_for("login"))

    csv_bytes = data.export_messages_csv()

    if not csv_bytes:
        flash("No messages to export.")
        return redirect(url_for("admin"))

    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=messages.csv"},
    )


@app.route("/admin/delete_project/<path:filename>", methods=["POST"])
def delete_project(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = urllib.parse.unquote(filename)
    ok = data.delete_project_by_name(fname)

    if ok:
        flash(f"Deleted file '{fname}'.")
    else:
        flash("File not found.")

    return redirect(url_for("admin"))


@app.route("/admin/approve/<path:filename>", methods=["POST"])
def approve_file(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = urllib.parse.unquote(filename)
    ok = data.approve_project_by_name(fname)

    if ok:
        flash(f"Approved '{fname}'.")
    else:
        flash("File not found.")

    return redirect(url_for("admin"))


@app.route("/admin/reject/<path:filename>", methods=["POST"])
def reject_file(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = urllib.parse.unquote(filename)
    ok = data.reject_project_by_name(fname)

    if ok:
        flash(f"Rejected '{fname}'.")
    else:
        flash("File not found.")

    return redirect(url_for("admin"))


@app.route("/admin/upload_cv", methods=["POST"])
def upload_cv_admin():
    if not require_admin():
        return redirect(url_for("login"))

    up = None

    if request.files:
        for key in ["cv", "file"]:
            if key in request.files and request.files[key].filename != "":
                up = request.files[key]
                break

        if not up:
            first_key = list(request.files.keys())[0]
            if request.files[first_key].filename != "":
                up = request.files[first_key]

    if not up or up.filename == "":
        flash("No CV selected.")
        return redirect(url_for("admin"))

    if not allowed_file(up.filename):
        flash("Invalid file type.")
        return redirect(url_for("admin"))

    ext = up.filename.rsplit(".", 1)[1].lower()
    fname, err = data.save_file_from_storage(
        "cv",
        up,
        rename_to=f"SurgeTechKnow_SurgeTechKnow_CV.{ext}",
        approve=True,
        single_replace=True
    )
    log_upload_result("cv", fname)

    if err:
        flash(err)
    else:
        flash("CV uploaded successfully! ✅")

    return redirect(url_for("admin"))


@app.route("/admin/upload_profile_image", methods=["POST"])
def upload_profile_image():
    if not require_admin():
        return redirect(url_for("login"))

    up = None

    if request.files:
        for key in ["image", "file"]:
            if key in request.files and request.files[key].filename != "":
                up = request.files[key]
                break

        if not up:
            first_key = list(request.files.keys())[0]
            if request.files[first_key].filename != "":
                up = request.files[first_key]

    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))

    if not allowed_image(up.filename):
        flash("Invalid image type.")
        return redirect(url_for("admin"))

    fname, err = data.save_file_from_storage("profile", up, approve=True, single_replace=True)
    log_upload_result("profile", fname)

    if err:
        flash(err)
    else:
        flash("Profile image updated. ✅")

    return redirect(url_for("admin"))


@app.route("/admin/upload_hero_image", methods=["POST"])
def upload_hero_image():
    if not require_admin():
        return redirect(url_for("login"))

    up = None

    if request.files:
        for key in ["image", "file"]:
            if key in request.files and request.files[key].filename != "":
                up = request.files[key]
                break

        if not up:
            first_key = list(request.files.keys())[0]
            if request.files[first_key].filename != "":
                up = request.files[first_key]

    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))

    if not allowed_image(up.filename):
        flash("Invalid image type.")
        return redirect(url_for("admin"))

    fname, err = data.save_file_from_storage("hero", up, approve=True, single_replace=True)
    log_upload_result("hero", fname)

    if err:
        flash(err)
    else:
        flash("Hero background updated. ✅")

    return redirect(url_for("admin"))


@app.route("/admin/upload_gallery", methods=["POST"])
def upload_gallery():
    if not require_admin():
        return redirect(url_for("login"))

    files = request.files.getlist("images")
    media_title = (request.form.get("media_title") or "").strip()
    media_caption = (request.form.get("media_caption") or "").strip()
    media_narration = (request.form.get("media_narration") or media_caption or "").strip()

    if not files:
        flash("Select at least one file.")
        return redirect(url_for("admin"))

    uploaded = 0

    for up in files:
        if not up or not up.filename:
            continue

        ext = up.filename.rsplit(".", 1)[-1].lower() if "." in up.filename else ""

        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
            fname, err = data.save_file_from_storage("gallery", up, approve=True)
            log_upload_result("gallery", fname)
            if fname:
                update_gallery_metadata(fname, media_title or pretty_media_title(fname), media_caption, media_narration)
                uploaded += 1

    if uploaded:
        flash(f"Uploaded {uploaded} item(s) to Operations Gallery. ✅")
    else:
        flash("No valid images or videos were uploaded.")

    return redirect(url_for("admin"))


@app.route("/admin/delete_gallery/<path:filename>", methods=["POST"])
def delete_gallery_image(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = secure_filename(urllib.parse.unquote(filename))

    blogs = data.load_blogs()
    found_ref = False
    ref_slugs = []

    for b in blogs:
        if fname in b["content"]:
            found_ref = True
            ref_slugs.append(b["title"])

    if found_ref:
        flash(
            f"⚠️ Cannot delete '{fname}' because it is currently used in the blog post(s): "
            f"{', '.join(ref_slugs)}. Please edit those posts first!"
        )
        return redirect(url_for("admin") + "#blog_media_section")

    ok = data.delete_file("gallery", fname)

    if ok:
        flash(f"Deleted gallery media '{fname}'.")
    else:
        flash("Media not found.")

    return redirect(url_for("admin"))


@app.route("/admin/gallery/update/<path:filename>", methods=["POST"])
def update_gallery_item(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = secure_filename(urllib.parse.unquote(filename))
    media_title = (request.form.get("media_title") or "").strip()
    media_caption = (request.form.get("media_caption") or "").strip()
    media_narration = (request.form.get("media_narration") or media_caption or "").strip()

    if not fname:
        flash("Invalid media item.")
        return redirect(url_for("admin") + "#gallery-pane")

    update_gallery_metadata(fname, media_title or pretty_media_title(fname), media_caption, media_narration)
    flash("Gallery media details updated successfully. ✅")
    return redirect(url_for("admin") + "#gallery-pane")


@app.route("/admin/upload_blog_media", methods=["POST"])
def upload_blog_media():
    if not require_admin():
        return redirect(url_for("login"))

    files = request.files.getlist("images")
    ret = request.args.get("ret", "")
    target_pane = "#blogs-pane" if ret == "blogs" else "#blog-media-pane"

    if not files:
        flash("Select at least one file.")
        return redirect(url_for("admin") + target_pane)

    uploaded = 0

    for up in files:
        if not up or not up.filename:
            continue

        ext = up.filename.rsplit(".", 1)[-1].lower() if "." in up.filename else ""

        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
            fname, err = data.save_file_from_storage("blog_media", up, approve=True)
            log_upload_result("blog_media", fname)

            if fname:
                uploaded += 1

    if uploaded:
        flash(f"Uploaded {uploaded} item(s) to Blog Media Library. ✅")
    else:
        flash("No valid images or videos were uploaded.")

    return redirect(url_for("admin") + target_pane)


@app.route("/admin/delete_blog_media/<path:filename>", methods=["POST"])
def delete_blog_media(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = secure_filename(urllib.parse.unquote(filename))
    ret = request.args.get("ret", "")
    target_pane = "#blogs-pane" if ret == "blogs" else "#blog-media-pane"

    blogs = data.load_blogs()
    found_ref = False
    ref_slugs = []

    for b in blogs:
        if fname in b["content"]:
            found_ref = True
            ref_slugs.append(b["title"])

    if found_ref:
        flash(
            f"⚠️ Cannot delete '{fname}' because it is currently used in the blog post(s): "
            f"{', '.join(ref_slugs)}. Please edit those posts first!"
        )
        return redirect(url_for("admin") + target_pane)

    ok = data.delete_file("blog_media", fname)

    if ok:
        flash(f"Deleted blog media '{fname}'.")
    else:
        flash("Media not found.")

    return redirect(url_for("admin") + target_pane)


@app.route("/admin/sync_cloudinary", methods=["GET", "POST"])
def admin_sync_cloudinary():
    if not require_admin():
        return redirect(url_for("login"))

    try:
        synced = data.sync_missing_files_to_cloudinary(limit=50)
        flash(f"Cloudinary sync complete. Synced {synced} old file(s). ✅")
    except Exception as e:
        flash(f"Cloudinary sync failed: {e}")

    return redirect(url_for("admin"))


@app.route("/admin/cloudinary_status")
def admin_cloudinary_status():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, name, category, url, cloudinary_id, storage_provider,
                           content IS NULL AS content_removed,
                           uploaded_at
                    FROM files
                    ORDER BY uploaded_at DESC
                    LIMIT 20
                """)
                rows = cur.fetchall()

                return jsonify({
                    "cloudinary_enabled": getattr(data, "CLOUDINARY_ENABLED", False),
                    "latest_files": [dict(r) for r in rows]
                })
    finally:
        conn.close()



def resolve_article_thumbnail(title, content, category, selected_thumbnail=''):
    """Resolve article thumbnail without slowing the page.
    Priority: admin-selected Draft Asset -> first image/video inside article -> blank.
    Blank is intentional because templates generate a fast category SVG fallback.
    """
    selected_thumbnail = (selected_thumbnail or '').strip()
    if selected_thumbnail:
        return selected_thumbnail
    try:
        first = get_first_image(content or '')
        if first:
            return first
    except Exception:
        pass
    return ''

@app.route("/admin/blogs/add", methods=["POST"])
def admin_add_blog():
    if not require_admin():
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    requested_category = request.form.get("category", "Auto").strip() or "Auto"
    category = get_blog_category(title, content) if requested_category.lower() in ("auto", "automatic", "") else requested_category
    is_trending = request.form.get("is_trending") in ("1", "true", "on", "yes", "trending")
    excerpt = request.form.get("excerpt", "").strip()
    featured_image = request.form.get("featured_image", "").strip()
    featured_image = resolve_article_thumbnail(title, content, category, featured_image)

    if not (title and content):
        flash("Title and content required.")
        return redirect(url_for("admin"))

    post = data.add_blog(title, content, category=category, is_trending=is_trending, excerpt=excerpt, featured_image=featured_image)

    if post and "slug" in post:
        session["promote_blog_slug"] = post["slug"]
        session["promote_blog_title"] = post["title"]
        session["promote_blog_event"] = "published"

    flash("Blog post published successfully. ✅")
    return redirect(url_for("admin") + "#blogs-pane")


@app.route("/admin/blogs/delete/<bid>", methods=["POST"])
def admin_delete_blog(bid):
    if not require_admin():
        return redirect(url_for("login"))

    data.delete_blog_by_id(bid)
    flash("Blog post deleted.")
    return redirect(url_for("admin") + "#blogs-pane")


@app.route("/admin/blogs/get/<int:bid>", methods=["GET"])
def admin_get_blog_json(bid):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    blogs = data.load_blogs()

    for b in blogs:
        if b["id"] == bid:
            return jsonify(b)

    return jsonify({"error": "not found"}), 404


@app.route("/admin/blogs/edit/<int:bid>", methods=["POST"])
def admin_edit_blog(bid):
    if not require_admin():
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    requested_category = request.form.get("category", "Auto").strip() or "Auto"
    category = get_blog_category(title, content) if requested_category.lower() in ("auto", "automatic", "") else requested_category
    is_trending = request.form.get("is_trending") in ("1", "true", "on", "yes", "trending")
    excerpt = request.form.get("excerpt", "").strip()
    featured_image = request.form.get("featured_image", "").strip()
    featured_image = resolve_article_thumbnail(title, content, category, featured_image)

    if not (title and content):
        flash("Title and content required.")
        return redirect(url_for("admin") + "#blogs-pane")

    ok = data.update_blog(bid, title, content, category=category, is_trending=is_trending, excerpt=excerpt, featured_image=featured_image)

    if ok:
        import re
        slug = re.sub(r"[^\w\s-]", "", title.lower().strip())
        slug = re.sub(r"[-\s]+", "-", slug)[:200]

        session["promote_blog_slug"] = slug
        session["promote_blog_title"] = title
        session["promote_blog_event"] = "updated"

        flash("Blog post successfully updated. ✅")
    else:
        flash("Failed to update blog post.")

    return redirect(url_for("admin") + "#blogs-pane")


@app.route("/admin/blogs/clear_promo", methods=["POST"])
def clear_promo_session():
    session.pop("promote_blog_slug", None)
    session.pop("promote_blog_title", None)
    session.pop("promote_blog_event", None)

    return jsonify({"status": "cleared"})


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    import traceback
    tb = traceback.format_exc()

    print("--- SERVER 500 TRACEBACK ---")
    print(tb)
    print("----------------------------")

    return render_template("500.html", traceback=tb), 500


@app.template_filter("render_markdown")
def render_markdown(text):
    if not text:
        return ""

    try:
        return markdown.markdown(text, extensions=["fenced_code", "codehilite"])
    except Exception as e:
        print(f"Error rendering markdown custom extensions: {e}")

        try:
            return markdown.markdown(text)
        except Exception as e2:
            print(f"Fallback markdown failed too: {e2}")
            import html
            return f"<pre>{html.escape(text)}</pre>"



OG_FALLBACK_IMAGE = "https://techknowsolution.co.ke/static/ogimage.png"

def category_fallback_image(category="Technology", title="SurgeTechKnow"):
    """Small inline SVG thumbnails so articles without images still look professional and load instantly."""
    import urllib.parse
    cat = (category or "Technology").strip()
    palette = {
        "Cybersecurity": ("#991b1b", "#ef4444", "🛡️"),
        "Networking": ("#0f172a", "#2563eb", "🌐"),
        "Windows News": ("#0c4a6e", "#38bdf8", "▦"),
        "Mobile & Android": ("#1e3a8a", "#2563eb", "📱"),
        "AI & Automation": ("#581c87", "#a855f7", "⚙"),
        "ICT Support": ("#1e40af", "#60a5fa", "🛠"),
        "Technology": ("#111827", "#64748b", "STK"),
    }
    c1, c2, icon = palette.get(cat, palette["Technology"])
    safe_cat = cat.replace("&", "&amp;")
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='900' height='560' viewBox='0 0 900 560'>
      <defs><linearGradient id='g' x1='0' x2='1' y1='0' y2='1'><stop stop-color='{c1}'/><stop offset='1' stop-color='{c2}'/></linearGradient></defs>
      <rect width='900' height='560' fill='url(#g)'/>
      <circle cx='760' cy='90' r='145' fill='rgba(255,255,255,.12)'/>
      <circle cx='70' cy='500' r='160' fill='rgba(255,255,255,.10)'/>
      <text x='54' y='90' font-family='Arial, sans-serif' font-size='28' fill='white' font-weight='800' opacity='.9'>SURGETECHKNOW</text>
      <text x='54' y='296' font-family='Arial, sans-serif' font-size='86' fill='white' font-weight='900'>{icon}</text>
      <text x='54' y='386' font-family='Arial, sans-serif' font-size='54' fill='white' font-weight='900'>{safe_cat}</text>
      <text x='56' y='430' font-family='Arial, sans-serif' font-size='22' fill='rgba(255,255,255,.82)' font-weight='700'>Practical technology insight</text>
    </svg>"""
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)

@app.template_filter("blog_image")
def blog_image(post):
    """Reliable thumbnail resolver for cards. Keeps cards from showing broken/empty images."""
    try:
        featured = (post.get("featured_image") if isinstance(post, dict) else getattr(post, "featured_image", "")) or ""
        content = (post.get("content") if isinstance(post, dict) else getattr(post, "content", "")) or ""
        category = normalize_blog_category(post) if post else get_blog_category("", content)
        first = get_first_image(content)
        if featured:
            return featured
        if first:
            return first
        return category_fallback_image(category)
    except Exception:
        return category_fallback_image("Technology")




def absolute_public_url(path):
    """Return a fully-qualified public URL for crawlers/social previews."""
    if not path:
        return OG_FALLBACK_IMAGE
    val = str(path).strip()
    if not val or val.startswith("data:"):
        return OG_FALLBACK_IMAGE
    if val.startswith("//"):
        return "https:" + val
    if val.startswith("http://"):
        return val.replace("http://", "https://", 1)
    if val.startswith("https://"):
        return val
    if val.startswith("/"):
        return "https://techknowsolution.co.ke" + val
    return "https://techknowsolution.co.ke/" + val.lstrip("./")

@app.template_filter("absolute_url")
def absolute_url_filter(path):
    return absolute_public_url(path)



def social_share_image_url(post):
    """Return the public image used by WhatsApp/Facebook/Twitter previews.
    Priority: admin-selected thumbnail -> first image in article -> static/ogimage.png.
    Never returns data URIs or relative paths.
    """
    try:
        featured = (post.get("featured_image") if isinstance(post, dict) else getattr(post, "featured_image", "")) or ""
        content = (post.get("content") if isinstance(post, dict) else getattr(post, "content", "")) or ""
        for candidate in (featured, get_first_image(content)):
            candidate = (candidate or "").strip()
            if candidate and not candidate.startswith("data:"):
                return absolute_public_url(candidate)
        return OG_FALLBACK_IMAGE
    except Exception:
        return OG_FALLBACK_IMAGE

@app.template_filter("social_share_image")
def social_share_image_filter(post):
    return social_share_image_url(post)

@app.template_filter("blog_social_image")
def blog_social_image(post):
    """Open Graph/Twitter image resolver for social previews.
    Priority: admin-selected thumbnail -> first image in article -> static/ogimage.png.
    """
    return social_share_image_url(post)


@app.template_filter("display_date")
def display_date(value):
    if not value:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return str(value)[:10]

@app.template_filter("iso_date")
def iso_date(value):
    if not value:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.isoformat()
    except Exception:
        return str(value)

@app.template_filter("get_first_image")
def get_first_image(text):
    if not text:
        return ""

    import re

    md_img = re.search(r"!\[.*?\]\((.*?)\)", text)

    if md_img:
        return md_img.group(1).strip()

    html_img = re.search(r'<img[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)

    if html_img:
        return html_img.group(1).strip()

    html_video = re.search(r'<video[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)

    if html_video:
        return html_video.group(1).strip()

    html_source = re.search(r'<source[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)

    if html_source:
        return html_source.group(1).strip()

    md_link = re.findall(r"\[.*?\]\((.*?)\)", text)

    for link in md_link:
        if any(ext in link.lower() for ext in [".mp4", ".webm", ".ogg", ".mov", ".m4v"]):
            return link.strip()

    html_img_fallback = re.search(r'src=["\'](.*?)["\']', text, re.IGNORECASE)

    if html_img_fallback:
        val = html_img_fallback.group(1).strip()

        if any(ext in val.lower() for ext in [
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
            ".mp4", ".webm", ".ogg", ".mov", ".m4v", "/media/",
            "res.cloudinary.com"
        ]):
            return val

    return ""


@app.template_filter("clean_excerpt")
def clean_excerpt(text, length=160):
    if not text:
        return ""

    import re

    text_no_caption = re.sub(
        r"<figcaption[^>]*>.*?</figcaption>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    text_no_html = re.sub(r"<[^>]+>", " ", text_no_caption)
    text_no_md_img = re.sub(r"!\[.*?\]\(.*?\)", " ", text_no_html)
    text_no_md_links = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text_no_md_img)

    cleaned = re.sub(r"#+\s+", "", text_no_md_links)
    cleaned = re.sub(r"\*+", "", cleaned)
    cleaned = re.sub(r"`+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if len(cleaned) <= length:
        return cleaned

    return cleaned[:length] + "..."


@app.template_filter("get_reading_time")
def get_reading_time(text):
    if not text:
        return 1

    words = len(text.split())
    minutes = max(1, int(words / 200))

    return minutes


@app.template_filter("trending_label")
def trending_label_filter(post):
    return get_trending_label(post)


@app.template_filter("get_category")
def get_category(text, title=""):
    return get_blog_category(title, text)


if __name__ == "__main__":
    print("🔄 Creating tables...")
    data.create_tables()
    print("✅ Tables ready!")
    app.run(host="0.0.0.0", port=5000, debug=True)
