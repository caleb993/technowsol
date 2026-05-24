import os
import io
import csv
import mimetypes
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras

# Load environment variables
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME")

# ✅ Supabase DB connection
def get_conn():
    return psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        sslmode="require"  # Supabase requires SSL
    )

# ----------------- Table creation -----------------
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
        CREATE TABLE IF NOT EXISTS site_visits (
          id SERIAL PRIMARY KEY,
          timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
          ip_address TEXT,
          user_agent TEXT,
          path TEXT
        )
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
        print("✅ Tables created or already exist.")
        
        # Seed TechRich Documents if empty
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
                    "INSERT INTO messages (timestamp, name, email, message, status) VALUES (now(), %s, %s, %s, %s)",
                    (name.strip(), email.strip(), message.strip(), "unread")
                )
    finally:
        conn.close()

def load_messages():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT id, timestamp, name, email, message, status FROM messages ORDER BY id ASC")
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
                        "INSERT INTO messages (timestamp, name, email, message, status) VALUES (%s, %s, %s, %s, %s)",
                        (t, m.get("name",""), m.get("email",""), m.get("message",""), m.get("status","unread"))
                    )
    finally:
        conn.close()

def get_message_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT id, timestamp, name, email, message, status FROM messages ORDER BY id ASC OFFSET %s LIMIT 1",
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
                cur.execute("SELECT id, status FROM messages ORDER BY id ASC OFFSET %s LIMIT 1", (idx,))
                r = cur.fetchone()
                if not r:
                    return False, None
                mid, status = r
                new = "read" if status == "unread" else "unread"
                cur.execute("UPDATE messages SET status=%s WHERE id=%s", (new, mid))
                return True, new
    finally:
        conn.close()

def mark_message_read_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, status FROM messages ORDER BY id ASC OFFSET %s LIMIT 1", (idx,))
                r = cur.fetchone()
                if not r:
                    return False, None
                mid, status = r
                cur.execute("UPDATE messages SET status='read' WHERE id=%s", (mid,))
                return True, "read"
    finally:
        conn.close()

def delete_message_by_index(idx):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT id, name FROM messages ORDER BY id ASC OFFSET %s LIMIT 1", (idx,))
                r = cur.fetchone()
                if not r:
                    return False, None
                cur.execute("DELETE FROM messages WHERE id=%s", (r["id"],))
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
        writer.writerow([m.get("timestamp",""), m.get("name",""), m.get("email",""), m.get("message",""), m.get("status","")])
    return buf.getvalue().encode("utf-8")

def get_messages_counts_last_n_days(days=30):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date(timestamp) as d, count(*) FROM messages WHERE timestamp >= now() - interval %s GROUP BY d ORDER BY d",
                    (f'{days} days',)
                )
                rows = cur.fetchall()
                counts = {r[0].isoformat(): r[1] for r in rows}
                labels, values = [], []
                today = datetime.now().date()
                for i in range(days-1, -1, -1):
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
                    "INSERT INTO subscribers (email, timestamp) VALUES (%s, now()) ON CONFLICT (email) DO NOTHING",
                    (email.strip().lower(),)
                )
    finally:
        conn.close()

