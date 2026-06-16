import os
import io
import csv
import mimetypes
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
except Exception:
    cloudinary = None

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


# ---------------- Environment ----------------
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

CLOUDINARY_ENABLED = bool(
    cloudinary and
    CLOUDINARY_CLOUD_NAME and
    CLOUDINARY_API_KEY and
    CLOUDINARY_API_SECRET
)

if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )
    print("✅ Cloudinary configured successfully.")
else:
    print("⚠️ Cloudinary not configured. Files will fallback to database storage.")


# ---------------- Supabase/PostgreSQL Connection ----------------
def get_conn():
    return psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        sslmode="require"
    )


# ---------------- Table Creation ----------------
def create_tables():
    commands = [
        """
        CREATE TABLE IF NOT EXISTS messages (
          id SERIAL PRIMARY KEY,
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
          name TEXT,
          email TEXT,
          message TEXT,
          status TEXT DEFAULT 'unread'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscribers (
          id SERIAL PRIMARY KEY,
          email TEXT UNIQUE,
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS blogs (
          id SERIAL PRIMARY KEY,
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
          title TEXT,
          slug TEXT UNIQUE,
          content TEXT
        )
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 0;
        """,
        """
        CREATE TABLE IF NOT EXISTS files (
          id SERIAL PRIMARY KEY,
          name TEXT,
          category TEXT,
          content BYTEA,
          mimetype TEXT,
          uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
          approved BOOLEAN DEFAULT TRUE
        )
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS url TEXT;
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS cloudinary_id TEXT;
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS storage_provider TEXT DEFAULT 'database';
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS file_size BIGINT DEFAULT 0;
        """,
        """
        CREATE TABLE IF NOT EXISTS site_visits (
          id SERIAL PRIMARY KEY,
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
          ip_address TEXT,
          user_agent TEXT,
          path TEXT
        )
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS session_id TEXT;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS visit_type TEXT DEFAULT 'real';
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS js_enabled BOOLEAN DEFAULT false;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS screen_resolution TEXT;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS mouse_moved BOOLEAN DEFAULT false;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS browser TEXT;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS timezone TEXT;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS device_type TEXT;
        """,
        """
        ALTER TABLE site_visits ADD COLUMN IF NOT EXISTS engaged BOOLEAN DEFAULT false;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS total_read_time_seconds INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS read_time_count INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS helpful_count INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS useful_count INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS learned_count INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS loved_count INTEGER DEFAULT 0;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published';
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITH TIME ZONE;
        """,

        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'Technology';
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS is_trending BOOLEAN DEFAULT FALSE;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS excerpt TEXT;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS featured_image TEXT;
        """,
        """
        ALTER TABLE blogs ADD COLUMN IF NOT EXISTS meta_keywords TEXT;
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS media_title TEXT;
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS media_caption TEXT;
        """,
        """
        ALTER TABLE files ADD COLUMN IF NOT EXISTS media_narration TEXT;
        """,
        """
        CREATE TABLE IF NOT EXISTS techrich_docs (
          id SERIAL PRIMARY KEY,
          title TEXT,
          doc_type TEXT,
          file_name TEXT,
          file_data BYTEA,
          mimetype TEXT,
          content TEXT,
          created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
          updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """
    ]

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for ddl in commands:
                    cur.execute(ddl)

        print("✅ Tables created/updated successfully.")

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM techrich_docs")
                    cnt = cur.fetchone()[0]

                    if cnt == 0:
                        cur.execute(
                            """
                            INSERT INTO techrich_docs (title, doc_type, file_name, content, created_at, updated_at) VALUES 
                            ('Resolving VLAN Leakage and Trunk Port Encapsulation Standards', 'note', '', '# Comprehensive VLAN Encapsulation Standards\n\nThis article outlines enterprise diagnostic criteria for mitigating Inter-VLAN performance loss across Layer 2 and Layer 3 routing equipment.\n\n### Core Engineering Diagnostics\n- Check trunk status: `show interface trunk`\n- Configure dot1q routing encapsulation: `encapsulation dot1Q 10`\n- Native VLAN must match on switch port and subinterface.', now(), now()),
                            ('Analyzing Stuck OSPF Neighbor States (DR/BDR Election Loop)', 'note', '', '# Demystifying Stuck OSPF Neighbor States\n\nAdjacencies fail to transition into the **FULL** state.\n\n### Immediate Actions\n- Double-check MTU matching: `show ip ospf interface`\n- Run `ip ospf mtu-ignore` to debug descriptors exchange loops.', now(), now()),
                            ('Managing Sudden DHCP Autoconfiguration Loops (169.254.x.x)', 'note', '', '# Resolving Workstation APIPA (169.254.x.x) Issues\n\nAPIPA assignment points directly to a DHCP client network negotiation failure.\n\n### Diagnosis Protocol\n- Release current gateway configuration.\n- Verify active Layer 3 IP helper parameters pointing to active pools: `ip helper-address 192.168.1.10`', now(), now()),
                            ('Mitigating Broadcast packet storms inside Spanning Tree Networks', 'note', '', '# Mitigating Access Layer Network Loops with STP BPDU Guard\n\nLoop protection is strictly configured on all trunk and access terminals:\n```\nswitchport mode access\nspanning-tree portfast\nspanning-tree bpduguard enable\n```', now(), now())
                            """
                        )
                        print("✅ Seeded initial TechRich Knowledge Nodes successfully.")

        except Exception as se:
            print("⚠️ Skipping TechRich docs seeding:", se)

    except Exception as e:
        print(f"❌ Error creating tables: {e}")

    finally:
        conn.close()


# ---------------- Messages ----------------
def save_message(name: str, email: str, message: str):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (timestamp, name, email, message, status)
                    VALUES (now(), %s, %s, %s, %s)
                    """,
                    (name.strip(), email.strip(), message.strip(), "unread")
                )
    finally:
        conn.close()


def load_messages():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, timestamp, name, email, message, status
                    FROM messages
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()

                return [
                    {
                        "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else "",
                        "name": r["name"] or "",
                        "email": r["email"] or "",
                        "message": r["message"] or "",
                        "status": r["status"] or "unread",
                        "db_id": r["id"]
                    }
                    for r in rows
                ]
    finally:
        conn.close()


def save_all_messages(msgs):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages")

                for m in msgs:
                    ts = m.get("timestamp") or datetime.now(timezone.utc).isoformat()

                    try:
                        t = datetime.fromisoformat(ts)
                    except Exception:
                        t = datetime.now(timezone.utc)

                    cur.execute(
                        """
                        INSERT INTO messages (timestamp, name, email, message, status)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            t,
                            m.get("name", ""),
                            m.get("email", ""),
                            m.get("message", ""),
                            m.get("status", "unread")
                        )
                    )
    finally:
        conn.close()


def get_message_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, timestamp, name, email, message, status
                    FROM messages
                    ORDER BY id ASC
                    OFFSET %s LIMIT 1
                    """,
                    (idx,)
                )
                r = cur.fetchone()

                if not r:
                    return None

                return {
                    "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else "",
                    "name": r["name"] or "",
                    "email": r["email"] or "",
                    "message": r["message"] or "",
                    "status": r["status"] or "unread",
                    "db_id": r["id"]
                }
    finally:
        conn.close()


def toggle_message_status_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status FROM messages ORDER BY id ASC OFFSET %s LIMIT 1",
                    (idx,)
                )
                r = cur.fetchone()

                if not r:
                    return False, None

                mid, status = r
                new = "read" if status == "unread" else "unread"

                cur.execute(
                    "UPDATE messages SET status=%s WHERE id=%s",
                    (new, mid)
                )

                return True, new
    finally:
        conn.close()


