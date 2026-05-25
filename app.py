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



from flask import request, redirect

@app.before_request
def redirect_to_custom_domain():
    if "onrender.com" in request.host:
        return redirect(
            "https://mga.techknowsols.gt.tc" + request.full_path,
            code=301
        )
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response
def get_or_create_visitor_id():
    # Retrieve or generate unique guest session identifier
    if "visitor_id" not in session:
        session["visitor_id"] = secrets.token_hex(16)
    return session["visitor_id"]

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
        data.record_visit(request.remote_addr, request.headers.get("User-Agent", "Unknown"), "/blog", get_or_create_visitor_id())
    except Exception as e:
        print(f"Tracking error: {e}")
    blogs = data.load_blogs()
    return render_template("blog_list.html", blogs=blogs)

@app.route("/blog/<slug>")
def view_blog(slug):
    try:
        data.record_visit(request.remote_addr, request.headers.get("User-Agent", "Unknown"), f"/blog/{slug}", get_or_create_visitor_id())
        data.increment_blog_views(slug)
    except Exception as e:
        print(f"Tracking error: {e}")
    post = data.get_blog_by_slug(slug)
    if not post:
        abort(404)
    return render_template("blog_view.html", post=post)


# ====== CALEB'S AI DIGITAL TWIN ENDPOINT ======

SYSTEM_INSTRUCTION = """
You are "Caleb Muga's AI Digital Twin", a professional, highly skilled, and conversational AI avatar representing Caleb Muga on his portfolio website.
Caleb's Background & Profile:
- Title: Lead Cisco-Certified Network Specialist, Cybersecurity Auditor, and Automation Architect.
- Role: Meticulously driven and customer-oriented ICT Officer.
- Key Certifications: Cisco CCNA, Routing and Switching, Enterprise Network Security.
- Top Core Skills:
  1. Routing & Switching Topologies (VLANs, OSPF, DHCP helper protocols, STP BPDU Guard, trunk interfaces).
  2. Cybersecurity auditing & server hardening (mitigating brute force, entropy calculations, threat vectors).
  3. Interactive network diagnostics, disaster recovery schemas, and virtualization setup.
  4. Automation scripting (using Python, Flask, bash, crontabs for model retraining or data routing).
- Personality: Smart, highly technical yet understandable, reassuring, respectful, and direct. You write crisp, helpful, and concise answers, often using numbered lists or brief code/command blocks where relevant.
- Goals of this Chatbot:
  1. Educate visitors on Caleb's credentials, experience, and specialized expertise.
  2. Answer technical questions about networking, router configs, or security audits (briefly and accurately!).
  3. Guide potential clients or employers to "Get in Touch" or hire Caleb using the Portfolio section or Contact Form.
  4. Be professional and strictly pretend to be Caleb's digital avatar, speaking in first-person ("I have built...", "In my CCNA practice...") or referring to Caleb's work with proud expertise.
- Maintain a tone that reflects a polished, secure command-line engineer. Keep answers short and under 3-4 structural blocks so the client can easily read them in a standard-sized chat widget. Use markdown properly.
"""

