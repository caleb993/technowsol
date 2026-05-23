```python
# app.py
import os
import io
import math
import secrets
import urllib.parse
import re
from datetime import datetime, timedelta
from collections import Counter

import data

# Run table creation once at startup
if __name__ == "__main__":
    print("🔄 Creating tables...")
    data.create_tables()
    print("✅ Tables ready!")

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, flash, abort, session, jsonify, Response
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))

# ====== CONFIG ======
ADMIN_KEY = os.environ.get("ADMIN_KEY", "calebadmin")

# Allowed extensions
ALLOWED_EXTS = {
    "pdf", "doc", "docx", "png", "jpg", "jpeg",
    "zip", "txt", "ppt", "pptx", "webp", "gif",
    "mp4", "webm", "ogg", "mov", "m4v"
}

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
VIDEO_EXTS = {"mp4", "webm", "ogg", "mov", "m4v"}

BLOG_MEDIA_EXTS = IMAGE_EXTS.union(VIDEO_EXTS)

app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB

# Initialize DB
data.create_tables()

# ====== HELPERS ======
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS

def allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in IMAGE_EXTS

def allowed_video(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in VIDEO_EXTS

def allowed_blog_media(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in BLOG_MEDIA_EXTS

def is_video(filename: str) -> bool:
    if not filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in VIDEO_EXTS

def require_admin():
    if not session.get("is_admin"):
        flash("Please log in as admin.")
        return False
    return True

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text

def latest_file(category, only_images=False):
    rec = data.get_latest_file_record(category, only_images=only_images)

    if not rec:
        return None, None

    ts = int(rec["uploaded_at"].timestamp()) if rec.get("uploaded_at") else 0

    return rec.get("name"), ts

def owner_cv_filename():
    return data.get_latest_filename('cv')

def list_projects():
    return data.list_projects(approved=True)

def list_pending():
    return data.list_projects(approved=False)

def list_gallery_media():
    items = data.list_gallery_media()
    return items

def media_url(kind, filename):
    if not filename:
        return None

    category = (
        "profile" if kind == "profile"
        else "hero" if kind == "hero"
        else "gallery"
    )

    ts = data.get_file_timestamp(category, filename) or 0

    return (
        url_for("media_file", kind=kind, filename=filename)
        + f"?v={int(ts)}"
    )

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

# ====== NEWSLETTER ======
@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = (request.form.get("email") or "").strip().lower()

    if not email or "@" not in email:
        flash("Please provide a valid email address.")
        return redirect(url_for("index") + "#newsletter")

    data.save_subscriber(email)

    flash("Thanks! You are subscribed to updates.")

    return redirect(url_for("index") + "#newsletter")

# ====== CONTACT ======
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

# ====== PROJECT UPLOAD ======
@app.route("/upload_project", methods=["POST"])
def upload_project():
    up = request.files.get("file")

    if not up or up.filename == "":
        flash("No file selected.")
        return redirect(url_for("index") + "#portfolio")

    if not allowed_file(up.filename):
        flash("Invalid file type.")
        return redirect(url_for("index") + "#portfolio")

    fname, err = data.save_file_from_storage(
        'project',
        up,
        approve=False
    )

    if err:
        flash(err)
    else:
        flash(f"Project '{fname}' uploaded successfully. ✅")

    return redirect(url_for("index") + "#portfolio")

# ====== DOWNLOADS ======
@app.route("/download/<kind>/<path:filename>")
def download_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))

    if kind == "project":
        rec = data.get_file_record('project', safe, approved=True)

    elif kind == "cv":
        rec = data.get_file_record('cv', safe)

    else:
        abort(404)

    if not rec:
        abort(404)

    content = rec['content']
    mimetype = rec.get('mimetype') or 'application/octet-stream'

    return send_file(
        io.BytesIO(content),
        download_name=safe,
        as_attachment=True,
        mimetype=mimetype
    )

# ====== MEDIA ======
@app.route("/media/<kind>/<path:filename>")
def media_file(kind, filename):
    safe = secure_filename(urllib.parse.unquote(filename))

    category = (
        "profile" if kind == "profile"
        else "hero" if kind == "hero"
        else "gallery"
    )

    rec = data.get_file_record(category, safe)

    if not rec:
        abort(404)

    return send_file(
        io.BytesIO(rec['content']),
        download_name=safe,
        as_attachment=False,
        mimetype=rec.get('mimetype') or 'application/octet-stream'
    )

# ====== BLOG MEDIA ======
@app.route("/blog_media/<path:filename>")
def blog_media(filename):
    safe = secure_filename(urllib.parse.unquote(filename))

    rec = data.get_file_record("blog_media", safe)

    if not rec:
        abort(404)

    return send_file(
        io.BytesIO(rec["content"]),
        download_name=safe,
        as_attachment=False,
        mimetype=rec.get("mimetype") or "application/octet-stream"
    )

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
            flash("Logged in successfully.")
            return redirect(url_for("admin"))

        flash("Wrong admin passcode.")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Logged out successfully.")
    return redirect(url_for("index"))

# ====== ADMIN ======
@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("login"))

    full_msgs = data.load_messages()

    total_messages = len(full_msgs)
    unread_count = sum(
        1 for m in full_msgs
        if m.get("status") == "unread"
    )

    pending = list_pending()
    projects = list_projects()

    pending_count = len(pending)
    approved_count = len(projects)

    prof_name, _ = latest_file("profile", only_images=True)
    hero_name, _ = latest_file("hero", only_images=True)

    gal = list_gallery_media()
    blogs = data.load_blogs()
    subscribers = data.load_subscribers()

    return render_template(
        "admin.html",
        total_messages=total_messages,
        unread_count=unread_count,
        pending_count=pending_count,
        approved_count=approved_count,
        pending=pending,
        projects=projects,
        cv_file=owner_cv_filename(),
        prof=prof_name,
        hero=hero_name,
        gal=gal,
        blogs=blogs,
        subscribers=subscribers
    )

# ====== BLOG MANAGEMENT ======
@app.route("/admin/blogs/add", methods=["POST"])
def admin_add_blog():
    if not require_admin():
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not title or not content:
        flash("Title and content are required.")
        return redirect(url_for("admin"))

    slug = slugify(title)

    media_file_upload = request.files.get("media")

    media_filename = None
    media_type = None

    if media_file_upload and media_file_upload.filename:

        if not allowed_blog_media(media_file_upload.filename):
            flash("Invalid blog media format.")
            return redirect(url_for("admin"))

        media_filename, err = data.save_file_from_storage(
            "blog_media",
            media_file_upload,
            approve=True
        )

        if err:
            flash(err)
            return redirect(url_for("admin"))

        if is_video(media_filename):
            media_type = "video"
        else:
            media_type = "image"

    data.add_blog(
        title=title,
        content=content,
        slug=slug,
        media=media_filename,
        media_type=media_type
    )

    flash("Blog published successfully. ✅")

    return redirect(url_for("admin"))

@app.route("/admin/blogs/delete/<bid>", methods=["POST"])
def admin_delete_blog(bid):
    if not require_admin():
        return redirect(url_for("login"))

    data.delete_blog_by_id(bid)

    flash("Blog deleted successfully.")

    return redirect(url_for("admin"))

# ====== CV UPLOAD ======
@app.route("/admin/upload_cv", methods=["POST"])
def upload_cv_admin():
    if not require_admin():
        return redirect(url_for("login"))

    up = request.files.get("cv")

    if not up or up.filename == "":
        flash("No CV selected.")
        return redirect(url_for("admin"))

    if not allowed_file(up.filename):
        flash("Invalid CV format.")
        return redirect(url_for("admin"))

    fname, err = data.save_file_from_storage(
        'cv',
        up,
        rename_to=f"Caleb_Muga_CV.{up.filename.rsplit('.',1)[1].lower()}",
        approve=True,
        single_replace=True
    )

    if err:
        flash(err)
    else:
        flash("CV uploaded successfully! ✅")

    return redirect(url_for("admin"))

# ====== PROFILE IMAGE ======
@app.route("/admin/upload_profile_image", methods=["POST"])
def upload_profile_image():
    if not require_admin():
        return redirect(url_for("login"))

    up = request.files.get("image")

    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))

    if not allowed_image(up.filename):
        flash("Invalid image format.")
        return redirect(url_for("admin"))

    fname, err = data.save_file_from_storage(
        'profile',
        up,
        approve=True,
        single_replace=True
    )

    if err:
        flash(err)
    else:
        flash("Profile image updated. ✅")

    return redirect(url_for("admin"))

# ====== HERO IMAGE ======
@app.route("/admin/upload_hero_image", methods=["POST"])
def upload_hero_image():
    if not require_admin():
        return redirect(url_for("login"))

    up = request.files.get("image")

    if not up or up.filename == "":
        flash("No image selected.")
        return redirect(url_for("admin"))

    if not allowed_image(up.filename):
        flash("Invalid image format.")
        return redirect(url_for("admin"))

    fname, err = data.save_file_from_storage(
        'hero',
        up,
        approve=True,
        single_replace=True
    )

    if err:
        flash(err)
    else:
        flash("Hero image updated successfully. ✅")

    return redirect(url_for("admin"))

# ====== GALLERY ======
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

        ext = (
            up.filename.rsplit(".", 1)[-1].lower()
            if "." in up.filename else ""
        )

        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:

            fname, err = data.save_file_from_storage(
                'gallery',
                up,
                approve=True
            )

            if fname:
                uploaded += 1

    if uploaded:
        flash(f"{uploaded} gallery media uploaded successfully. ✅")
    else:
        flash("No valid media uploaded.")

    return redirect(url_for("admin"))

@app.route("/admin/delete_gallery/<path:filename>", methods=["POST"])
def delete_gallery_image(filename):
    if not require_admin():
        return redirect(url_for("login"))

    fname = secure_filename(urllib.parse.unquote(filename))

    ok = data.delete_file('gallery', fname)

    if ok:
        flash(f"Deleted '{fname}'.")
    else:
        flash("Media not found.")

    return redirect(url_for("admin"))

# ====== ANALYTICS ======
@app.route("/admin/analytics_data")
def admin_analytics_data():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 403

    labels, values = data.get_messages_counts_last_n_days(30)

    return jsonify({
        "labels": labels,
        "values": values
    })

# ====== SITEMAP ======
@app.route('/sitemap.xml')
def sitemap():
    from flask import send_from_directory
    return send_from_directory('static', 'sitemap.xml')

# ====== ERROR HANDLERS ======
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

# ====== MAIN ======
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
```