def mark_message_read_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status FROM messages ORDER BY id ASC OFFSET %s LIMIT 1",
                    (idx,)
                )
                r = cur.fetchone()

                if not r:
                    return False, None

                mid, status = r

                cur.execute(
                    "UPDATE messages SET status='read' WHERE id=%s",
                    (mid,)
                )

                return True, "read"
    finally:
        conn.close()


def delete_message_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT id, name FROM messages ORDER BY id ASC OFFSET %s LIMIT 1",
                    (idx,)
                )
                r = cur.fetchone()

                if not r:
                    return False, None

                cur.execute(
                    "DELETE FROM messages WHERE id=%s",
                    (r["id"],)
                )

                return True, {"name": r["name"]}
    finally:
        conn.close()


def export_messages_csv():
    msgs = load_messages()

    if not msgs:
        return None

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["timestamp", "name", "email", "message", "status"])

    for m in msgs:
        writer.writerow([
            m.get("timestamp", ""),
            m.get("name", ""),
            m.get("email", ""),
            m.get("message", ""),
            m.get("status", "")
        ])

    return buf.getvalue().encode("utf-8")


def get_messages_counts_last_n_days(days=30):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date(timestamp) as d, count(*)
                    FROM messages
                    WHERE timestamp >= now() - interval %s
                    GROUP BY d
                    ORDER BY d
                    """,
                    (f"{days} days",)
                )

                rows = cur.fetchall()
                counts = {r[0].isoformat(): r[1] for r in rows}

                labels, values = [], []
                today = datetime.now().date()

                for i in range(days - 1, -1, -1):
                    d = (today - timedelta(days=i)).isoformat()
                    labels.append(d)
                    values.append(counts.get(d, 0))

                return labels, values
    finally:
        conn.close()


# ---------------- Subscribers ----------------
def save_subscriber(email: str):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO subscribers (email, timestamp)
                    VALUES (%s, now())
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (email.strip().lower(),)
                )
    finally:
        conn.close()


def load_subscribers():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, email, timestamp
                    FROM subscribers
                    ORDER BY id DESC
                """)

                return [
                    {
                        "email": r["email"],
                        "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else ""
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


# ---------------- Blogs ----------------
def slugify(text: str) -> str:
    import re

    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)

    return s[:200]




def ensure_blog_seo_columns():
    """Keep deployed databases compatible with new blog SEO fields. Safe to run repeatedly."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE blogs ADD COLUMN IF NOT EXISTS excerpt TEXT;")
                cur.execute("ALTER TABLE blogs ADD COLUMN IF NOT EXISTS featured_image TEXT;")
                cur.execute("ALTER TABLE blogs ADD COLUMN IF NOT EXISTS meta_keywords TEXT;")
    finally:
        conn.close()

def add_blog(title, content, status="published", published_at=None, category="Technology", is_trending=False, excerpt=None, featured_image=None, meta_keywords=None):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(id) FROM blogs")
                r = cur.fetchone()
                nid = (r[0] or 0) + 1

                slug = slugify(title) or f"post-{nid}"
                pub_time = published_at if published_at else datetime.now(timezone.utc)

                cur.execute(
                    """
                    INSERT INTO blogs (timestamp, title, slug, content, status, published_at, category, is_trending, excerpt, featured_image, meta_keywords)
                    VALUES (now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        title.strip(),
                        slug,
                        content.strip(),
                        status,
                        pub_time,
                        (category or "Technology").strip(),
                        bool(is_trending),
                        (excerpt or "").strip(),
                        (featured_image or "").strip(),
                        (meta_keywords or "").strip()
                    )
                )

                return {
                    "id": nid,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "title": title,
                    "slug": slug,
                    "content": content,
                    "category": category or "Technology",
                    "is_trending": bool(is_trending),
                    "excerpt": excerpt or "",
                    "featured_image": featured_image or "",
                    "meta_keywords": meta_keywords or "",
                    "status": status,
                    "published_at": pub_time.isoformat() if hasattr(pub_time, "isoformat") else str(pub_time),
                    "helpful_count": 0,
                    "useful_count": 0,
                    "learned_count": 0,
                    "loved_count": 0
                }
    finally:
        conn.close()

