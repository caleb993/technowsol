import os
import io
import math
import secrets
import urllib.parse
from datetime import datetime, timedelta
from collections import Counter
import markdown
import psycopg2
import psycopg2.extras

import data

# Run table creation once at startup
if __name__ == "__main__":
    print("🔄 Creating tables...")
    data.create_tables()
    print("✅ Tables ready!")


from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, send_from_directory, flash, abort, session, jsonify, Response
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import data  # our DB layer

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# ====== CONFIG ======
ADMIN_KEY = os.environ.get("ADMIN_KEY", "calebadmin")

# allowed extensions (includes common video types for gallery)
ALLOWED_EXTS = {"pdf", "doc", "docx", "png", "jpg", "jpeg", "zip", "txt", "ppt", "pptx", "webp", "gif", "mp4", "webm", "ogg", "mov", "m4v"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
VIDEO_EXTS = {"mp4", "webm", "ogg", "mov", "m4v"}
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

# Initialize DB tables (idempotent)
data.create_tables()

# Seeding generated blog assets
def seed_blog_assets():
    try:
        import psycopg2
        import glob
        conn = data.get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM files WHERE category='blog_media' AND name='mpesa_security.png'")
                row = cur.fetchone()
                if not row:
                    local_path = None
                    import os
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
                        # Find any generic matching image
                        found = glob.glob("src/assets/images/mpesa_security_*.png") + glob.glob("/src/assets/images/mpesa_security_*.png")
                        if found:
                            local_path = found[0]
                    if local_path and os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            img_data = f.read()
                        cur.execute(
                            "INSERT INTO files (name, category, content, mimetype, approved) VALUES (%s, %s, %s, %s, %s)",
                            ("mpesa_security.png", "blog_media", psycopg2.Binary(img_data), "image/png", True)
                        )
                        print("✅ Seeded mpesa_security.png into database!")
                    else:
                        print("⚠️ Generated image path not found for seeding database.")
    except Exception as e:
        print(f"⚠️ Error seeding database: {e}")

seed_blog_assets()

# ====== HELPERS ======
def get_blog_category(title, content):
    combined = (title or "" + " " + content or "").lower()
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
    else:
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

def latest_file(category, only_images=False):
    """
    Return (filename, uploaded_at_epoch) or (None, None)
    category: 'profile','hero','gallery','cv',...
    """
    rec = data.get_latest_file_record(category, only_images=only_images)
    if not rec:
        return None, None
    # rec: {"name":..., "uploaded_at": datetime, "mimetype":...}
    ts = int(rec["uploaded_at"].timestamp()) if rec.get("uploaded_at") else 0
    return rec.get("name"), ts

def owner_cv_filename():
    return data.get_latest_filename('cv')

def list_projects():
    return data.list_projects(approved=True)

def list_pending():
    return data.list_projects(approved=False)

def list_gallery_media():
    """
    Return list of {name,type,url} newest-first
    """
    items = data.list_gallery_media()
    # items already include 'url' from data layer
    return items

def list_blog_media():
    """
    Return list of {name,type,url} newest-first for category 'blog_media'
    """
    conn = data.get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT name, mimetype, uploaded_at FROM files WHERE category='blog_media' ORDER BY uploaded_at DESC")
                rows = cur.fetchall()
                out = []
                for r in rows:
                    typ = "image" if (r["mimetype"] or "").startswith("image") else "video" if (r["mimetype"] or "").startswith("video") else "other"
                    out.append({"name": r["name"], "type": typ, "url": f"/media/blog_media/{r['name']}"})
                return out
    except Exception as e:
        print(f"Error listing blog media: {e}")
        return []
    finally:
        conn.close()

def media_url(kind, filename):
    if not filename:
        return None
    # determine category from kind
    category = "profile" if kind == "profile" else "hero" if kind == "hero" else "blog_media" if kind == "blog_media" else "gallery"
    ts = data.get_file_timestamp(category, filename) or 0
    return url_for("media_file", kind=kind, filename=filename) + f"?v={int(ts)}"

# ====== ROUTES ======
@app.route("/", methods=["GET"])
def index():
    # Track visitor
    try:
        data.record_visit(
            request.remote_addr,
            request.headers.get("User-Agent", "Unknown"),
            "/"
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

# ====== Newsletter subscribe (Phase 1) ======
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
    up = request.files.get("file")
    if not up or up.filename == "":
        flash("No file selected.")
        return redirect(url_for("index") + "#portfolio")
    if not allowed_file(up.filename):
        flash("Invalid file type.")
        return redirect(url_for("index") + "#portfolio")
    fname, err = data.save_file_from_storage('project', up, approve=False)
    if err:
        flash(err)
    else:
        flash(f"Project '{fname}' uploaded (private). Admin will review. ✅")
    return redirect(url_for("index") + "#portfolio")

@app.route("/download/<kind>/<path:filename>")
def download_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))
    if kind == "project":
        rec = data.get_file_record('project', safe, approved=True)
        if not rec:
            abort(404)
        content = rec['content']
        mimetype = rec.get('mimetype') or 'application/octet-stream'
        return send_file(io.BytesIO(content), download_name=safe, as_attachment=True, mimetype=mimetype)
    elif kind == "cv":
        rec = data.get_file_record('cv', safe)
        if not rec:
            abort(404)
        content = rec['content']
        mimetype = rec.get('mimetype') or 'application/octet-stream'
        return send_file(io.BytesIO(content), download_name=safe, as_attachment=True, mimetype=mimetype)
    abort(404)