def load_subscribers():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT id, email, timestamp FROM subscribers ORDER BY id DESC")
                return [
                    {"email": r["email"], "timestamp": r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else ""}
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

def add_blog(title, content):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(id) FROM blogs")
                r = cur.fetchone()
                nid = (r[0] or 0) + 1
                slug = slugify(title) or f"post-{nid}"
                cur.execute(
                    "INSERT INTO blogs (timestamp, title, slug, content) VALUES (now(), %s, %s, %s)",
                    (title.strip(), slug, content.strip())
                )
                return {"id": nid, "timestamp": datetime.now().isoformat(timespec="seconds"), "title": title, "slug": slug, "content": content}
    finally:
        conn.close()

def load_blogs():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT id, timestamp, title, slug, content, COALESCE(views, 0) as views FROM blogs ORDER BY id DESC")
                return [
                    {
                        "id": r["id"],
                        "timestamp": (r["timestamp"].isoformat(timespec="seconds") if r["timestamp"] else "") if "timestamp" in r and r["timestamp"] else "",
                        "title": r["title"] or "",
                        "slug": r["slug"] or "",
                        "content": r["content"] or "",
                        "views": r["views"] or 0
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()

def get_blog_by_slug(slug):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT id, timestamp, title, slug, content, COALESCE(views, 0) as views FROM blogs WHERE slug=%s LIMIT 1", (slug,))
                r = cur.fetchone()
                if not r:
                    return None
                timestamp_str = ""
                if r["timestamp"]:
                    try:
                        timestamp_str = r["timestamp"].isoformat(timespec="seconds")
                    except Exception:
                        timestamp_str = str(r["timestamp"])
                return {
                    "id": r["id"], 
                    "timestamp": timestamp_str, 
                    "title": r["title"] or "", 
                    "slug": r["slug"] or "", 
                    "content": r["content"] or "",
                    "views": r["views"] or 0
                }
    finally:
        conn.close()

def increment_blog_views(slug):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE blogs SET views = COALESCE(views, 0) + 1 WHERE slug = %s", (slug,))
    except Exception as e:
        print(f"Error incrementing blog views: {e}")
    finally:
        conn.close()

def delete_blog_by_id(bid):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM blogs WHERE id = %s", (bid,))
    finally:
        conn.close()

def update_blog(bid, title, content):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                slug = slugify(title) or f"post-{bid}"
                cur.execute(
                    "UPDATE blogs SET title = %s, slug = %s, content = %s WHERE id = %s",
                    (title.strip(), slug, content.strip(), bid)
                )
                return True
    finally:
        conn.close()

# ---------------- Files ----------------
def _guess_mimetype(filename, file_storage=None):
    if file_storage and getattr(file_storage, "mimetype", None):
        return file_storage.mimetype
    mt = mimetypes.guess_type(filename)[0]
    return mt or "application/octet-stream"

def save_file_from_storage(category, file_storage, rename_to=None, approve=True, single_replace=False):
    if not file_storage or file_storage.filename == "":
        return None, "No file provided."
    original = secure_filename(file_storage.filename)
    fname = secure_filename(rename_to) if rename_to else (datetime.now().strftime("%Y%m%d_%H%M%S_") + original)
    try:
        content = file_storage.read()
        mimetype = _guess_mimetype(fname, file_storage)
        conn = get_conn()
        with conn:
            with conn.cursor() as cur:
                if single_replace:
                    cur.execute("DELETE FROM files WHERE category = %s", (category,))
                cur.execute(
                    "INSERT INTO files (name, category, content, mimetype, uploaded_at, approved) VALUES (%s, %s, %s, %s, now(), %s) RETURNING id",
                    (fname, category, psycopg2.Binary(content), mimetype, approve)
                )
        return fname, None
    except Exception as e:
        return None, str(e)

def get_file_record(category, name, approved=None):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if approved is None:
                    cur.execute(
                        "SELECT id, name, content, mimetype, uploaded_at, approved FROM files WHERE category=%s AND name=%s ORDER BY uploaded_at DESC LIMIT 1",
                        (category, name)
                    )
                else:
                    cur.execute(
                        "SELECT id, name, content, mimetype, uploaded_at, approved FROM files WHERE category=%s AND name=%s AND approved=%s ORDER BY uploaded_at DESC LIMIT 1",
                        (category, name, approved)
                    )
                r = cur.fetchone()
                if not r:
                    return None
                return {"id": r["id"], "name": r["name"], "content": bytes(r["content"]) if r["content"] else b"", "mimetype": r["mimetype"], "uploaded_at": r["uploaded_at"], "approved": r["approved"]}
    finally:
        conn.close()

def get_latest_file_record(category, only_images=False):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if only_images:
                    cur.execute(
                        "SELECT id, name, content, mimetype, uploaded_at FROM files WHERE category=%s AND mimetype LIKE 'image/%%' ORDER BY uploaded_at DESC LIMIT 1",
                        (category,)
                    )
                else:
                    cur.execute(
                        "SELECT id, name, content, mimetype, uploaded_at FROM files WHERE category=%s ORDER BY uploaded_at DESC LIMIT 1",
                        (category,)
                    )
                r = cur.fetchone()
                if not r:
                    return None
                return {"id": r["id"], "name": r["name"], "content": bytes(r["content"]) if r["content"] else b"", "mimetype": r["mimetype"], "uploaded_at": r["uploaded_at"]}
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
                cur.execute("SELECT name, mimetype, uploaded_at FROM files WHERE category='gallery' ORDER BY uploaded_at DESC")
                rows = cur.fetchall()
                out = []
                for r in rows:
                    typ = "image" if (r["mimetype"] or "").startswith("image") else "video" if (r["mimetype"] or "").startswith("video") else "other"
                    out.append({"name": r["name"], "type": typ, "url": f"/media/gallery/{r['name']}"})
                return out
    finally:
        conn.close()

def list_projects(approved=True):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM files WHERE category='project' AND approved=%s ORDER BY uploaded_at DESC",
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
                    "UPDATE files SET approved = TRUE WHERE category='project' AND name=%s AND approved=FALSE RETURNING id",
                    (name,)
                )
                return bool(cur.fetchone())
    finally:
        conn.close()

def reject_project_by_name(name):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM files WHERE category='project' AND name=%s AND approved=FALSE RETURNING id",
                    (name,)
                )
                return bool(cur.fetchone())
    finally:
        conn.close()

def delete_project_by_name(name):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM files WHERE category='project' AND name=%s RETURNING id",
                    (name,)
                )
                return bool(cur.fetchone())
    finally:
        conn.close()