def load_blogs(include_drafts=False):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if include_drafts:
                    cur.execute("""
                        SELECT id, timestamp, title, slug, content,
                               COALESCE(views, 0) as views,
                               COALESCE(helpful_count, 0) as helpful_count,
                               COALESCE(useful_count, 0) as useful_count,
                               COALESCE(learned_count, 0) as learned_count,
                               COALESCE(loved_count, 0) as loved_count,
                               COALESCE(status, 'published') as status,
                               published_at,
                               COALESCE(category, 'Technology') as category,
                               COALESCE(is_trending, FALSE) as is_trending,
                               COALESCE(excerpt, '') as excerpt,
                               COALESCE(featured_image, '') as featured_image,
                               COALESCE(meta_keywords, '') as meta_keywords
                        FROM blogs
                        ORDER BY id DESC
                    """)
                else:
                    cur.execute("""
                        SELECT id, timestamp, title, slug, content,
                               COALESCE(views, 0) as views,
                               COALESCE(helpful_count, 0) as helpful_count,
                               COALESCE(useful_count, 0) as useful_count,
                               COALESCE(learned_count, 0) as learned_count,
                               COALESCE(loved_count, 0) as loved_count,
                               COALESCE(status, 'published') as status,
                               published_at,
                               COALESCE(category, 'Technology') as category,
                               COALESCE(is_trending, FALSE) as is_trending,
                               COALESCE(excerpt, '') as excerpt,
                               COALESCE(featured_image, '') as featured_image,
                               COALESCE(meta_keywords, '') as meta_keywords
                        FROM blogs
                        WHERE COALESCE(status, 'published') = 'published'
                        AND (published_at IS NULL OR published_at <= now())
                        ORDER BY id DESC
                    """)

                return [
                    {
                        "id": r["id"],
                        "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else "",
                        "title": r["title"] or "",
                        "slug": r["slug"] or "",
                        "content": r["content"] or "",
                        "views": r["views"] or 0,
                        "helpful_count": r["helpful_count"] or 0,
                        "useful_count": r["useful_count"] or 0,
                        "learned_count": r["learned_count"] or 0,
                        "loved_count": r["loved_count"] or 0,
                        "status": r["status"] or "published",
                        "published_at": r["published_at"].isoformat() if r["published_at"] else "",
                        "category": r["category"] or "Technology",
                        "is_trending": bool(r["is_trending"]),
                        "excerpt": r["excerpt"] or "",
                        "featured_image": r["featured_image"] or "",
                        "meta_keywords": r["meta_keywords"] or ""
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


def get_blog_by_slug(slug):
    try:
        ensure_blog_seo_columns()
    except Exception:
        pass
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, timestamp, title, slug, content,
                           COALESCE(views, 0) as views,
                           COALESCE(helpful_count, 0) as helpful_count,
                           COALESCE(useful_count, 0) as useful_count,
                           COALESCE(learned_count, 0) as learned_count,
                           COALESCE(loved_count, 0) as loved_count,
                           COALESCE(status, 'published') as status,
                           published_at,
                           COALESCE(category, 'Technology') as category,
                           COALESCE(is_trending, FALSE) as is_trending,
                           COALESCE(excerpt, '') as excerpt,
                           COALESCE(featured_image, '') as featured_image,
                           COALESCE(meta_keywords, '') as meta_keywords
                    FROM blogs
                    WHERE slug=%s
                    LIMIT 1
                """, (slug,))

                r = cur.fetchone()

                if not r:
                    return None

                return {
                    "id": r["id"],
                    "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else "",
                    "title": r["title"] or "",
                    "slug": r["slug"] or "",
                    "content": r["content"] or "",
                    "views": r["views"] or 0,
                    "helpful_count": r["helpful_count"] or 0,
                    "useful_count": r["useful_count"] or 0,
                    "learned_count": r["learned_count"] or 0,
                    "loved_count": r["loved_count"] or 0,
                    "status": r["status"] or "published",
                    "published_at": r["published_at"].isoformat() if r["published_at"] else "",
                    "category": r["category"] or "Technology",
                    "is_trending": bool(r["is_trending"]),
                    "excerpt": r["excerpt"] or "",
                    "featured_image": r["featured_image"] or "",
                    "meta_keywords": r["meta_keywords"] or ""
                }
    finally:
        conn.close()


def increment_blog_reaction(slug, reaction_type):
    if reaction_type not in ["helpful", "useful", "learned", "loved"]:
        return False

    column_name = f"{reaction_type}_count"
    conn = get_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE blogs
                    SET {column_name} = COALESCE({column_name}, 0) + 1
                    WHERE slug = %s
                    """,
                    (slug,)
                )
                return True

    except Exception as e:
        print(f"Error incrementing blog reaction {reaction_type}: {e}")
        return False

    finally:
        conn.close()


def increment_blog_views(slug):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE blogs
                    SET views = COALESCE(views, 0) + 1
                    WHERE slug = %s
                    """,
                    (slug,)
                )

    except Exception as e:
        print(f"Error incrementing blog views: {e}")

    finally:
        conn.close()


def delete_blog_by_id(bid):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blogs WHERE id = %s",
                    (bid,)
                )
    finally:
        conn.close()


def update_blog(bid, title, content, category="Technology", is_trending=False, excerpt=None, featured_image=None, meta_keywords=None):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                slug = slugify(title) or f"post-{bid}"

                cur.execute(
                    """
                    UPDATE blogs
                    SET title = %s, slug = %s, content = %s,
                        category = %s, is_trending = %s, excerpt = %s, featured_image = %s, meta_keywords = %s
                    WHERE id = %s
                    """,
                    (
                        title.strip(),
                        slug,
                        content.strip(),
                        (category or "Technology").strip(),
                        bool(is_trending),
                        (excerpt or "").strip() if excerpt is not None else "",
                        (featured_image or "").strip() if featured_image is not None else "",
                        (meta_keywords or "").strip() if meta_keywords is not None else "",
                        bid
                    )
                )

                return True
    finally:
        conn.close()


# ---------------- Files / Cloudinary Hybrid Storage ----------------
def _guess_mimetype(filename, file_storage=None):
    if file_storage and getattr(file_storage, "mimetype", None):
        return file_storage.mimetype

    mt = mimetypes.guess_type(filename)[0]

    return mt or "application/octet-stream"


def _cloudinary_folder(category):
    safe_category = secure_filename(category or "uploads") or "uploads"
    return f"techknow/{safe_category}"


def upload_bytes_to_cloudinary(content, filename, category):
    if not CLOUDINARY_ENABLED:
        return None

    try:
        file_obj = io.BytesIO(content)
        file_obj.name = filename

        result = cloudinary.uploader.upload(
            file_obj,
            folder=_cloudinary_folder(category),
            public_id=os.path.splitext(filename)[0],
            overwrite=False,
            resource_type="auto"
        )

        return {
            "url": result.get("secure_url"),
            "public_id": result.get("public_id"),
            "resource_type": result.get("resource_type")
        }

    except Exception as e:
        print(f"⚠️ Cloudinary upload failed, falling back to DB storage: {e}")
        return None


def delete_from_cloudinary(public_id):
    if not CLOUDINARY_ENABLED or not public_id:
        return False

    try:
        cloudinary.uploader.destroy(public_id, resource_type="image")
        cloudinary.uploader.destroy(public_id, resource_type="video")
        cloudinary.uploader.destroy(public_id, resource_type="raw")
        return True

    except Exception as e:
        print(f"⚠️ Could not delete Cloudinary file {public_id}: {e}")
        return False



def _is_convertible_image(filename, mimetype=""):
    """Return True for uploaded images we can safely optimize to WebP."""
    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
    # Keep GIF animation untouched. Videos/documents are untouched.
    return ext in {"png", "jpg", "jpeg", "webp"} or (mimetype or "").lower() in {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _optimized_webp_bytes(content, filename):
    """Convert PNG/JPG/WebP uploads to a compressed WebP image for faster pages.
    Keeps transparency when present, strips heavy metadata, limits huge dimensions,
    and returns (new_content, new_filename, new_mimetype). If Pillow is unavailable
    or conversion fails, the original file is returned unchanged.
    """
    if not Image or not content or not _is_convertible_image(filename):
        return content, filename, None

    try:
        max_width = int(os.getenv("WEBP_MAX_WIDTH", "1536"))
        quality = int(os.getenv("WEBP_QUALITY", "78"))

        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img)

        if getattr(img, "is_animated", False):
            return content, filename, None

        if img.width > max_width:
            new_height = max(1, int(img.height * (max_width / float(img.width))))
            img = img.resize((max_width, new_height), Image.LANCZOS)

        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")

        base = os.path.splitext(filename)[0] or "image"
        new_filename = secure_filename(base + ".webp")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=quality, method=6, optimize=True)
        optimized = out.getvalue()

        # Avoid replacing a tiny already-optimized image with a larger file.
        if optimized and len(optimized) < len(content) * 0.98:
            return optimized, new_filename, "image/webp"
        if filename.lower().endswith(".webp"):
            return optimized or content, new_filename, "image/webp"
        return optimized or content, new_filename, "image/webp"
    except Exception as e:
        print(f"⚠️ WebP optimization skipped for {filename}: {e}")
        return content, filename, None

def save_file_from_storage(category, file_storage, rename_to=None, approve=True, single_replace=False):
    if not file_storage or file_storage.filename == "":
        return None, "No file provided."

    original = secure_filename(file_storage.filename)
    fname = secure_filename(rename_to) if rename_to else (
        datetime.now().strftime("%Y%m%d_%H%M%S_") + original
    )

    try:
        content = file_storage.read()
        mimetype = _guess_mimetype(fname, file_storage)

        if not content:
            return None, "Uploaded file is empty."

        # Performance upgrade: automatically convert uploaded PNG/JPG/WebP images
        # to compressed WebP before saving or sending to Cloudinary. This keeps
        # article thumbnails, profile images, hero images and gallery photos light.
        optimized_mimetype = None
        if category in {"profile", "hero", "gallery", "blog_media"}:
            content, fname, optimized_mimetype = _optimized_webp_bytes(content, fname)
            if optimized_mimetype:
                mimetype = optimized_mimetype

        file_size = len(content or b"")

        cloud = upload_bytes_to_cloudinary(content, fname, category)

        url = None
        cloudinary_id = None
        storage_provider = "database"

        if cloud and cloud.get("url"):
            url = cloud.get("url")
            cloudinary_id = cloud.get("public_id")
            storage_provider = "cloudinary"

        conn = get_conn()

        try:
            with conn:
                with conn.cursor() as cur:
                    if single_replace:
                        cur.execute(
                            """
                            SELECT cloudinary_id
                            FROM files
                            WHERE category = %s
                            AND cloudinary_id IS NOT NULL
                            """,
                            (category,)
                        )

                        old_cloudinary_ids = [r[0] for r in cur.fetchall()]

                        cur.execute(
                            "DELETE FROM files WHERE category = %s",
                            (category,)
                        )

                        for old_id in old_cloudinary_ids:
                            delete_from_cloudinary(old_id)

                    cur.execute(
                        """
                        INSERT INTO files
                        (name, category, content, mimetype, uploaded_at, approved, url, cloudinary_id, storage_provider, file_size)
                        VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            fname,
                            category,
                            None if url else psycopg2.Binary(content),
                            mimetype,
                            approve,
                            url,
                            cloudinary_id,
                            storage_provider,
                            file_size
                        )
                    )

            return fname, None

        finally:
            conn.close()

    except Exception as e:
        return None, str(e)