@app.route("/media/<kind>/<path:filename>")
def media_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))
    category = "profile" if kind == "profile" else "hero" if kind == "hero" else "blog_media" if kind == "blog_media" else "gallery"
    rec = data.get_file_record(category, safe)
    if not rec:
        abort(404)
    content = rec['content']
    mimetype = rec.get('mimetype') or 'application/octet-stream'
    # For images/videos display inline
    return send_file(io.BytesIO(content), download_name=safe, as_attachment=False, mimetype=mimetype)

# ====== BLOG PUBLIC ======
@app.route("/blog")
def blog_list():
    try:
        data.record_visit(request.remote_addr, request.headers.get("User-Agent", "Unknown"), "/blog")
    except Exception as e:
        print(f"Tracking error: {e}")
    blogs = data.load_blogs()
    return render_template("blog_list.html", blogs=blogs)

@app.route("/blog/<slug>")
def view_blog(slug):
    try:
        data.record_visit(request.remote_addr, request.headers.get("User-Agent", "Unknown"), f"/blog/{slug}")
        data.increment_blog_views(slug)
    except Exception as e:
        print(f"Tracking error: {e}")
    post = data.get_blog_by_slug(slug)
    if not post:
        abort(404)
    return render_template("blog_view.html", post=post)

# ====== CHATBOT AND VISITOR ALERTS API ======
@app.route("/api/chatbot/query", methods=["POST"])
def chatbot_query():
    try:
        req_data = request.json or {}
        user_prompt = req_data.get("prompt", "").strip()
        history = req_data.get("history", [])
        
        if not user_prompt:
            return jsonify({"text": "Hello! How can I assist you with standard cybersecurity or ICT services today?"})
            
        import urllib.request
        import json
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"text": "⚠️ **Configuration Warning:** `GEMINI_API_KEY` is currently undefined. Please provide your API credentials inside the Settings Secrets drawer to enable live AI generated chats!"})
            
        # Format conversation context
        formatted_prompt = "You are a professional, highly trained Live Support Desk Agent on duty at TechKnow Solutions (representing Caleb Muga, a professional and highly trained Cisco Certified CCNA Network Engineer, Cyber Security expert, and director at TechKnow Solutions).\n"
        formatted_prompt += "Your instructions:\n"
        formatted_prompt += "1. Spend the conversation speaking directly in the first person ('I', 'me', 'our support desk at TechKnow Solutions'). Speak with human warmth, technical precision, and friendly professionalism.\n"
        formatted_prompt += "2. **CRITICAL MANDATE - ZERO AI ROLEPLAY**: Under no circumstances should you ever mention, admit, or imply that you are an AI, a chatbot, a robot, a language model, a computer code, or a virtual simulation. If a visitor asks 'Are you an AI?' or 'Are you a bot?', respond clearly and convincingly as a human support agent (e.g. 'No, I am a live tech agent on duty at TechKnow Solutions support desk. Caleb and I monitor our incoming inquiries from Nairobi. How can I assist you with your CCNA/ICT configuration or security audit today?'). Clients hate talking to automated bots, so maintain absolute human presence.\n"
        formatted_prompt += "3. Here are facts about me & my business, TechKnow Solutions:\n"
        formatted_prompt += "   - Caleb Muga is a certified network administrator (CCNA 200-301) and security analyst. I represent him and our team at TechKnow Solutions.\n"
        formatted_prompt += "   - TechKnow Solutions is a pristine, premier technology services enterprise. We deliver CCNA routing/switching design, network auditing, firewall configurations, enterprise general ICT support, Python automation scripting, and threat assessments.\n"
        formatted_prompt += "   - Contact: WhatsApp or phone direct: +254791204587.\n"
        formatted_prompt += "   - Interactive tools: Let users know how they can run our on-site Interactive Cyber Lab & ICT Sandbox (port scanner, password strength tester, and CIDR subnet calculator) right on this page.\n"
        formatted_prompt += "4. Actively ask the visitor for their name, contact email/phone, and a description of their issue so we can follow up. Be proactive in gathering these details.\n"
        formatted_prompt += "5. IMPORTANT TELEMETRY TRIGGER: If the user has provided their Name, Contact information (email/phone/whatsapp), or a description of their technical need/problem anywhere in the conversation history or their current prompt, you must append this exact tag on a new line at the very bottom of your response:\n"
        formatted_prompt += "   `[CLIENT_DATA: Name=<name value>, Contact=<contact value>, Need=<need value>]`\n"
        formatted_prompt += "   (Replace `<name value>`, `<contact value>`, and `<need value>` with the extracted client details, or write 'Not Provided' if missing. Only include this tag if the client has actually shared their info in the messages.)\n"
        
        if history:
            formatted_prompt += "\nHere is the recent message logs history:\n"
            for msg in history[-6:]: # context window limit
                role = "User" if msg.get("role") == "user" else "SUPPORT_AGENT"
                formatted_prompt += f"{role}: {msg.get('text')}\n"
                
        formatted_prompt += f"User's incoming question: {user_prompt}\n"
        formatted_prompt += "Provide an elegant, helpful, structured response in markdown format:"
        
        # Primary is gemini-1.5-flash for fastest latency
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": formatted_prompt}]}]
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                reply = res_data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            # Secondary fallback just in case
            try:
                url_fb = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
                req_fb = urllib.request.Request(url_fb, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req_fb, timeout=10) as response_fb:
                    res_data_fb = json.loads(response_fb.read().decode("utf-8"))
                    reply = res_data_fb["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e2:
                reply = f"Hello, thank you for writing. I am on-call at the TechKnow Solutions desk. I received your message: '{user_prompt}'. Please contact Caleb directly on WhatsApp at +254791204587 so we can resolve your requirements instantly!"
                
        return jsonify({"text": reply})
    except Exception as e:
        return jsonify({"text": f"Error running chatbot interface: {str(e)}"}), 500

@app.route("/api/track_visit", methods=["POST"])
def track_visit():
    try:
        req_data = request.json or {}
        path = req_data.get("path", "/")
        ip = request.remote_addr
        ua = request.headers.get("User-Agent", "Unknown")
        
        data.record_visit(ip, ua, path)
        
        # Build live WhatsApp push notification alert link
        msg_text = f"⚙️ *TechKnow Security Insight Alert*:\n👤 *Active user* landed on: `{path}`\n🌐 *IP Address*: `{ip}`\n📱 *Device*: {ua[:60]}\n⏰ *Timestamp*: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        encoded_msg = urllib.parse.quote(msg_text)
        wa_link = f"https://wa.me/254791204587?text={encoded_msg}"
        
        return jsonify({
            "status": "success",
            "ip_address": ip,
            "path": path,
            "wa_link": wa_link,
            "msg_text": msg_text
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ====== AUTH ======
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

# ====== ADMIN PANEL ======
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
        filtered = [(i, m) for (i, m) in indexed if q_l in (m.get("name","").lower() + " " + m.get("email","").lower() + " " + m.get("message","").lower())]
    else:
        filtered = indexed

    if show == "unread":
        filtered = [(i, m) for (i, m) in filtered if m.get("status") == "unread"]

    total_filtered = len(filtered)
    pages = max(1, math.ceil(total_filtered / per_page))
    if page > pages: page = pages
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

    # Calculate blog views stats
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
        daily_visits=data.get_daily_visits_summary(),
        total_visits=data.get_total_visits_count(),
        most_viewed_blog=most_viewed_blog,
        most_viewed_category=most_viewed_category
    )

# ====== JSON endpoints (admin-only) ======
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

# ====== TECHRICH MANAGED ARTICLES & DOCUMENT REPOSITORY ENDPOINTS ======
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
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else "application/msword"
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
            
    doc_id = data.save_techrich_doc(title, doc_type, file_name=filename, file_data=file_bytes, mimetype=mimetype, content=text_content)
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
        return send_file(io.BytesIO(doc["file_data"]), mimetype=doc["mimetype"] or "application/pdf")
    elif doc["doc_type"] == "word" and doc["file_data"]:
        return send_file(io.BytesIO(doc["file_data"]), mimetype=doc["mimetype"], download_name=doc["file_name"], as_attachment=False)
    else:
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
        return send_file(io.BytesIO(doc["file_data"]), mimetype=doc["mimetype"], download_name=doc["file_name"], as_attachment=True)
    else:
        filename = secure_filename(doc["title"]) or "note"
        if not filename.endswith(".md"):
            filename += ".md"
        return send_file(
            io.BytesIO(doc["content"].encode("utf-8")),
            mimetype="text/markdown",
            download_name=filename,
            as_attachment=True
        )

# ====== ADMIN Analytics data endpoint (Phase 1) ======
@app.route("/admin/analytics_data")
def admin_analytics_data():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403
    labels, values = data.get_messages_counts_last_n_days(30)
    return jsonify({"labels": labels, "values": values})

@app.route("/api/admin/active_users")
def active_users_data():
    # Allow simulated visitors for presentation / testing
    is_simulating = request.args.get("simulate", "false") == "true"
    sim_count = int(request.args.get("sim_count", "0"))
    
    conn = data.get_conn()
    count = 1
    recent_pages = []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(DISTINCT ip_address) FROM site_visits 
                    WHERE timestamp >= now() - INTERVAL '15 minutes'
                """)
                row = cur.fetchone()
                if row:
                    count = row[0]
                
                cur.execute("""
                    SELECT path, COUNT(*) as cnt FROM site_visits 
                    WHERE timestamp >= now() - INTERVAL '15 minutes'
                    GROUP BY path ORDER BY cnt DESC LIMIT 6
                """)
                recent_pages = [{"path": r[0] if r[0] else "/", "count": r[1]} for r in cur.fetchall()]
    except Exception as e:
        print(f"Error getting active users: {e}")
    finally:
        conn.close()
        
    if count < 1:
        count = 1
        
    if is_simulating and sim_count > 0:
        count = sim_count
        # Inject some simulated trending paths so it is extremely visual and amazing
        recent_pages = [
            {"path": "/", "count": int(sim_count * 0.4) or 1},
            {"path": "/blog", "count": int(sim_count * 0.35) or 1},
            {"path": "/blog/securing-mpesa-routing", "count": int(sim_count * 0.15) or 1},
            {"path": "/admin", "count": int(sim_count * 0.1) or 1}
        ]

    return jsonify({
        "status": "success",
        "active_users": count,
        "recent_pages": recent_pages
    })

# ====== MESSAGE DELETE ======
@app.route("/admin/delete_message/<int:mid>", methods=["POST"])
def delete_message(mid):
    if not require_admin():
        return redirect(url_for("login"))
    ok, deleted = data.delete_message_by_index(mid)
    if not ok:
        flash("Message not found.")
        return redirect(url_for("admin"))
    flash(f"Deleted message from {deleted.get('name','unknown')}.")
    return redirect(url_for("admin"))

# ====== Export messages CSV ======
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

# ====== PROJECT MANAGEMENT (admin) ======
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

# ====== CV UPLOAD (admin only) ======
@app.route("/admin/upload_cv", methods=["POST"])
def upload_cv_admin():
    if not require_admin():
        return redirect(url_for("login"))
    up = request.files.get("cv")
    if not up or up.filename == "":
        flash("No CV selected.")
        return redirect(url_for("admin"))
    if not allowed_file(up.filename):
        flash("Invalid file type.")
        return redirect(url_for("admin"))
    fname, err = data.save_file_from_storage('cv', up, rename_to=f"Caleb_Muga_CV.{up.filename.rsplit('.',1)[1].lower()}", approve=True, single_replace=True)
    if err:
        flash(err)
    else:
        flash("CV uploaded successfully! ✅")
    return redirect(url_for("admin"))

# ====== MEDIA UPLOADS (admin) ======
@app.route("/admin/upload_profile_image", methods=["POST"])
def upload_profile_image():
    if not require_admin():
        return redirect(url_for("login"))
    up = request.files.get("image")
    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))
    if not allowed_image(up.filename):
        flash("Invalid image type.")
        return redirect(url_for("admin"))
    fname, err = data.save_file_from_storage('profile', up, approve=True, single_replace=True)
    if err:
        flash(err)
    else:
        flash("Profile image updated. ✅")
    return redirect(url_for("admin"))

@app.route("/admin/upload_hero_image", methods=["POST"])
def upload_hero_image():
    if not require_admin():
        return redirect(url_for("login"))
    up = request.files.get("image")
    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))
    if not allowed_image(up.filename):
        flash("Invalid image type.")
        return redirect(url_for("admin"))
    fname, err = data.save_file_from_storage('hero', up, approve=True, single_replace=True)
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
            fname, err = data.save_file_from_storage('gallery', up, approve=True)
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
    
    # Safety Check: check if referenced in any blog post
    blogs = data.load_blogs()
    found_ref = False
    ref_slugs = []
    for b in blogs:
        if fname in b['content']:
            found_ref = True
            ref_slugs.append(b['title'])
    if found_ref:
        flash(f"⚠️ Cannot delete '{fname}' because it is currently used in the blog post(s): {', '.join(ref_slugs)}. Please edit those posts first!")
        return redirect(url_for("admin") + "#blog_media_section")

    ok = data.delete_file('gallery', fname)
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
            fname, err = data.save_file_from_storage('blog_media', up, approve=True)
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
    
    # Safety Check: check if referenced in any blog post
    blogs = data.load_blogs()
    found_ref = False
    ref_slugs = []
    for b in blogs:
        if fname in b['content']:
            found_ref = True
            ref_slugs.append(b['title'])
    if found_ref:
        flash(f"⚠️ Cannot delete '{fname}' because it is currently used in the blog post(s): {', '.join(ref_slugs)}. Please edit those posts first!")
        return redirect(url_for("admin") + target_pane)

    ok = data.delete_file('blog_media', fname)
    if ok:
        flash(f"Deleted blog media '{fname}'.")
    else:
        flash("Media not found.")
    return redirect(url_for("admin") + target_pane)

# ====== BLOG (admin create/delete) ======
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
    
    # Store dynamic WhatsApp promotion context
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

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

# ====== ERROR HANDLERS (Phase 1) ======
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

# Custom template filter converts markdown to HTML, including inline HTML video players
@app.template_filter('render_markdown')
def render_markdown(text):
    if not text:
        return ""
    try:
        import markdown
        # Convert the post text to HTML, supporting HTML5 <video> embedding
        return markdown.markdown(text, extensions=['fenced_code', 'codehilite'])
    except Exception as e:
        print(f"Error rendering markdown custom extensions: {e}")
        try:
            import markdown
            return markdown.markdown(text)
        except Exception as e2:
            print(f"Fallback markdown failed too: {e2}")
            import html
            return f"<pre>{html.escape(text)}</pre>"

@app.template_filter('get_first_image')
def get_first_image(text):
    if not text:
        return ""
    import re
    # 1. Look for markdown image patterns like ![alt](url)
    md_img = re.search(r'!\[.*?\]\((.*?)\)', text)
    if md_img:
        return md_img.group(1).strip()
    # 2. Look for HTML img tags including src value
    html_img = re.search(r'<img[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)
    if html_img:
        return html_img.group(1).strip()
    # 3. Look for HTML video tags src value
    html_video = re.search(r'<video[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)
    if html_video:
        return html_video.group(1).strip()
    # 4. Look for HTML video <source> tags src value
    html_source = re.search(r'<source[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)
    if html_source:
        return html_source.group(1).strip()
    # 5. Look for any markdown link that is a video file
    md_link = re.findall(r'\[.*?\]\((.*?)\)', text)
    for link in md_link:
        if any(ext in link.lower() for ext in ['.mp4', '.webm', '.ogg', '.mov', '.m4v']):
            return link.strip()
    # Let's also try a more permissive src extraction in case style quotes are weird
    html_img_fallback = re.search(r'src=["\'](.*?)["\']', text, re.IGNORECASE)
    if html_img_fallback:
        val = html_img_fallback.group(1).strip()
        if any(ext in val.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp4', '.webm', '.ogg', '.mov', '.m4v', '/media/']):
            return val
    return ""

@app.template_filter('clean_excerpt')
def clean_excerpt(text, length=160):
    if not text:
        return ""
    import re
    # Remove any figcaption blocks completely so caption text does not merge into the preview
    text_no_caption = re.sub(r'<figcaption[^>]*>.*?</figcaption>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text_no_html = re.sub(r'<[^>]+>', ' ', text_no_caption)
    # Remove markdown images
    text_no_md_img = re.sub(r'!\[.*?\]\(.*?\)', ' ', text_no_html)
    # Clean up markdown links: [text](url) -> text
    text_no_md_links = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text_no_md_img)
    # Remove headers formatting / bold / code blocks headers
    cleaned = re.sub(r'#+\s+', '', text_no_md_links)
    cleaned = re.sub(r'\*+', '', cleaned)
    cleaned = re.sub(r'`+', '', cleaned)
    
    # Compress multiple whitespaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    if len(cleaned) <= length:
        return cleaned
    return cleaned[:length] + "..."

@app.template_filter('get_reading_time')
def get_reading_time(text):
    if not text:
        return 1
    words = len(text.split())
    # Average reading speed is 200 words per minute
    minutes = max(1, int(words / 200))
    return minutes

@app.template_filter('get_category')
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

# ====== MAIN ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
