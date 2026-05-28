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
    send_file, flash, abort, session, jsonify, Response
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
    ua = (user_agent or "").lower()
    if not ua or len(ua) < 12:
        return True
    return any(sig in ua for sig in BOT_SIGNATURES)


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

    if is_ignored_tracking_path(path):
        return {"status": "ignored", "reason": "ignored_path"}

    if is_bot_user_agent(user_agent):
        record_bot_request(path, user_agent, "bot_user_agent")
        return {"status": "ignored", "reason": "bot"}

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

    suspicious = False
    if screen_resolution.lower() == "unknown" or timezone.lower() in ("unknown", ""):
        suspicious = True
    if time_on_page > 43200:
        suspicious = True

    # Human verification requires JavaScript plus behavioral evidence.
    verified = bool(js_enabled and not suspicious and (time_on_page >= 15 or engaged_flag or scroll_depth >= 25))
    engaged = bool(verified and (engaged_flag or scroll_depth >= 25 or time_on_page >= 30))
    active = bool(verified and visible and (time_on_page >= 15 or engaged_flag or scroll_depth >= 25))

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
        "returning": 0, "avg_read_time": 0, "bounce_rate": 0, "scroll_completion": 0
    }
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT
                      COUNT(*) FILTER (WHERE js_verified = TRUE AND bot_detected = FALSE AND suspicious = FALSE) AS human_sessions,
                      COUNT(*) FILTER (WHERE js_verified = TRUE AND bot_detected = FALSE AND suspicious = FALSE AND engaged = TRUE) AS engaged_sessions,
                      COUNT(*) FILTER (WHERE js_verified = TRUE AND bot_detected = FALSE AND suspicious = FALSE AND active = TRUE AND last_activity >= now() - INTERVAL '90 seconds') AS active_readers,
                      COUNT(*) FILTER (WHERE suspicious = TRUE) AS suspicious_sessions,
                      COUNT(*) FILTER (WHERE returning_visitor = TRUE AND js_verified = TRUE AND suspicious = FALSE) AS returning_visitors,
                      COALESCE(AVG(total_active_seconds) FILTER (WHERE js_verified = TRUE AND suspicious = FALSE), 0) AS avg_read_time,
                      COALESCE(AVG(scroll_depth) FILTER (WHERE js_verified = TRUE AND suspicious = FALSE), 0) AS avg_scroll,
                      COUNT(*) FILTER (WHERE js_verified = TRUE AND suspicious = FALSE AND (total_active_seconds < 15 OR scroll_depth < 10)) AS bounces
                    FROM verified_sessions
                """)
                row = cur.fetchone() or {}
                cur.execute("SELECT COUNT(*) AS bots FROM bot_requests")
                bot_row = cur.fetchone() or {}

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
                    WHERE js_verified = TRUE AND suspicious = FALSE
                      AND first_seen >= now() - (%s * INTERVAL '1 day')
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
    base_url = "https://mga.techknowsols.gt.tc"

    static_pages = [
        {"loc": "/", "changefreq": "daily", "priority": "1.0"},
        {"loc": "/blog", "changefreq": "daily", "priority": "0.9"},
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
    """Force the public custom domain to avoid duplicate indexing on Render."""
    if "onrender.com" in request.host:
        query = request.query_string.decode("utf-8")
        target = "https://mga.techknowsols.gt.tc" + request.path
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

Sitemap: https://mga.techknowsols.gt.tc/sitemap.xml
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


def get_blog_category(title, content):
    combined = ((title or "") + " " + (content or "")).lower()

    if any(k in combined for k in ["cyber", "exploit", "mitigate", "security", "defense", "hack", "penetration", "firewall"]):
        return "Cybersecurity"
    elif any(k in combined for k in ["rout", "net", "ip", "cisco", "ccna", "switch", "router", "dhcp", "dns", "lan", "wan"]):
        return "Networking"
    elif any(k in combined for k in ["ai", "machine", "learning", "model", "neural", "predict", "automation", "workflow", "cron", "script"]):
        return "AI & Automation"
    elif any(k in combined for k in ["web", "html", "css", "flask", "react", "js", "ts", "javascript", "typescript", "frontend", "backend"]):
        return "Web Development"
    elif any(k in combined for k in ["ict", "support", "helpdesk", "comput", "hardware", "troubleshoot", "printer"]):
        return "ICT Support"

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


def list_gallery_media():
    return data.list_gallery_media()


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
    gallery = list_gallery_media()
    blogs = data.load_blogs()

    return render_template(
        "index.html",
        cv_file=owner_cv_filename(),
        allowed_exts=sorted(ALLOWED_EXTS),
        year=datetime.now().year,
        profile_url=media_url("profile", prof_name) if prof_name else None,
        hero_url=media_url("hero", hero_name) if hero_name else None,
        gallery_images=gallery,
        blog_posts=blogs
    )


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
    blogs = data.load_blogs()

    if q:
        q_lower = q.lower()
        blogs = [
            b for b in blogs
            if q_lower in (b.get("title", "") or "").lower()
            or q_lower in (b.get("content", "") or "").lower()
        ]

    return render_template("blog_list.html", blogs=blogs, search_query=q)


@app.route("/blog/<slug>")
def view_blog(slug):
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            f"/blog/{slug}",
            get_or_create_visitor_id()
        )
        data.increment_blog_views(slug)
    except Exception as e:
        print(f"Tracking error: {e}")

    post = data.get_blog_by_slug(slug)

    if not post:
        abort(404)

    # Category related articles query
    related = []
    try:
        all_blogs = data.load_blogs()
        current_cat = get_blog_category(post.get("title", ""), post.get("content", ""))
        for b in all_blogs:
            if b.get("slug") == post.get("slug"):
                continue
            b_cat = get_blog_category(b.get("title", ""), b.get("content", ""))
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
You are "Caleb Muga's AI Digital Twin", a professional, highly skilled, and conversational AI avatar representing Caleb Muga on his portfolio website.
Caleb's Background & Profile:
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
                ai_response = "Hello there! I am Caleb Muga's AI Digital Twin. Ask me about CCNA configurations, cybersecurity, ICT support, or collaboration."

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


@app.route("/api/admin/verified_visitors")
def admin_verified_visitors():
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403
    return jsonify({"status": "success", "metrics": get_verified_analytics_snapshot()})


@app.route("/api/blog/heartbeat", methods=["POST"])

def blog_heartbeat():
    try:
        req_data = request.json or {}
        slug = req_data.get("slug")
        is_new_view = req_data.get("new_view", False)

        if not slug:
            return jsonify({"status": "error", "message": "slug required"}), 400

        conn = data.get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    if is_new_view:
                        cur.execute("""
                            UPDATE blogs
                            SET read_time_count = COALESCE(read_time_count, 0) + 1
                            WHERE slug = %s
                        """, (slug,))
                    else:
                        cur.execute("""
                            UPDATE blogs
                            SET total_read_time_seconds = COALESCE(total_read_time_seconds, 0) + 5
                            WHERE slug = %s
                        """, (slug,))
        finally:
            conn.close()

        return jsonify({"status": "success"})

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
            system_instruction="You are Caleb Muga, an expert Systems Specialist."
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

    most_viewed_blog = None
    most_viewed_category = "Technology"
    category_summary = {}

    if blogs:
        most_viewed_blog = max(blogs, key=lambda b: b.get("views", 0))

        for b in blogs:
            cat = get_blog_category(b.get("title", ""), b.get("content", ""))
            category_summary[cat] = category_summary.get(cat, 0) + b.get("views", 0)

        if category_summary:
            best_cat = max(category_summary, key=category_summary.get)
            most_viewed_category = f"{best_cat} ({category_summary[best_cat]} views)"

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
                    WHERE js_verified = TRUE AND suspicious = FALSE
                      AND last_activity >= now() - INTERVAL '90 seconds'
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
    if not session.get("is_admin"):
        return jsonify({"error": "unauthorized"}), 403

    conn = data.get_conn()
    articles = []
    active_users = 1
    recent_pages = []

    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT COUNT(DISTINCT COALESCE(session_id, ip_address))
                    FROM site_visits
                    WHERE timestamp >= now() - INTERVAL '15 minutes'
                """)
                row = cur.fetchone()

                if row:
                    active_users = row[0] if row[0] > 0 else 1

                cur.execute("""
                    SELECT path, COUNT(*) as cnt
                    FROM site_visits
                    WHERE timestamp >= now() - INTERVAL '15 minutes'
                    GROUP BY path
                    ORDER BY cnt DESC
                    LIMIT 6
                """)

                recent_pages = [
                    {"path": r[0] if r[0] else "/", "count": r[1]}
                    for r in cur.fetchall()
                ]

                cur.execute("""
                    SELECT id, title, slug,
                           COALESCE(views, 0) as views,
                           COALESCE(total_read_time_seconds, 0) as total_read_time,
                           COALESCE(read_time_count, 0) as read_count
                    FROM blogs
                    ORDER BY views DESC
                """)

                rows = cur.fetchall()

                for r in rows:
                    views = r["views"]
                    rd_cnt = r["read_count"]
                    ttl_time = r["total_read_time"]

                    divisor = rd_cnt if rd_cnt > 0 else (views if views > 0 else 1)
                    avg_seconds = int(ttl_time / divisor)

                    category = get_blog_category(r["title"], "")

                    articles.append({
                        "id": r["id"],
                        "title": r["title"],
                        "slug": r["slug"],
                        "views": views,
                        "total_read_time": ttl_time,
                        "avg_read_time_seconds": avg_seconds,
                        "category": category
                    })

    except Exception as e:
        print(f"Error querying article stats: {e}")
    finally:
        conn.close()

    category_views = {}

    for a in articles:
        cat = a["category"]
        category_views[cat] = category_views.get(cat, 0) + a["views"]

    dominant_category = "Technology"

    if category_views:
        best_cat = max(category_views, key=category_views.get)
        dominant_category = f"{best_cat} ({category_views[best_cat]} views)"

    return jsonify({
        "status": "success",
        "active_users": max(1, active_users),
        "recent_pages": recent_pages,
        "articles": articles,
        "dominant_category": dominant_category
    })


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
        rename_to=f"Caleb_Muga_CV.{ext}",
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
                uploaded += 1

    if uploaded:
        flash(f"Uploaded {uploaded} item(s) to gallery. ✅")
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