def get_file_record(category, name, approved=None):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if approved is None:
                    cur.execute(
                        """
                        SELECT id, name, category, content, mimetype, uploaded_at, approved,
                               url, cloudinary_id, storage_provider, file_size
                        FROM files
                        WHERE category=%s AND name=%s
                        ORDER BY uploaded_at DESC
                        LIMIT 1
                        """,
                        (category, name)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, name, category, content, mimetype, uploaded_at, approved,
                               url, cloudinary_id, storage_provider, file_size
                        FROM files
                        WHERE category=%s AND name=%s AND approved=%s
                        ORDER BY uploaded_at DESC
                        LIMIT 1
                        """,
                        (category, name, approved)
                    )

                r = cur.fetchone()

                if not r:
                    return None

                return {
                    "id": r["id"],
                    "name": r["name"],
                    "category": r["category"],
                    "content": bytes(r["content"]) if r["content"] else b"",
                    "mimetype": r["mimetype"],
                    "uploaded_at": r["uploaded_at"],
                    "approved": r["approved"],
                    "url": r["url"],
                    "cloudinary_id": r["cloudinary_id"],
                    "storage_provider": r["storage_provider"] or "database",
                    "file_size": r["file_size"] or 0
                }

    finally:
        conn.close()


def get_latest_file_record(category, only_images=False):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if only_images:
                    cur.execute(
                        """
                        SELECT id, name, category, content, mimetype, uploaded_at, approved,
                               url, cloudinary_id, storage_provider, file_size
                        FROM files
                        WHERE category=%s AND mimetype LIKE 'image/%%'
                        ORDER BY uploaded_at DESC
                        LIMIT 1
                        """,
                        (category,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, name, category, content, mimetype, uploaded_at, approved,
                               url, cloudinary_id, storage_provider, file_size
                        FROM files
                        WHERE category=%s
                        ORDER BY uploaded_at DESC
                        LIMIT 1
                        """,
                        (category,)
                    )

                r = cur.fetchone()

                if not r:
                    return None

                return {
                    "id": r["id"],
                    "name": r["name"],
                    "category": r["category"],
                    "content": bytes(r["content"]) if r["content"] else b"",
                    "mimetype": r["mimetype"],
                    "uploaded_at": r["uploaded_at"],
                    "approved": r["approved"],
                    "url": r["url"],
                    "cloudinary_id": r["cloudinary_id"],
                    "storage_provider": r["storage_provider"] or "database",
                    "file_size": r["file_size"] or 0
                }

    finally:
        conn.close()