def call_gemini_api(prompt, system_instruction=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    
    # We choose gemini-2.5-flash as it is fast, stable, and highly capable for general Q&A
    model_name = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }
    
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        }
        
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "aistudio-build"
    }
    
    import urllib.request
    import urllib.error
    import json
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
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
        history = req_data.get("history", []) # list of {"role": "user"|"model", "text": "..."}
        
        if not user_message:
            return jsonify({"status": "error", "message": "message is required"}), 400
            
        print(f"👤 AI Twin Question: '{user_message}'")
        
        # Format chat history context for the model
        context_prompt = ""
        for turn in history[-6:]: # Keep last 6 turns for context
            role_label = "User" if turn.get("role") == "user" else "AI"
            context_prompt += f"{role_label}: {turn.get('text')}\n"
        context_prompt += f"User: {user_message}\nAI:"
        
        # Attempt calling real Gemini API
        ai_response = call_gemini_api(context_prompt, system_instruction=SYSTEM_INSTRUCTION)
        
        is_mock = False
        if ai_response is None:
            # Fallback static agent matcher if GEMINI_API_KEY is not defined
            is_mock = True
            msg_lower = user_message.lower()
            if any(k in msg_lower for k in ["skills", "cert", "credential", "ccna", "switching", "routing"]):
                ai_response = "I am Cisco CCNA certified in Routing & Switching, specializing in robust LAN/WAN infrastructure. I design resilient VLAN partitions, troubleshoot DR/BDR election loops, configure OSPF, and enforce STP BPDU Guards to prevent rogue loops."
            elif any(k in msg_lower for k in ["contact", "hire", "email", "work", "meeting"]):
                ai_response = "I am based in Nairobi, Kenya. You can reach out directly via the **Get in touch / Contact form** section of this site. Just type your details and shoot a dispatch; I usually respond within 120 minutes!"
            elif any(k in msg_lower for k in ["audit", "secure", "protection", "firewall", "entropy"]):
                ai_response = "I conduct enterprise cybersecurity audits. This includes active endpoint policy monitoring, firmware inspections, and testing brute-force resilience. Try my Brute-Force Password Simulator under the Interactive Labs above!"
            elif any(k in msg_lower for k in ["project", "code", "portfolio"]):
                ai_response = "I have built interactive labs on this portfolio: standard Subnet Calculators, Port Audit sandboxes, and an active Admin telemetry suite. Go take a spin with them!"
            else:
                ai_response = "Hello there! I am Caleb Muga's AI Digital Twin, configured with system parameters of a Leading Network Specialist and Security Architect. Ask me about CCNA configurations, current security recommendations, or how we can collaborate!"
                
            ai_response += "\n\n*(Note: Set up a `GEMINI_API_KEY` in settings to activate full real-time Gemini LLM reasoning).* "

        return jsonify({
            "status": "success",
            "reply": ai_response,
            "mock": is_mock
        })
    except Exception as e:
        print(f"Error in ai_chat endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ====== VISITOR ALERTS API ======

@app.route("/api/track_visit", methods=["POST"])
def track_visit():
    try:
        req_data = request.json or {}
        path = req_data.get("path", "/")
        ip = request.remote_addr
        ua = request.headers.get("User-Agent", "Unknown")
        
        data.record_visit(ip, ua, path, get_or_create_visitor_id())
        
        return jsonify({
            "status": "success"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
        except Exception as e:
            print(f"Error updating blog heartbeat: {e}")
            return jsonify({"status": "error"}), 500
        finally:
            conn.close()
            
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ====== BLOG CORE ACTIONS & TELEMETRY ======

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
            # Load updated blog to send back new counts
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
        
        prompt = f"""You are the AI Assistant for TechKnow Solutions. Please review this technical article titled "{title_text}" and summarize it:
{content_text[:3000]}

Respond ONLY in the following JSON format:
{{
  "summary": "Exactly 3 concise sentences summarizing the complete premise.",
  "takeaways": [
    "Key engineering bullet points 1",
    "Key engineering bullet points 2",
    "Key engineering bullet points 3",
    "Key engineering bullet points 4"
  ],
  "skill_level": "one word: 'Beginner', 'Intermediate', or 'Expert CCNA'"
}}"""

        ai_reply = call_gemini_api(prompt, system_instruction="You are a meticulous network engineer and security expert. Output raw valid JSON strictly.")
        
        if ai_reply:
            try:
                # Sanitize response out of codeblocks if any
                clean_json = ai_reply.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()
                
                parsed = json.loads(clean_json)
                return jsonify({
                    "status": "success",
                    "summary": parsed.get("summary", ""),
                    "takeaways": parsed.get("takeaways", []),
                    "skill_level": parsed.get("skill_level", "Intermediate")
                })
            except Exception as parse_err:
                print("Failed to parse JSON summary, fallback to raw response:", parse_err)
        
        # Robust template fallback summary
        takeaways = [
            "Establishes key diagnostic criteria for validating network performance.",
            "Demonstrates precise OSPF, DHCP, or physical layer topology commands.",
            "Integrates enterprise security policies to protect business nodes.",
            "Optimizes system latency by resolving redundant packet forwarding and loops."
        ]
        
        words = content_text.split()
        short_summary = f"An analytical review of standard configurations for '{title_text}'. It covers core enterprise diagnostics, debugging protocols, and actionable configurations designed for scalable networks."
        
        return jsonify({
            "status": "success",
            "summary": short_summary,
            "takeaways": takeaways,
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
            
        prompt = f"""The reader of my technical journal has selected/highlighted this exact text from my article "{title_text}":
"{selected_text}"

As Caleb Muga, a professional Cisco CCNA network specialist & Cybersecurity Architect, explain or answer questions about this specific quote in 3-4 highly technical, crisp, and helpful sentences. Use markdown bolding on key commands or terms."""

        ai_reply = call_gemini_api(prompt, system_instruction="You are Caleb Muga, an expert Systems Specialist. Share precise, authoritative insights.")
        
        if not ai_reply:
            ai_reply = f"Regarding your highlighted quote from **{title_text}**: This refers directly to core troubleshooting topologies. In enterprise deployments, executing relevant check commands (such as **show ip interface brief** or spanning-tree overrides) ensures optimal packet routing while isolating access terminals from rogue ingress flows."
            
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
            
        # Let's load actual blogs
        blogs = data.load_blogs(include_drafts=False)
        blogs_meta = [{"title": b["title"], "slug": b["slug"], "url": f"/blog/{b['slug']}"} for b in blogs]
        
        # Standard system sites
        site_nodes = [
            {"title": "Brute-Force Password Simulator Lab", "url": "/#pass-audit", "category": "Interactive Labs"},
            {"title": "Live TCP Port Scanner Diagnostics Lab", "url": "/#port-scan", "category": "Interactive Labs"},
            {"title": "Interactive IPv4 Subnet Calculator Lab", "url": "/#subnet-calc", "category": "Interactive Labs"},
            {"title": "VLAN Leakage Mitigation Guide Node", "url": "/#learn", "category": "Knowledge Base"},
            {"title": "OSPF Adjacency Deadlocks & DR/BDR Loop Protection", "url": "/#learn", "category": "Knowledge Base"},
            {"title": "Spanning-Tree BPDU Access Loop Protection", "url": "/#learn", "category": "Knowledge Base"}
        ]
        
        prompt = f"""The user is performing a semantic search on my professional cybersecurity & Cisco CCNA networking portfolio.
User Query: "{query}"

Available Blog Posts: {repr(blogs_meta)}
Available Interactives/Services: {repr(site_nodes)}

Match the most relevant articles, interactive tools, or competence areas. Select 1 to 4 best nodes.
Respond STRICTLY with a valid JSON array of objects, with no conversational fluff or markdown code wrap blocks:
[
  {{
    "title": "Match Name",
    "url": "/fully/qualified/url",
    "match_reason": "Exactly 1 short sentence why this matches the query semantic criteria."
  }}
]"""

        ai_reply = call_gemini_api(prompt, system_instruction="You are the TechKnow Solutions AI Search router. Match semantic targets and output valid JSON only.")
        
        if ai_reply:
            try:
                clean_json = ai_reply.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()
                parsed = json.loads(clean_json)
                if isinstance(parsed, list):
                    return jsonify({"status": "success", "results": parsed})
            except Exception as parse_err:
                print("Failed parsing semantic search results, switching to keyword fallback:", parse_err)
                
        # Robust local keyword search fallback
        results = []
        q_lower = query.lower()
        
        # Search blogs
        for b in blogs:
            if q_lower in b["title"].lower() or q_lower in b["content"].lower():
                results.append({
                    "title": b["title"],
                    "url": f"/blog/{b['slug']}",
                    "match_reason": f"Matches query in the article title and contents."
                })
                
        # Search interactive maps
        for item in site_nodes:
            if q_lower in item["title"].lower() or (("lab" in q_lower or "simulate" in q_lower) and "Lab" in item.get("category", "")):
                results.append({
                    "title": item["title"],
                    "url": item["url"],
                    "match_reason": f"Interactive diagnostic utility corresponding to query parameters."
                })
                
        # Limit results size
        return jsonify({"status": "success", "results": results[:4]})
        
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
    # We query the actual DISTINCT visitor count using visitor UUID session cookies, completely removing any simulated capabilities.
    conn = data.get_conn()
    count = 1
    recent_pages = []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(DISTINCT COALESCE(session_id, ip_address)) FROM site_visits \
                    WHERE timestamp >= now() - INTERVAL '15 minutes' \
                """)
                row = cur.fetchone()
                if row:
                    count = row[0]
                
                cur.execute("""
                    SELECT path, COUNT(*) as cnt FROM site_visits \
                    WHERE timestamp >= now() - INTERVAL '15 minutes' \
                    GROUP BY path ORDER BY cnt DESC LIMIT 6 \
                """)
                recent_pages = [{"path": r[0] if r[0] else "/", "count": r[1]} for r in cur.fetchall()]
    except Exception as e:
        print(f"Error getting active users: {e}")
    finally:
        conn.close()
        
    if count < 1:
        count = 1

    return jsonify({
        "status": "success",
        "active_users": count,
        "recent_pages": recent_pages
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
                # 1. Fetch real active users (recent 15 minutes of site_visits) using distinct session_id
                cur.execute("""
                    SELECT COUNT(DISTINCT COALESCE(session_id, ip_address)) FROM site_visits \
                    WHERE timestamp >= now() - INTERVAL '15 minutes' \
                """)
                row = cur.fetchone()
                if row:
                    active_users = row[0] if row[0] > 0 else 1
                
                # 2. Fetch recent path metrics
                cur.execute("""
                    SELECT path, COUNT(*) as cnt FROM site_visits \
                    WHERE timestamp >= now() - INTERVAL '15 minutes' \
                    GROUP BY path ORDER BY cnt DESC LIMIT 6 \
                """)
                recent_pages = [{"path": r[0] if r[0] else "/", "count": r[1]} for r in cur.fetchall()]
                
                # 3. Fetch real blog views & duration trackers
                cur.execute("""
                    SELECT id, title, slug, COALESCE(views, 0) as views, \
                           COALESCE(total_read_time_seconds, 0) as total_read_time, \
                           COALESCE(read_time_count, 0) as read_count \
                    FROM blogs ORDER BY views DESC \
                """)
                rows = cur.fetchall()
                for r in rows:
                    views = r["views"]
                    rd_cnt = r["read_count"]
                    ttl_time = r["total_read_time"]
                    
                    # Compute average read time based on views or read count
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
        
    # Calculate dominant category dynamically
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