@app.route("/admin/blogs/add", methods=["POST"])
def admin_add_blog():
    if not require_admin():
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not (title and content):
        flash("Title and content required.")
        return redirect(url_for("admin"))

    post = data.add_blog(title, content)

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

    if not (title and content):
        flash("Title and content required.")
        return redirect(url_for("admin") + "#blogs-pane")

    ok = data.update_blog(bid, title, content)

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


@app.template_filter("get_category")
def get_category(text, title=""):
    combined = (str(title or "") + " " + str(text or "")).lower()

    if any(keyword in combined for keyword in ["cyber", "exploit", "mitigate", "security", "defense", "hack", "penetration", "firewall"]):
        return "Cybersecurity"
    elif any(keyword in combined for keyword in ["rout", "net", "ip", "cisco", "ccna", "switch", "router", "dhcp", "dns", "lan", "wan"]):
        return "Networking"
    elif any(keyword in combined for keyword in ["ai", "machine learning", "model", "neural", "prediction", "automation", "workflow", "cron", "script"]):
        return "AI & Automation"
    elif any(keyword in combined for keyword in ["web", "html", "css", "flask", "react", "js", "ts", "javascript", "typescript", "frontend", "backend"]):
        return "Web Development"
    elif any(keyword in combined for keyword in ["ict", "support", "helpdesk", "comput", "hardware", "troubleshoot", "printer"]):
        return "ICT Support"

    return "Technology"


if __name__ == "__main__":
    print("🔄 Creating tables...")
    data.create_tables()
    print("✅ Tables ready!")
    app.run(host="0.0.0.0", port=5000, debug=True)