def get_latest_filename(category):
    rec = get_latest_file_record(category)

    return rec["name"] if rec else None


def get_file_timestamp(category, filename):
    rec = get_file_record(category, filename)

    if not rec:
        return None

    dt = rec.get("uploaded_at")

    return dt.timestamp() if dt else None


def list_gallery_media():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT name, mimetype, uploaded_at, url, storage_provider,
                           COALESCE(media_title, '') AS media_title,
                           COALESCE(media_caption, '') AS media_caption,
                           COALESCE(media_narration, '') AS media_narration
                    FROM files
                    WHERE category='gallery' AND approved = TRUE
                    ORDER BY uploaded_at DESC
                """)
                rows = cur.fetchall()
                out = []
                for r in rows:
                    mimetype = r["mimetype"] or ""
                    typ = "image" if mimetype.startswith("image") else "video" if mimetype.startswith("video") else "other"
                    base = os.path.splitext(r["name"] or "Operations Media")[0].replace("_", " ").replace("-", " ").strip().title()
                    caption = (r["media_caption"] or "").strip() or "A SurgeTechKnow operations moment from ICT support, networking, cybersecurity, or systems deployment."
                    out.append({
                        "name": r["name"],
                        "type": typ,
                        "url": r["url"] or f"/media/gallery/{r['name']}",
                        "title": (r["media_title"] or "").strip() or base,
                        "caption": caption,
                        "summary": caption,
                        "narration": (r["media_narration"] or "").strip() or caption,
                        "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else "",
                        "storage_provider": r["storage_provider"] or "database"
                    })
                return out
    finally:
        conn.close()

def list_projects(approved=True):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT name
                    FROM files
                    WHERE category='project'
                    AND approved=%s
                    ORDER BY uploaded_at DESC
                    """,
                    (approved,)
                )

                return [r[0] for r in cur.fetchall()]

    finally:
        conn.close()


