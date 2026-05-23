import os
import io
import math
import secrets
import urllib.parse
from datetime import datetime, timedelta
from collections import Counter
import markdown


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

# ====== HELPERS ======
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
    blogs = data.load_blogs()
    return render_template("blog_list.html", blogs=blogs)

@app.route("/blog/<slug>")
def view_blog(slug):
    post = data.get_blog_by_slug(slug)
    if not post:
        abort(404)
    return render_template("blog_view.html", post=post)

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
        subscribers=subscribers
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

@app.route("/admin/toggle_read_json/<int:mid>", methods=["POST"])
def toggle_read_json(mid):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403
    ok, new = data.toggle_message_status_by_index(mid)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": new})

# ====== ADMIN Analytics data endpoint (Phase 1) ======
@app.route("/admin/analytics_data")
def admin_analytics_data():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403
    labels, values = data.get_messages_counts_last_n_days(30)
    return jsonify({"labels": labels, "values": values})

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
    if not files:
        flash("Select at least one file.")
        return redirect(url_for("admin") + "#blog_media_section")
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
    return redirect(url_for("admin") + "#blog_media_section")

@app.route("/admin/delete_blog_media/<path:filename>", methods=["POST"])
def delete_blog_media(filename):
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

    ok = data.delete_file('blog_media', fname)
    if ok:
        flash(f"Deleted blog media '{fname}'.")
    else:
        flash("Media not found.")
    return redirect(url_for("admin") + "#blog_media_section")

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
    data.add_blog(title, content)
    flash("Blog post published.")
    return redirect(url_for("admin"))

@app.route("/admin/blogs/delete/<bid>", methods=["POST"])
def admin_delete_blog(bid):
    if not require_admin():
        return redirect(url_for("login"))
    data.delete_blog_by_id(bid)
    flash("Blog post deleted.")
    return redirect(url_for("admin"))

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