def delete_file(category, name):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM files WHERE category=%s AND name=%s RETURNING id",
                    (category, name)
                )
                return bool(cur.fetchone())
    finally:
        conn.close()

# ---------------- Site Visit Tracking ----------------
def record_visit(ip_address: str, user_agent: str, path: str):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO site_visits (ip_address, user_agent, path, timestamp) VALUES (%s, %s, %s, now())",
                    (ip_address or "Unknown", user_agent or "Unknown", path or "/")
                )
    except Exception as e:
        print(f"Error recording visit in DB: {e}")
    finally:
        conn.close()

def get_daily_visits_summary():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Get daily counts for last 15 days, aggregate by date (ignoring time)
                cur.execute("""
                    SELECT TO_CHAR(timestamp, 'YYYY-MM-DD') as visit_date, COUNT(*) as visit_count 
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
                    INSERT INTO techrich_docs (title, doc_type, file_name, file_data, mimetype, content, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now()) RETURNING id
                    """,
                    (title.strip(), doc_type, file_name, file_data if file_data else None, mimetype, content)
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
                    SELECT id, title, doc_type, file_name, mimetype, length(file_data) as file_size, content, created_at, updated_at 
                    FROM techrich_docs ORDER BY updated_at DESC
                """)
                rows = cur.fetchall()
                out = []
                for r in rows:
                    created_str = r["created_at"].isoformat() if r["created_at"] else ""
                    updated_str = r["updated_at"].isoformat() if r["updated_at"] else ""
                    out.append({
                        "id": r["id"],
                        "title": r["title"] or "Untitled Document",
                        "doc_type": r["doc_type"] or "note",
                        "file_name": r["file_name"] or "",
                        "mimetype": r["mimetype"] or "text/plain",
                        "file_size": r["file_size"] or 0,
                        "content": r["content"] or "",
                        "created_at": created_str,
                        "updated_at": updated_str
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
                    SELECT id, title, doc_type, file_name, file_data, mimetype, content, created_at, updated_at 
                    FROM techrich_docs WHERE id = %s
                """, (doc_id,))
                r = cur.fetchone()
                if not r:
                    return None
                created_str = r["created_at"].isoformat() if r["created_at"] else ""
                updated_str = r["updated_at"].isoformat() if r["updated_at"] else ""
                return {
                    "id": r["id"],
                    "title": r["title"] or "Untitled",
                    "doc_type": r["doc_type"] or "note",
                    "file_name": r["file_name"] or "",
                    "file_data": bytes(r["file_data"]) if r["file_data"] else None,
                    "mimetype": r["mimetype"] or "",
                    "content": r["content"] or "",
                    "created_at": created_str,
                    "updated_at": updated_str
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
                    SET title = %s, content = %s, updated_at = now() 
                    WHERE id = %s
                    """,
                    (title.strip(), content, doc_id)
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
                cur.execute("DELETE FROM techrich_docs WHERE id = %s", (doc_id,))
                return True
    except Exception as e:
        print(f"Error deleting techrich doc: {e}")
        return False
    finally:
        conn.close()

# ---------------- Auto-create tables ----------------
try:
    create_tables()
except Exception as e:
    print("⚠️ Could not auto-create tables:", e)