def approve_project_by_name(name):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE files
                    SET approved = TRUE
                    WHERE category='project'
                    AND name=%s
                    AND approved=FALSE
                    RETURNING id
                    """,
                    (name,)
                )

                return bool(cur.fetchone())

    finally:
        conn.close()


def reject_project_by_name(name):
    rec = get_file_record("project", name, approved=False)

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM files
                    WHERE category='project'
                    AND name=%s
                    AND approved=FALSE
                    RETURNING id
                    """,
                    (name,)
                )

                deleted = bool(cur.fetchone())

                if deleted and rec and rec.get("cloudinary_id"):
                    delete_from_cloudinary(rec["cloudinary_id"])

                return deleted

    finally:
        conn.close()


def delete_project_by_name(name):
    rec = get_file_record("project", name)

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM files
                    WHERE category='project'
                    AND name=%s
                    RETURNING id
                    """,
                    (name,)
                )

                deleted = bool(cur.fetchone())

                if deleted and rec and rec.get("cloudinary_id"):
                    delete_from_cloudinary(rec["cloudinary_id"])

                return deleted

    finally:
        conn.close()


def delete_file(category, name):
    rec = get_file_record(category, name)

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM files
                    WHERE category=%s
                    AND name=%s
                    RETURNING id
                    """,
                    (category, name)
                )

                deleted = bool(cur.fetchone())

                if deleted and rec and rec.get("cloudinary_id"):
                    delete_from_cloudinary(rec["cloudinary_id"])

                return deleted

    finally:
        conn.close()


def sync_missing_files_to_cloudinary(limit=20):
    """
    Sync old database-stored files to Cloudinary.

    Important:
    After successful Cloudinary upload, this function sets content=NULL.
    That means Supabase/PostgreSQL stops storing the heavy BYTEA file.
    """
    if not CLOUDINARY_ENABLED:
        print("⚠️ Cloudinary is not configured. Sync skipped.")
        return 0

    conn = get_conn()
    synced = 0

    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, name, category, content
                    FROM files
                    WHERE url IS NULL
                    AND content IS NOT NULL
                    ORDER BY uploaded_at ASC
                    LIMIT %s
                    """,
                    (limit,)
                )

                rows = cur.fetchall()

                for r in rows:
                    content = bytes(r["content"]) if r["content"] else b""

                    if not content:
                        continue

                    cloud = upload_bytes_to_cloudinary(
                        content,
                        r["name"],
                        r["category"]
                    )

                    if cloud and cloud.get("url"):
                        cur.execute(
                            """
                            UPDATE files
                            SET url=%s,
                                cloudinary_id=%s,
                                storage_provider='cloudinary',
                                content=NULL
                            WHERE id=%s
                            """,
                            (
                                cloud["url"],
                                cloud["public_id"],
                                r["id"]
                            )
                        )

                        synced += 1

        print(f"✅ Synced {synced} file(s) to Cloudinary and cleared BYTEA content.")
        return synced

    except Exception as e:
        print(f"⚠️ Error syncing missing files to Cloudinary: {e}")
        return synced

    finally:
        conn.close()


# ---------------- Site Visit Tracking ----------------
def record_visit(ip_address: str, user_agent: str, path: str, session_id: str = None, js_enabled: bool = False, screen_resolution: str = None, mouse_moved: bool = False, is_admin: bool = False, timezone: str = None, browser: str = None, device_type: str = None, engaged: bool = False):
    """Record visits without bot blocking or suspicious filtering.

    Owner requested that all public traffic be allowed/counted because aggressive
    bot filters caused admin views and external analytics to drop. Admin/local
    visits are still separated as admin so the public dashboard is not polluted.
    """
    is_local = ip_address in ["127.0.0.1", "::1", "localhost", "0.0.0.0"]
    if is_local or is_admin or (path and path.startswith("/admin")):
        visit_type = "admin"
    else:
        visit_type = "real" if js_enabled else "pageview"

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO site_visits (ip_address, user_agent, path, timestamp, session_id, visit_type, js_enabled, screen_resolution, mouse_moved, browser, timezone, device_type, engaged)
                    VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        ip_address or "Unknown",
                        user_agent or "Unknown",
                        path or "/",
                        session_id,
                        visit_type,
                        js_enabled,
                        screen_resolution,
                        mouse_moved,
                        browser,
                        timezone,
                        device_type,
                        True if not is_admin else engaged
                    )
                )
    except Exception as e:
        print(f"Error recording visit in DB: {e}")
    finally:
        conn.close()

def get_visits_by_type():
    conn = get_conn()
    stats = {"total": 0, "real": 0, "bot": 0, "suspicious": 0, "pageview": 0, "admin": 0}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT visit_type, COUNT(*) FROM site_visits GROUP BY visit_type")
                rows = cur.fetchall()
                for v_type, count in rows:
                    if v_type in stats:
                        stats[v_type] = count
                
                # Verified human pageviews + sessions
                cur.execute("SELECT COUNT(*) FROM site_visits WHERE visit_type IN ('real', 'pageview')")
                stats["total"] = cur.fetchone()[0]

                # Active Engaged Users count
                cur.execute("SELECT COUNT(*) FROM site_visits WHERE engaged = TRUE")
                stats["engaged"] = cur.fetchone()[0]
    except Exception as e:
        print("Error getting visits by type:", e)
    finally:
        conn.close()
    return stats


def get_daily_visits_summary():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT TO_CHAR(timestamp, 'YYYY-MM-DD') as visit_date,
                           COUNT(*) as visit_count
                    FROM site_visits
                    WHERE timestamp >= now() - INTERVAL '15 days'
                    GROUP BY visit_date
                    ORDER BY visit_date ASC
                """)

                rows = cur.fetchall()

                return [{"date": r[0], "count": r[1]} for r in rows]

    except Exception as e:
        print(f"Error loading daily visits: {e}")
        return []

    finally:
        conn.close()


def get_total_visits_count():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM site_visits")
                row = cur.fetchone()

                return row[0] if row else 0

    except Exception as e:
        print(f"Error loading total visits: {e}")
        return 0

    finally:
        conn.close()


# ---------------- TechRich Document Repository ----------------
def save_techrich_doc(title, doc_type, file_name=None, file_data=None, mimetype=None, content=None):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO techrich_docs
                    (title, doc_type, file_name, file_data, mimetype, content, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    RETURNING id
                    """,
                    (
                        title.strip(),
                        doc_type,
                        file_name,
                        file_data if file_data else None,
                        mimetype,
                        content
                    )
                )

                r = cur.fetchone()

                return r[0] if r else None

    except Exception as e:
        print(f"Error saving techrich doc in DB: {e}")
        return None

    finally:
        conn.close()


def load_techrich_docs():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, title, doc_type, file_name, mimetype,
                           length(file_data) as file_size,
                           content, created_at, updated_at
                    FROM techrich_docs
                    ORDER BY updated_at DESC
                """)

                rows = cur.fetchall()
                out = []

                for r in rows:
                    out.append({
                        "id": r["id"],
                        "title": r["title"] or "Untitled Document",
                        "doc_type": r["doc_type"] or "note",
                        "file_name": r["file_name"] or "",
                        "mimetype": r["mimetype"] or "text/plain",
                        "file_size": r["file_size"] or 0,
                        "content": r["content"] or "",
                        "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else ""
                    })

                return out

    except Exception as e:
        print(f"Error loading techrich docs: {e}")
        return []

    finally:
        conn.close()


def get_techrich_doc_by_id(doc_id):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, title, doc_type, file_name, file_data,
                           mimetype, content, created_at, updated_at
                    FROM techrich_docs
                    WHERE id = %s
                """, (doc_id,))

                r = cur.fetchone()

                if not r:
                    return None

                return {
                    "id": r["id"],
                    "title": r["title"] or "Untitled",
                    "doc_type": r["doc_type"] or "note",
                    "file_name": r["file_name"] or "",
                    "file_data": bytes(r["file_data"]) if r["file_data"] else None,
                    "mimetype": r["mimetype"] or "",
                    "content": r["content"] or "",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else ""
                }

    except Exception as e:
        print(f"Error fetching techrich doc by id: {e}")
        return None

    finally:
        conn.close()


def update_techrich_doc(doc_id, title, content):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE techrich_docs
                    SET title = %s,
                        content = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        title.strip(),
                        content,
                        doc_id
                    )
                )

                return True

    except Exception as e:
        print(f"Error updating techrich doc: {e}")
        return False

    finally:
        conn.close()


def delete_techrich_doc_by_id(doc_id):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM techrich_docs WHERE id = %s",
                    (doc_id,)
                )

                return True

    except Exception as e:
        print(f"Error deleting techrich doc: {e}")
        return False

    finally:
        conn.close()


# ---------------- Auto-create Tables ----------------
try:
    create_tables()
except Exception as e:
    print("⚠️ Could not auto-create tables:", e)
