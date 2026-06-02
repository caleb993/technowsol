
    // Message details viewer and auto mark as read
    function openMessageModal(mid, name, email, timestamp, status) {
      document.getElementById('modalSender').innerText = name;
      document.getElementById('modalEmail').innerText = email;
      document.getElementById('modalTimestamp').innerText = timestamp;
      
      var rawMsg = document.getElementById('full-msg-' + mid).innerText;
      document.getElementById('modalContent').innerText = rawMsg;
      
      const modal = new bootstrap.Modal(document.getElementById('messageModal'));
      modal.show();
      
      if (status === 'unread') {
        fetch('/admin/mark_read_json/' + mid, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        })
        .then(res => res.json())
        .then(data => {
          // reload the layout once they close the modal to update counts
          document.getElementById('messageModal').addEventListener('hidden.bs.modal', function() {
            window.location.reload();
          }, { once: true });
        })
        .catch(e => console.error(e));
      }
    }

    // Toggle read unread message dynamically over JSON endpoints
    function toggleReadStatus(mid, btnNode) {
      fetch('/admin/toggle_read_json/' + mid, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      })
      .then(res => res.json())
      .then(data => {
        if (data.status) {
          // reload window to update counts and state dynamically
          window.location.reload();
        } else {
          alert('Verification error: ' + (data.error || 'Server rejected request.'));
        }
      })
      .catch(e => {
        console.error(e);
        alert('Network anomaly reported.');
      });
    }

    // Blog post editing controller
    function loadBlogForEditing(bid) {
      fetch('/admin/blogs/get/' + bid)
        .then(res => res.json())
        .then(blog => {
          if (blog.error) {
            alert("Could not load blog post data: " + blog.error);
            return;
          }
          // Populate fields
          document.getElementById('edit-blog-id').value = blog.id;
          document.getElementById('title').value = blog.title;
          document.getElementById('blogContent').value = blog.content;
          if (document.getElementById('blogCategory')) document.getElementById('blogCategory').value = blog.category || 'Auto';
          if (document.getElementById('blogTrending')) document.getElementById('blogTrending').value = blog.is_trending ? '1' : '0';
          if (document.getElementById('blogExcerpt')) document.getElementById('blogExcerpt').value = blog.excerpt || '';
          if (document.getElementById('blogFeaturedImage')) { document.getElementById('blogFeaturedImage').value = blog.featured_image || ''; refreshFeaturedPreview(); }
          if (window.tinymce && tinymce.get('blogContent')) { tinymce.get('blogContent').setContent(blog.content || ''); }
          
          // Update form action and UI labels
          document.getElementById('blog-form').action = '/admin/blogs/edit/' + blog.id;
          document.getElementById('editor-title').innerHTML = '<i class="bi bi-pencil-fill text-warning me-2"></i>Edit Insight: ' + blog.title;
          document.getElementById('blog-submit-btn').innerHTML = 'Save Changes <i class="bi bi-check-circle-fill"></i>';
          document.getElementById('cancel-edit-btn').classList.remove('d-none');
          
          // Smooth scroll to the editor top
          document.getElementById('blogs-pane').scrollIntoView({ behavior: 'smooth' });
        })
        .catch(e => {
          console.error(e);
          alert("Error fetching blog details.");
        });
    }

    // copy clipboard helper for markdown library references
    function copyToClipboard(val, buttonElement) {
      navigator.clipboard.writeText(val).then(() => {
        const orig = buttonElement.innerHTML;
        buttonElement.innerHTML = '<i class="bi bi-check-all"></i> Copied!';
        buttonElement.classList.remove('btn-outline-warning');
        buttonElement.classList.add('btn-success');
        buttonElement.classList.add('text-black');
        setTimeout(() => {
          buttonElement.innerHTML = orig;
          buttonElement.classList.remove('btn-success');
          buttonElement.classList.remove('text-black');
          buttonElement.classList.add('btn-outline-warning');
        }, 1800);
      }).catch(e => {
        alert('Clipboard permissions blocks browser automatic writeback.');
      });
    }



    function refreshFeaturedPreview(){
      const input = document.getElementById('blogFeaturedImage');
      const box = document.getElementById('featuredThumbPreview');
      if(!input || !box) return;
      const url = (input.value || '').trim();
      if(!url){ box.innerHTML = '<i class="bi bi-image text-muted"></i>'; return; }
      box.innerHTML = `<img src="${url}" alt="Selected article thumbnail" onerror="this.parentElement.innerHTML='<i class=\'bi bi-image-alt text-warning\'></i>'">`;
    }

    function useAsFeaturedImage(url, buttonElement){
      const input = document.getElementById('blogFeaturedImage');
      if(!input) return;
      input.value = url || '';
      refreshFeaturedPreview();
      if(buttonElement){
        const original = buttonElement.innerHTML;
        buttonElement.innerHTML = '<i class="bi bi-check2-circle"></i> Selected';
        buttonElement.classList.remove('btn-outline-info');
        buttonElement.classList.add('btn-success','text-black');
        setTimeout(()=>{buttonElement.innerHTML=original;buttonElement.classList.add('btn-outline-info');buttonElement.classList.remove('btn-success','text-black');},1500);
      }
    }
    document.addEventListener('input', function(e){ if(e.target && e.target.id === 'blogFeaturedImage') refreshFeaturedPreview(); });

    // Insert media directly into TinyMCE rich editor or textarea fallback.
    function insertMediaTag(url, type) {
      const filename = decodeURIComponent((url || '').split('/').pop() || 'blog-media');
      const safeAlt = filename.replace(/[-_]/g, ' ').replace(/\.[^/.]+$/, '');
      let html = '';

      if (type === 'image') {
        html = `<figure class="article-media-frame"><img src="${url}" alt="${safeAlt}" class="blog-media article-media" loading="lazy"><figcaption>${safeAlt}</figcaption></figure><p></p>`;
      } else {
        html = `<figure class="article-media-frame"><video src="${url}" controls playsinline preload="metadata" class="embedded-video blog-media article-media"></video><figcaption>${safeAlt}</figcaption></figure><p></p>`;
      }

      if (window.tinymce && tinymce.get('blogContent')) {
        tinymce.get('blogContent').insertContent(html);
        localStorage.setItem("draft_content", tinymce.get('blogContent').getContent());
        return;
      }

      var textarea = document.getElementById("blogContent");
      if (!textarea) return;
      var startPos = textarea.selectionStart || 0;
      var endPos = textarea.selectionEnd || 0;
      var text = textarea.value || '';
      textarea.value = text.substring(0, startPos) + html + text.substring(endPos);
      textarea.focus();
      textarea.selectionStart = textarea.selectionEnd = startPos + html.length;
      localStorage.setItem("draft_content", textarea.value);
    }


    function plainTextFromHtml(html) {
      const tmp = document.createElement('div');
      tmp.innerHTML = html || '';
      return (tmp.textContent || tmp.innerText || '').trim();
    }

    function updateSEOChecklist() {
      const title = (document.getElementById('title')?.value || '').trim();
      const html = (window.tinymce && tinymce.get('blogContent')) ? tinymce.get('blogContent').getContent() : (document.getElementById('blogContent')?.value || '');
      const text = plainTextFromHtml(html);
      const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
      const headings = (html.match(/<h[1-3][\s>]/gi) || []).length;
      const media = (html.match(/<img\s|<video\s|<iframe\s/gi) || []).length;

      setSEOItem('seo-title-check', title.length, title.length >= 35 && title.length <= 70, title.length >= 20);
      setSEOItem('seo-word-check', words, words >= 800, words >= 500);
      setSEOItem('seo-heading-check', headings, headings >= 2, headings >= 1);
      setSEOItem('seo-image-check', media, media >= 1, media >= 1);
    }

    function setSEOItem(id, value, good, warn) {
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.remove('good', 'warn', 'bad');
      el.classList.add(good ? 'good' : warn ? 'warn' : 'bad');
      const strong = el.querySelector('strong');
      if (strong) strong.textContent = value;
    }

    function markAutosaved() {
      const el = document.getElementById('autosave-status');
      if (!el) return;
      el.textContent = 'Autosaved ' + new Date().toLocaleTimeString();
      el.style.color = '#86efac';
    }

    function previewDraftArticle() {
      if (window.tinymce) tinymce.triggerSave();
      const title = document.getElementById('title')?.value || 'Untitled article';
      const content = (window.tinymce && tinymce.get('blogContent')) ? tinymce.get('blogContent').getContent() : (document.getElementById('blogContent')?.value || '');
      const win = window.open('', '_blank');
      if (!win) return alert('Popup blocked. Allow popups to preview.');
      win.document.write(`<!doctype html><html><head><title>${title}</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Inter,Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 18px;line-height:1.75;color:#111827}img,video,iframe{max-width:100%;border-radius:16px;display:block;margin:22px auto}h1,h2,h3{line-height:1.25}table{width:100%;border-collapse:collapse}td,th{border:1px solid #ddd;padding:10px}
    /* ADMIN POLISH V4 */
    .card-fire{border-radius:18px!important;box-shadow:0 18px 45px rgba(0,0,0,.22)!important}
    .dashboard-wrapper:before{content:'SurgeTechKnow Control Center';position:fixed;right:24px;top:18px;z-index:1001;color:#bae6fd;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.08em;text-transform:uppercase;background:rgba(0,213,255,.08);border:1px solid rgba(0,213,255,.18);padding:8px 12px;border-radius:999px}
    .stat-card{min-height:128px;display:flex;flex-direction:column;justify-content:center}
    .form-control-fire,.btn-fire-primary,.btn-fire-secondary{border-radius:12px!important}
    .tab-pane .card-fire h4{letter-spacing:-.02em}
    @media(max-width:800px){.dashboard-wrapper:before{display:none}.main-content-wrapper{padding:1rem!important;padding-top:4.5rem!important}.stat-card{min-height:auto}.card-fire{padding:1rem!important}}
  

    /* TechKnow Console visual upgrade: dark glass, denim/cyan telemetry, compact analytics */
    :root{--console-cyan:#00d5ff;--console-blue:#1e40af;--console-bg:#020711;--console-panel:rgba(5,14,28,.82);--console-border:rgba(148,163,184,.18)}
    .main-content-wrapper{background:radial-gradient(circle at top left,rgba(0,213,255,.07),transparent 28%),linear-gradient(135deg,#030712,#020711 55%,#00030a)!important;}
    .sidebar-wrapper{background:linear-gradient(180deg,rgba(3,7,18,.98),rgba(2,6,23,.96))!important;border-right:1px solid var(--console-border)!important;}
    .card-fire{background:linear-gradient(135deg,rgba(6,17,34,.88),rgba(2,9,21,.82))!important;border:1px solid var(--console-border)!important;box-shadow:0 10px 30px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.025)!important;}
    .card-fire:hover{border-color:rgba(0,213,255,.42)!important;box-shadow:0 14px 38px rgba(0,213,255,.08)!important;}
    .brand-logo{font-size:2rem;background:linear-gradient(90deg,#00d5ff,#f8fafc);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
    .sidebar-link.active{background:linear-gradient(90deg,rgba(0,213,255,.16),rgba(30,64,175,.12))!important;border-left-color:#00d5ff!important;}
    .stat-number{color:#fff!important;text-shadow:0 0 18px rgba(0,213,255,.12)}
    .truth-mini-card{background:rgba(0,213,255,.06)!important;border-color:rgba(0,213,255,.18)!important}.truth-mini-card .value{color:#38bdf8!important}
    .console-search{background:rgba(2,6,23,.72);border:1px solid var(--console-border);border-radius:14px;height:52px;min-width:340px;display:flex;align-items:center;gap:10px;padding:0 15px;color:#cbd5e1}.console-search input{background:transparent;border:0;outline:0;color:#fff;width:100%}.console-secure{height:52px;border-radius:12px;padding:0 18px;background:rgba(0,213,255,.08);border:1px solid rgba(0,213,255,.22);display:flex;align-items:center;gap:10px;color:#38bdf8;font-weight:800;font-family:'JetBrains Mono',monospace}.console-led{width:13px;height:13px;border-radius:50%;background:#00d5ff;box-shadow:0 0 0 6px rgba(0,213,255,.12),0 0 18px rgba(0,213,255,.7)}
    .metric-value-live.updated{color:#38bdf8!important;text-shadow:0 0 14px rgba(56,189,248,.55)!important}
    @media(max-width:991px){.console-search{display:none}.brand-logo{font-size:1.35rem}.console-secure{height:40px;padding:0 10px;font-size:11px}}

  </style></head><body>
<h1>${title}</h1>${content}
</body></html>`);
      win.document.close();
    }

    function filterBlogMediaAssets(query) {
      query = (query || '').toLowerCase().trim();
      document.querySelectorAll('[data-media-name]').forEach(item => {
        const name = (item.getAttribute('data-media-name') || item.textContent || '').toLowerCase();
        item.style.display = name.includes(query) ? '' : 'none';
      });
    }

    function initializeRichBlogEditor() {
      if (!window.tinymce || !document.getElementById('blogContent')) return;
      if (tinymce.get('blogContent')) return;

      tinymce.init({
        selector: '#blogContent',
        height: 620,
        menubar: 'file edit view insert format tools table help',
        branding: false,
        promotion: false,
        plugins: 'preview importcss searchreplace autolink autosave save directionality code visualblocks visualchars fullscreen image link media table charmap pagebreak nonbreaking anchor insertdatetime advlist lists wordcount help charmap quickbars emoticons codesample',
        toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline strikethrough | forecolor backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | table link image media codesample blockquote | removeformat code fullscreen preview',
        quickbars_selection_toolbar: 'bold italic | quicklink h2 h3 blockquote quicktable',
        quickbars_insert_toolbar: 'quickimage quicktable media codesample',
        image_caption: true,
        automatic_uploads: false,
        convert_urls: false,
        relative_urls: false,
        remove_script_host: false,
        extended_valid_elements: 'video[src|controls|class|preload|playsinline|poster|width|height],source[src|type],iframe[src|width|height|allowfullscreen|loading|referrerpolicy|class],figure[class],figcaption[class]',
        content_style: `
          body { font-family: Inter, Arial, sans-serif; font-size: 17px; line-height: 1.75; color: #111827; padding: 22px; }
          h1,h2,h3,h4 { font-family: Space Grotesk, Inter, sans-serif; line-height: 1.25; }
          img, video, iframe { max-width: 100%; border-radius: 16px; display: block; margin: 18px auto; }
          figure { margin: 24px 0; }
          figcaption { font-size: 13px; color: #64748b; text-align: center; margin-top: 8px; }
          table { border-collapse: collapse; width: 100%; margin: 18px 0; }
          td, th { border: 1px solid #cbd5e1; padding: 10px; }
          blockquote { border-left: 4px solid #00d5ff; padding: 12px 16px; background: #fff7ed; }
          code { background: #f1f5f9; padding: 2px 5px; border-radius: 5px; }
          pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; overflow:auto; }
        `,
        setup: function(editor) {
          editor.on('change keyup undo redo setcontent', function() {
            localStorage.setItem('draft_content', editor.getContent()); markAutosaved(); updateSEOChecklist();
          });
        }
      });
    }

    // Initialize Auto-saving drafts & Hash Router deep linkage
    document.addEventListener("DOMContentLoaded", function() {
      // 1. Hash deep linkage
      var hash = window.location.hash;
      if (hash) {
        var triggerEl = document.querySelector('button[data-bs-target="' + hash + '"]');
        if (triggerEl) {
          var tab = new bootstrap.Tab(triggerEl);
          tab.show();
        }
      }

      // 2. Blog auto-save and restore
      var blogTitleInput = document.getElementById("title");
      var blogContentTextarea = document.getElementById("blogContent");
      
      if (blogTitleInput && blogContentTextarea) {
        // Restore
        if (localStorage.getItem("draft_title")) {
          blogTitleInput.value = localStorage.getItem("draft_title");
        }
        if (localStorage.getItem("draft_content")) {
          blogContentTextarea.value = localStorage.getItem("draft_content");
        }

        initializeRichBlogEditor();
        setTimeout(function(){
          if (window.tinymce && tinymce.get("blogContent") && localStorage.getItem("draft_content")) {
            tinymce.get("blogContent").setContent(localStorage.getItem("draft_content"));
          }
        }, 600);
        setTimeout(updateSEOChecklist, 900);
        
        // Auto-save on edit
        blogTitleInput.addEventListener("input", function() {
          localStorage.setItem("draft_title", blogTitleInput.value); markAutosaved(); updateSEOChecklist();
        });
        blogContentTextarea.addEventListener("input", function() {
          localStorage.setItem("draft_content", blogContentTextarea.value); markAutosaved(); updateSEOChecklist();
        });
        
        // Clear on form submit
        var blogForm = blogTitleInput.closest("form");
        if (blogForm) {
          blogForm.addEventListener("submit", function() {
            if (window.tinymce) { tinymce.triggerSave(); }
            localStorage.removeItem("draft_title");
            localStorage.removeItem("draft_content");
          });
        }
      }

      // 3. Render Neon Line Chart using Chart.js CDN dynamically
      const loadChartScript = () => {
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/chart.js";
        script.onload = () => {
          initializeAnalyticsChart();
        };
        document.body.appendChild(script);
      };
      
      const initializeAnalyticsChart = () => {
        const ctx = document.getElementById("visitorChart");
        if (!ctx) return;
        
        // Fetch raw Jinja daily_visits list
        const rawData = {{ daily_visits|tojson }};
        
        // Fill up to last 15 days if list is short
        let chartLabels = [];
        let chartValues = [];
        
        if (rawData && rawData.length > 0) {
          chartLabels = rawData.map(item => item.date);
          chartValues = rawData.map(item => item.count);
        } else {
          // Empty state placeholder
          chartLabels = ["No Data Logged"];
          chartValues = [0];
        }
        
        const canvasCtx = ctx.getContext("2d");
        const areaGradient = canvasCtx.createLinearGradient(0, 0, 0, 240);
        areaGradient.addColorStop(0, "rgba(16, 185, 129, 0.45)");
        areaGradient.addColorStop(1, "rgba(16, 185, 129, 0.0)");

        new Chart(ctx, {
          type: "line",
          data: {
            labels: chartLabels,
            datasets: [{
              label: "Daily Verified Sessions",
              data: chartValues,
              borderColor: "#00d5ff", // neon emerald
              backgroundColor: areaGradient,
              borderWidth: 2.5,
              pointBackgroundColor: "#00d5ff",
              pointHoverBackgroundColor: "#fff",
              pointHoverBorderColor: "#00d5ff",
              pointHoverBorderWidth: 2,
              pointHoverRadius: 6,
              tension: 0.35,
              fill: true
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false }
            },
            scales: {
              x: {
                grid: { color: "rgba(255, 255, 255, 0.05)" },
                ticks: { color: "#9ca3af", font: { family: "JetBrains Mono", size: 10 } }
              },
              y: {
                grid: { color: "rgba(255, 255, 255, 0.05)" },
                ticks: { color: "#9ca3af", font: { family: "JetBrains Mono", size: 10 }, stepSize: 1 }
              }
            }
          }
        });
      };
      
      // Trigger lazy load
      loadChartScript();

      // 4. URL query param check to load blog editing instantly
      const urlParams = new URLSearchParams(window.location.search);
      const editId = urlParams.get('edit_id');
      if (editId) {
        var blogsBtn = document.querySelector('button[data-bs-target="#blogs-pane"]');
        if (blogsBtn) {
          var tab = new bootstrap.Tab(blogsBtn);
          tab.show();
        }
        // Small delay to allow tab transitions before scrolling
        setTimeout(() => {
          loadBlogForEditing(editId);
        }, 150);
      }
    });

    // Push live analytics to WhatsApp click-to-chat redirector
    function pushTrackerToWhatsApp() {
      const totalSessions = "{{ total_visits }}";
      const timestamp = new Date().toLocaleString();
      const text = `📊 *CENTRAL CONTROL TELEMETRY*:\n============================\n👤 *Owner*: SurgeTechKnow\n🏠 *Brand*: SurgeTechKnow\n🔥 *Traffic State*: ONLINE & SECURE\n📈 *Accumulated Sessions*: \`${totalSessions} visits\`\n⏰ *Export Time*: ${timestamp}\n\n👉 View Admin Suite: \`${window.location.origin}/admin\``;
      
      const query = encodeURIComponent(text);
      window.open(`https://wa.me/254791204587?text=${query}`, '_blank');
    }

    // --- TECHRICH & ACTIVE VISITORS AUXILIARY SCRIPTS ---
    
    // Convert curated item to Blog Draft
    function pushTechRichToDraft(title, content) {
      // 1. Programmatically trigger click on blogs-tab
      const blogsTabBtn = document.getElementById("blogs-tab");
      if (blogsTabBtn) {
        const tab = new bootstrap.Tab(blogsTabBtn);
        tab.show();
      }
      
      // 2. Populate editing fields
      document.getElementById("title").value = "TechRich: " + title;
      document.getElementById("blogContent").value = content;
      
      // 3. Focus and scroll smoothly
      setTimeout(() => {
        const titleInput = document.getElementById("title");
        titleInput.focus();
        titleInput.scrollIntoView({ behavior: "smooth", block: "center" });
        showToastAlert("🚀 Adapted TechRich article template! Adjust content, add your keywords, and hit 'Publish' to push live on your blog.");
      }, 200);
    }
    
    // --- DYNAMIC TECHRICH CLOUD CABINET SYSTEM & EDITING ENGINE ---
    let techRichDocs = [];
    let activeTrTab = "all";
    let activeTrDocId = null;
    let isTrWorkspaceExpanded = false;

    function toggleTrWorkspaceExpand() {
      const browserCol = document.getElementById("tr-browser-col");
      const workspaceCol = document.getElementById("tr-workspace-col");
      const icon = document.getElementById("tr-expand-icon");
      const text = document.getElementById("tr-expand-text");
      const pdfIframe = document.getElementById("tr-pdf-iframe");

      isTrWorkspaceExpanded = !isTrWorkspaceExpanded;
      if (isTrWorkspaceExpanded) {
        if (browserCol) browserCol.classList.add("d-none");
        if (workspaceCol) {
          workspaceCol.classList.remove("col-lg-7");
          workspaceCol.classList.add("col-lg-12");
        }
        if (icon) {
          icon.classList.remove("bi-arrows-angle-expand");
          icon.classList.add("bi-arrows-angle-contract");
        }
        if (text) text.innerText = "Normal View";
        if (pdfIframe) {
          pdfIframe.style.minHeight = "1350px";
        }
      } else {
        if (browserCol) browserCol.classList.remove("d-none");
        if (workspaceCol) {
          workspaceCol.classList.remove("col-lg-12");
          workspaceCol.classList.add("col-lg-7");
        }
        if (icon) {
          icon.classList.remove("bi-arrows-angle-contract");
          icon.classList.add("bi-arrows-angle-expand");
        }
        if (text) text.innerText = "Expand Reader";
        if (pdfIframe) {
          pdfIframe.style.minHeight = "950px";
        }
      }
    }

    function loadTechRichDocs() {
      fetch("/admin/techrich/list")
        .then(res => res.json())
        .then(data => {
          if (data.status === "success" || data.docs) {
            techRichDocs = data.docs || [];
            drawTechRichDocs();
          }
        })
        .catch(err => {
          console.error("Failed to load TechRich index:", err);
          document.getElementById("tr-browser-list").innerHTML = `
            <div class="p-4 text-center text-danger font-mono text-xs">
              <i class="bi bi-exclamation-triangle d-block mb-2"></i>
              Failed to connect to digital cabinet.
            </div>
          `;
        });
    }

    function filterTechRichByTab(type) {
      const tabs = ["all", "pdf", "word", "note"];
      tabs.forEach(t => {
        document.getElementById("tr-pil-" + t).classList.remove("active");
      });
      document.getElementById("tr-pil-" + type).classList.add("active");
      activeTrTab = type;
      drawTechRichDocs();
    }

    function drawTechRichDocs() {
      const query = document.getElementById("tr-search").value.toLowerCase().trim();
      const listContainer = document.getElementById("tr-browser-list");
      listContainer.innerHTML = "";

      const filtered = techRichDocs.filter(d => {
        const matchesTab = (activeTrTab === "all" || d.doc_type === activeTrTab);
        const matchesQuery = (!query || d.title.toLowerCase().includes(query) || (d.file_name && d.file_name.toLowerCase().includes(query)));
        return (matchesTab && matchesQuery);
      });

      if (filtered.length === 0) {
        listContainer.innerHTML = `
          <div class="p-4 text-center text-muted font-mono text-xs">
            <i class="bi bi-folder-x d-block fs-4 mb-1.5 opacity-50"></i>
            No matching documents found.
          </div>
        `;
        return;
      }

      filtered.forEach(d => {
        let iconHtml = '<i class="bi bi-file-earmark-text text-muted"></i>';
        if (d.doc_type === 'pdf') {
          iconHtml = '<i class="bi bi-file-earmark-pdf-fill text-danger fs-5"></i>';
        } else if (d.doc_type === 'word') {
          iconHtml = '<i class="bi bi-file-earmark-word-fill text-info fs-5"></i>';
        } else if (d.doc_type === 'note') {
          iconHtml = '<i class="bi bi-file-earmark-richtext-fill text-warning fs-5"></i>';
        }

        const activeClass = (activeTrDocId === d.id) ? "style='background: rgba(251, 191, 36, 0.15); border-left: 3px solid #fbbf24 !important;'" : "";
        const item = document.createElement("button");
        item.type = "button";
        item.className = "list-group-item list-group-item-action bg-transparent border-0 d-flex align-items-center justify-content-between p-3 transition-all";
        item.style.borderBottom = "1px solid rgba(255, 255, 255, 0.05)";
        if (activeClass) item.style.cssText += "background: rgba(251, 191, 36, 0.11); border-left: 4px solid #fbbf24 !important;";

        item.innerHTML = `
          <div class="d-flex align-items-center gap-3 text-start truncate flex-grow-1" onclick="openTechRichDoc(${d.id})">
            <div>${iconHtml}</div>
            <div class="truncate">
              <span class="text-white text-xs d-block font-semibold truncate" style="max-width: 220px;">${d.title}</span>
              <span class="text-muted text-xxs block font-mono">${d.doc_type.toUpperCase()} • ${d.file_name || 'Virtual Note'}</span>
            </div>
          </div>
          <div class="d-flex align-items-center gap-2">
            <a href="/admin/techrich/download/${d.id}" target="_blank" class="btn btn-xs btn-link p-1 text-muted hover:text-white" title="Download original file"><i class="bi bi-download"></i></a>
            <button onclick="deleteTechRichDoc(${d.id}, event)" class="btn btn-xs btn-link p-1 text-muted hover:text-danger" title="Purge document"><i class="bi bi-trash3-fill"></i></button>
          </div>
        `;
        listContainer.appendChild(item);
      });
    }

    function openTechRichDoc(id) {
      activeTrDocId = id;
      drawTechRichDocs(); // Refresh active lists backgrounds

      const textMeta = document.getElementById("tr-active-meta");
      const textTitle = document.getElementById("tr-active-title");
      const actionToolbar = document.getElementById("tr-active-actions");
      const canvas = document.getElementById("tr-editor-canvas");

      canvas.innerHTML = `
        <div class="m-auto text-center font-mono text-xs text-muted">
          <div class="spinner-border spinner-border-sm text-warning mb-2"></div>
          <div>Streaming secure segment logs...</div>
        </div>
      `;

      fetch(`/admin/techrich/view/${id}`)
        .then(res => res.json())
        .catch(err => {
          // Fallback if binary file view
          return { id: id };
        })
        .then(doc => {
          // Lookup active reference metadata from memory
          const cached = techRichDocs.find(d => d.id === id);
          if (!cached) return;

          textTitle.innerText = cached.title;
          textMeta.innerHTML = `<span class="badge bg-warning/15 text-warning font-mono me-1.5">${cached.doc_type.toUpperCase()}</span> ${cached.file_name || 'Direct Markdown Note'}`;

          // Format toolbar based on doc capabilities
          let toolbarHtml = `
            <a href="/admin/techrich/download/${id}" target="_blank" class="btn btn-xs btn-neutral-900 border border-secondary/15 py-1 px-3.5 rounded text-white text-xs d-flex align-items-center gap-1.5 font-mono">
              <i class="bi bi-download text-warning"></i> Download Original
            </a>
          `;

          if (cached.doc_type === "pdf") {
            toolbarHtml += `
              <button onclick="toggleTrWorkspaceExpand()" class="btn btn-xs btn-outline-warning py-1 px-3 rounded text-warning text-xs d-flex align-items-center gap-1.5 font-mono">
                <i id="tr-expand-icon" class="bi ${isTrWorkspaceExpanded ? 'bi-arrows-angle-contract' : 'bi-arrows-angle-expand'}"></i> 
                <span id="tr-expand-text">${isTrWorkspaceExpanded ? 'Normal View' : 'Expand Reader'}</span>
              </button>
            `;
          }

          if (cached.doc_type === "note" || cached.doc_type === "word") {
            toolbarHtml += `
              <button onclick="printTechRichNote()" class="btn btn-xs btn-outline-warning py-1 px-3 rounded text-warning text-xs d-flex align-items-center gap-1.5 font-mono">
                <i class="bi bi-file-pdf-fill"></i> Download PDF
              </button>
              <button onclick="adaptActiveToBlog()" class="btn btn-xs btn-warning py-1 px-3.5 rounded text-black fw-bold text-xs d-flex align-items-center gap-1.5 font-mono">
                <i class="bi bi-rocket-takeoff-fill"></i> Push Draft Live
              </button>
            `;
          }

          actionToolbar.innerHTML = toolbarHtml;

          // Render canvas view
          if (cached.doc_type === "pdf") {
            const currentHeight = isTrWorkspaceExpanded ? '1350px' : '950px';
            canvas.innerHTML = `
              <div class="embed-responsive h-100 flex-grow-1 border border-secondary/10 rounded-3">
                <iframe id="tr-pdf-iframe" class="embed-responsive-item w-100 h-100 rounded" src="/admin/techrich/view/${id}" style="border:none; min-height: ${currentHeight}; background: #fff; transition: min-height 0.25s ease;"></iframe>
              </div>
            `;
          } else {
            // Edit model for Note or Word docs
            const defaultText = doc.content || doc.text_content || "# " + cached.title + "\n\nStart typing configuration details or staff procedures here...";
            canvas.innerHTML = `
              <div class="d-flex flex-column h-100 flex-grow-1 gap-2.5">
                <div class="text-xs text-muted font-mono"><i class="bi bi-info-circle text-warning"></i> DIRECTLY EDIT THREAD: Add any staff instructions or technical questions and hit Save.</div>
                
                <div class="flex-grow-1 d-flex flex-column">
                  <input type="text" id="tr-edit-title-input" class="form-control form-control-fire mb-2 text-sm text-white fw-bold font-sans" style="background:#090d16;" value="${cached.title}" placeholder="Document title...">
                  <textarea id="tr-edit-textarea" class="form-control form-control-fire flex-grow-1 font-mono text-sm text-white p-3 border-secondary/10 rounded-3" style="background: rgba(8, 11, 20, 0.9); min-height:380px; resize:none; line-height: 1.6;" placeholder="Type markdown note text content here...">${defaultText}</textarea>
                </div>

                <div class="d-flex align-items-center justify-content-between mt-2 pt-2 border-top border-secondary/10">
                  <span class="text-muted text-xxs font-mono" id="tr-save-status">Ready to save modifications</span>
                  <button onclick="saveActiveTrDocChanges()" class="btn btn-xs btn-success text-black py-1.5 px-4 font-mono fw-bold rounded d-flex align-items-center gap-1.5">
                    <i class="bi bi-check-circle-fill"></i> Save workspace changes
                  </button>
                </div>
              </div>
            `;
          }
        });
    }

    function saveActiveTrDocChanges() {
      if (!activeTrDocId) return;
      const title = document.getElementById("tr-edit-title-input").value.trim();
      const content = document.getElementById("tr-edit-textarea").value;
      const statusSpan = document.getElementById("tr-save-status");
      
      statusSpan.innerHTML = "<span class='text-warning animate-pulse'><i class='bi bi-arrow-repeat spin'></i> Syncing records on remote node...</span>";

      const formData = new FormData();
      formData.append("title", title);
      formData.append("content", content);

      fetch(`/admin/techrich/update/${activeTrDocId}`, {
        method: "POST",
        body: formData
      })
      .then(res => res.json())
      .then(data => {
        if (data.status === "success") {
          statusSpan.innerHTML = "<span class='text-info'><i class='bi bi-check2-all'></i> Changes saved live successfully!</span>";
          loadTechRichDocs();
          setTimeout(() => {
            statusSpan.innerText = "Ready to save modifications";
          }, 3500);
        } else {
          statusSpan.innerHTML = "<span class='text-danger'>Error: " + (data.error || "failed") + "</span>";
        }
      })
      .catch(err => {
        console.error(err);
        statusSpan.innerHTML = "<span class='text-danger'>Sync error</span>";
      });
    }

    function createNewTechRichNote() {
      const modalTitle = prompt("Enter a title for your new Technow note documentation:", "CCNA Subnet Allocation Protocol");
      if (!modalTitle) return;

      const formData = new FormData();
      formData.append("title", modalTitle);
      formData.append("content", "# " + modalTitle + "\n\n### Direct Support Desk Action Items\n- \n- \n\n### Dynamic CCNA Configurations\n```\n! Run core backup variables\n```");

      fetch("/admin/techrich/create", {
        method: "POST",
        body: formData
      })
      .then(res => res.json())
      .then(data => {
        if (data.status === "success" && data.id) {
          showToastAlert("🚀 Created new document draft inside local TechRich segment!");
          loadTechRichDocs();
          setTimeout(() => {
            openTechRichDoc(data.id);
          }, 400);
        }
      })
      .catch(err => console.error(err));
    }

    function uploadTechRichFile() {
      const fileInput = document.getElementById("tr-file-input");
      if (!fileInput.files || fileInput.files.length === 0) return;

      const file = fileInput.files[0];
      const formData = new FormData();
      formData.append("file", file);

      showToastAlert("⏳ Parsing and encrypting file transmission block...");

      fetch("/admin/techrich/upload", {
        method: "POST",
        body: formData
      })
      .then(res => res.json())
      .then(data => {
        fileInput.value = ""; // clear
        if (data.status === "success") {
          showToastAlert("🚀 Document committed successfully to secure TechRich cloud storage node!");
          loadTechRichDocs();
          if (data.id) {
            setTimeout(() => {
              openTechRichDoc(data.id);
            }, 500);
          }
        } else {
          showToastAlert("⚠️ Transmission abort: " + (data.error || "validation failure"));
        }
      })
      .catch(err => {
        console.error(err);
        showToastAlert("⚠️ Network block error during upload.");
      });
    }

    function deleteTechRichDoc(id, event) {
      if (event) event.stopPropagation();
      const cached = techRichDocs.find(d => d.id === id);
      const title = cached ? cached.title : "this file";
      
      if (!confirm(`Are you absolutely sure you want to permanently delete the document "${title}" from the TechRich Cabinet?`)) {
        return;
      }

      fetch(`/admin/techrich/delete/${id}`, { method: "POST" })
        .then(res => res.json())
        .then(data => {
          if (data.status === "success") {
            showToastAlert("🗑️ Document purged successfully!");
            if (activeTrDocId === id) {
              activeTrDocId = null;
              document.getElementById("tr-active-title").innerText = "Workspace Sandbox";
              document.getElementById("tr-active-meta").innerText = "Select a document node from the directory browser to open";
              document.getElementById("tr-active-actions").innerHTML = "";
              document.getElementById("tr-editor-canvas").innerHTML = `
                <div class="m-auto text-center text-muted col-10 font-sans">
                  <i class="bi bi-terminal-split text-warning" style="font-size: 3.5rem; opacity: 0.15; display:block; margin-bottom: 0.5rem;"></i>
                  <h6 class="text-white-50 fw-bold">ACTIVE WORKSPACE READOUT</h6>
                  <p class="text-xs text-muted leading-relaxed">Double click any document node from SurgeTechKnow's left browser cabinet to inspect CCNA configuration guidelines, stream reference PDFs, or update ICT support staff routines directly without download/re-upload cycles.</p>
                </div>
              `;
            }
            loadTechRichDocs();
          }
        })
        .catch(err => console.error(err));
    }

    function adaptActiveToBlog() {
      if (!activeTrDocId) return;
      const titleInput = document.getElementById("tr-edit-title-input");
      const textInput = document.getElementById("tr-edit-textarea");
      if (!titleInput || !textInput) return;

      pushTechRichToDraft(titleInput.value, textInput.value);
    }

    function printTechRichNote() {
      const textInput = document.getElementById("tr-edit-textarea");
      const titleInput = document.getElementById("tr-edit-title-input");
      if (!textInput || !titleInput) return;

      const printWin = window.open('', '_blank');
      if (!printWin) {
        alert("Please enable pop-ups to generate and save PDF documents natively.");
        return;
      }

      const contentHtml = marked.parse(textInput.value);

      printWin.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>${titleInput.value}</title>
          <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
          <style>
            body { font-family: 'Inter', system-ui, sans-serif; padding: 40px; color: #1e293b; background: #fff; }
            h1 { font-weight: 800; border-bottom: 2px solid #1e40af; padding-bottom: 12px; margin-bottom: 20px; font-size: 2rem; }
            pre { background: #f1f5f9; padding: 15px; border-radius: 6px; font-family: monospace; font-size: 0.85rem; border: 1px solid #cbd5e1; }
            p, li { line-height: 1.6; }
            header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; padding-bottom: 10px; color: #64748b; font-size: 0.75rem; font-family: monospace; }
        

    /* Dashboard truth upgrades */
    .truth-mini-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .truth-mini-card {
      background: rgba(16,185,129,0.055);
      border: 1px solid rgba(16,185,129,0.13);
      border-radius: 10px;
      padding: 8px;
      text-align: center;
    }
    .truth-mini-card .label {
      display: block;
      color: var(--text-muted);
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .truth-mini-card .value {
      color: #00d5ff;
      font-weight: 800;
      font-family: 'Space Grotesk', sans-serif;
      font-size: 1rem;
    }
    .health-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,.06);
      font-size: .78rem;
    }
    .health-row:last-child { border-bottom: 0; }
    .seo-check-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .seo-check-item {
      border: 1px solid rgba(255,255,255,.08);
      background: rgba(255,255,255,.025);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 11px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .seo-check-item.good { border-color: rgba(34,197,94,.24); color: #bbf7d0; background: rgba(34,197,94,.055); }
    .seo-check-item.warn { border-color: rgba(245,158,11,.25); color: #fde68a; background: rgba(245,158,11,.055); }
    .seo-check-item.bad { border-color: rgba(239,68,68,.25); color: #fecaca; background: rgba(239,68,68,.055); }
    .autosave-status {
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      color: #86efac;
    }
    .media-filter-input {
      background: rgba(0,0,0,.25) !important;
      border: 1px solid rgba(255,255,255,.09) !important;
      color: #fff !important;
      border-radius: 10px !important;
    }

  
    /* ADMIN POLISH V4 */
    .card-fire{border-radius:18px!important;box-shadow:0 18px 45px rgba(0,0,0,.22)!important}
    .dashboard-wrapper:before{content:'SurgeTechKnow Control Center';position:fixed;right:24px;top:18px;z-index:1001;color:#bae6fd;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.08em;text-transform:uppercase;background:rgba(0,213,255,.08);border:1px solid rgba(0,213,255,.18);padding:8px 12px;border-radius:999px}
    .stat-card{min-height:128px;display:flex;flex-direction:column;justify-content:center}
    .form-control-fire,.btn-fire-primary,.btn-fire-secondary{border-radius:12px!important}
    .tab-pane .card-fire h4{letter-spacing:-.02em}
    @media(max-width:800px){.dashboard-wrapper:before{display:none}.main-content-wrapper{padding:1rem!important;padding-top:4.5rem!important}.stat-card{min-height:auto}.card-fire{padding:1rem!important}}
  

    /* TechKnow Console visual upgrade: dark glass, denim/cyan telemetry, compact analytics */
    :root{--console-cyan:#00d5ff;--console-blue:#1e40af;--console-bg:#020711;--console-panel:rgba(5,14,28,.82);--console-border:rgba(148,163,184,.18)}
    .main-content-wrapper{background:radial-gradient(circle at top left,rgba(0,213,255,.07),transparent 28%),linear-gradient(135deg,#030712,#020711 55%,#00030a)!important;}
    .sidebar-wrapper{background:linear-gradient(180deg,rgba(3,7,18,.98),rgba(2,6,23,.96))!important;border-right:1px solid var(--console-border)!important;}
    .card-fire{background:linear-gradient(135deg,rgba(6,17,34,.88),rgba(2,9,21,.82))!important;border:1px solid var(--console-border)!important;box-shadow:0 10px 30px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.025)!important;}
    .card-fire:hover{border-color:rgba(0,213,255,.42)!important;box-shadow:0 14px 38px rgba(0,213,255,.08)!important;}
    .brand-logo{font-size:2rem;background:linear-gradient(90deg,#00d5ff,#f8fafc);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
    .sidebar-link.active{background:linear-gradient(90deg,rgba(0,213,255,.16),rgba(30,64,175,.12))!important;border-left-color:#00d5ff!important;}
    .stat-number{color:#fff!important;text-shadow:0 0 18px rgba(0,213,255,.12)}
    .truth-mini-card{background:rgba(0,213,255,.06)!important;border-color:rgba(0,213,255,.18)!important}.truth-mini-card .value{color:#38bdf8!important}
    .console-search{background:rgba(2,6,23,.72);border:1px solid var(--console-border);border-radius:14px;height:52px;min-width:340px;display:flex;align-items:center;gap:10px;padding:0 15px;color:#cbd5e1}.console-search input{background:transparent;border:0;outline:0;color:#fff;width:100%}.console-secure{height:52px;border-radius:12px;padding:0 18px;background:rgba(0,213,255,.08);border:1px solid rgba(0,213,255,.22);display:flex;align-items:center;gap:10px;color:#38bdf8;font-weight:800;font-family:'JetBrains Mono',monospace}.console-led{width:13px;height:13px;border-radius:50%;background:#00d5ff;box-shadow:0 0 0 6px rgba(0,213,255,.12),0 0 18px rgba(0,213,255,.7)}
    .metric-value-live.updated{color:#38bdf8!important;text-shadow:0 0 14px rgba(56,189,248,.55)!important}
    @media(max-width:991px){.console-search{display:none}.brand-logo{font-size:1.35rem}.console-secure{height:40px;padding:0 10px;font-size:11px}}

  </style>
        </head>
        <body>
          <header>
            <div>SurgeTechKnow TECHRICH INTERNAL DOCUMENT SECURITY MANUAL</div>
            <div>COMPILED AT: ${new Date().toLocaleString()}</div>
          </header>
          <h1>${titleInput.value}</h1>
          <div class="content">${contentHtml}</div>
          <script>
            window.onload = function() {
              window.print();
              setTimeout(function() { window.close(); }, 1500);
            }
          <\/script>
</body>
        </html>
      `);
      printWin.document.close();
    }

    // Attach load trigger on tab click
    document.addEventListener("DOMContentLoaded", function() {
      const techrichTabBtn = document.getElementById("techrich-tab");
      if (techrichTabBtn) {
        techrichTabBtn.addEventListener("shown.bs.tab", function() {
          loadTechRichDocs();
        });
      }
      
      // Seed first index draft
      setTimeout(() => {
        if (techRichDocs.length === 0 && document.getElementById("techrich-pane").classList.contains("active")) {
          loadTechRichDocs();
        }
      }, 1000);
    });


    function flashMetricUpdate(el) {
      if (!el) return;
      el.classList.add('updated');
      setTimeout(() => el.classList.remove('updated'), 450);
    }

    function updateVerifiedVisitorsPanel(metrics) {
      if (!metrics) return;
      const pairs = {
        'verified-total': metrics.total,
        'verified-real': metrics.real,
        'verified-active': metrics.engaged,
        'verified-bots': metrics.bot,
        'verified-suspicious': metrics.suspicious,
        'verified-returning': metrics.returning,
        'verified-avg-read': metrics.avg_read_time,
        'verified-bounce': (metrics.bounce_rate || 0) + '%',
        'verified-scroll': (metrics.scroll_completion || 0) + '%',
        'verified-today': metrics.today || 0,
        'verified-seven-days': metrics.seven_days || 0,
        'verified-all-time': metrics.all_time || metrics.total || 0
      };
      Object.entries(pairs).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el && String(el.textContent).trim() !== String(value)) {
          el.textContent = value;
          flashMetricUpdate(el);
        }
      });
    }


    function updateTrackingHealth(health) {
      if (!health) return;
      const status = document.getElementById('tracking-health-status');
      const lastSeen = document.getElementById('tracking-last-seen');
      const lastBot = document.getElementById('tracking-last-bot');
      const endpoint = document.getElementById('tracking-endpoint');
      const msg = document.getElementById('tracking-health-message');
      if (status) {
        status.textContent = (health.tracking_js_status || 'waiting').toUpperCase();
        status.className = 'badge border ' + (health.tracking_js_status === 'active' ? 'bg-info/10 text-info border-info/20' : health.tracking_js_status === 'error' ? 'bg-danger/10 text-danger border-danger/20' : 'bg-warning/10 text-warning border-warning/20');
      }
      if (lastSeen) lastSeen.textContent = health.last_verified_seen ? new Date(health.last_verified_seen).toLocaleString() : 'Waiting...';
      if (lastBot) lastBot.textContent = health.last_bot_seen ? new Date(health.last_bot_seen).toLocaleString() : 'None yet';
      if (endpoint) endpoint.textContent = health.track_endpoint || '/api/track_visit';
      if (msg) msg.textContent = health.message || 'Tracking status loaded.';
    }

    function updateTopLivePages(pages) {
      const holder = document.getElementById('top-live-pages');
      if (!holder) return;
      if (!pages || pages.length === 0) {
        holder.innerHTML = '<div class="text-muted text-mono small">No active verified readers right now.</div>';
        return;
      }
      holder.innerHTML = pages.map(p => `
        <div class="d-flex justify-content-between align-items-center p-2 rounded border border-info/10" style="background:rgba(14,165,233,.045);">
          <span class="text-truncate text-white small" title="${p.path}"><i class="bi bi-link-45deg text-info me-1"></i>${p.path}</span>
          <span class="badge bg-info text-black">${p.active_readers}</span>
        </div>
      `).join('');
    }

    function resetVerifiedAnalytics() {
      const confirmText = prompt('Type RESET to clear verified sessions, bot logs, and read sessions.');
      if (confirmText !== 'RESET') return;
      fetch('/api/admin/reset_analytics', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({confirm:'RESET'})
      }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
          showToastAlert('Verified analytics reset successfully.');
          pollVerifiedVisitorMetrics();
          pollRealTimeMetrics();
        } else {
          alert(data.message || 'Reset failed.');
        }
      }).catch(() => alert('Reset endpoint offline.'));
    }

    function pollVerifiedVisitorMetrics() {
      fetch('/api/admin/verified_visitors')
        .then(res => res.json())
        .then(data => {
          if (data.status === 'success') { updateVerifiedVisitorsPanel(data.metrics); updateTrackingHealth(data.health); updateTopLivePages(data.top_live_pages); }
        })
        .catch(err => console.error('Verified visitor metrics offline:', err));
    }

    // Global alert tracking for thresholds
    let notifiedThresholds = new Set();

    // Polling function for real-time article engagement stats and active user sessions (100% REAL!)
    function pollRealTimeMetrics() {
      fetch("/api/admin/article_stats")
        .then(res => res.json())
        .then(data => {
          if (data.status === "success") {
            if (data.visitor_metrics) updateVerifiedVisitorsPanel(data.visitor_metrics);
            if (data.tracking_health) updateTrackingHealth(data.tracking_health);
            if (data.recent_pages) updateTopLivePages(data.recent_pages);
            // 1. Update active sessions count
            const count = Number(data.active_users || 0);
            document.getElementById("active-user-count").innerText = count;
            const progressPercent = Math.min(100, Math.max(8, (count / 65) * 100));
            document.getElementById("active-progress").style.width = progressPercent + "%";
            
            // Trigger alerts if milestones reached
            checkActiveUsersAlerts(count);

            // 2. Update dynamic Cards B and C (Popular Essay & Dominant Category)
            const dominantCategoryHeader = document.getElementById("tr-dominant-category-header");
            if (dominantCategoryHeader) {
              dominantCategoryHeader.innerText = data.dominant_category || "Technology";
            }

            // Find the most popular essay
            if (data.articles && data.articles.length > 0) {
              const bestArticle = data.articles[0]; // ordered desc by views primary
              const mostViewedTitle = document.getElementById("tr-most-viewed-title");
              const mostViewedViews = document.getElementById("tr-most-viewed-views");
              const mostViewedLink = document.getElementById("tr-most-viewed-link");

              if (mostViewedTitle) mostViewedTitle.innerText = bestArticle.title;
              if (mostViewedViews) mostViewedViews.innerText = bestArticle.views;
              if (mostViewedLink) mostViewedLink.setAttribute("href", "/blog/" + bestArticle.slug);
            }

            // 3. Update the gorgeous live metrics table
            const tbody = document.getElementById("realtime-blog-stats-body");
            if (tbody && data.articles) {
              if (data.articles.length === 0) {
                tbody.innerHTML = `
                  <tr>
                    <td colspan="7" class="text-center py-4 text-muted font-mono" style="background:transparent; border:none;">No articles written yet.</td>
                  </tr>
                `;
              } else {
                let html = "";
                data.articles.forEach(art => {
                  // Format read time beautifully
                  let formattedDuration = "-";
                  if (art.total_read_time > 0) {
                    const mins = Math.floor(art.total_read_time / 60);
                    const secs = art.total_read_time % 60;
                    formattedDuration = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
                  }

                  let formattedAvg = "-";
                  if (art.avg_read_time_seconds > 0) {
                    const avgMins = Math.floor(art.avg_read_time_seconds / 60);
                    const avgSecs = art.avg_read_time_seconds % 60;
                    formattedAvg = avgMins > 0 ? `${avgMins}m ${avgSecs}s` : `${avgSecs}s`;
                  }

                  html += `
                    <tr class="align-middle border-bottom border-secondary/5 font-sans hover:bg-white/5 transition-colors">
                      <td class="py-3 text-white font-medium" style="background: transparent; border: none; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <a href="/blog/${art.slug}" target="_blank" class="text-white hover:text-warning text-decoration-none">
                          <i class="bi bi-file-text text-warning/70 me-1.5"></i> ${art.title}
                        </a>
                      </td>
                      <td style="background: transparent; border: none;">
                        <span class="badge bg-secondary/20 text-white-50 font-mono" style="font-size:0.65rem; border: 1px solid rgba(255,255,255,0.05);">${art.category}</span>
                      </td>
                      <td class="text-center font-mono text-warning font-semibold" style="background: transparent; border: none;">
                        <i class="bi bi-eye"></i> ${art.verified_views || art.views || 0} verified
                      </td>
                      <td class="text-center font-mono text-muted" style="background: transparent; border: none;">
                        <i class="bi bi-clock"></i> ${formattedDuration}
                      </td>
                      <td class="text-center font-mono text-info font-medium" style="background: transparent; border: none;">
                        <i class="bi bi-stopwatch text-info/70"></i> ${formattedAvg}
                      </td>
                      <td class="text-center font-mono text-info" style="background: transparent; border: none;">
                        ${art.avg_scroll_depth || 0}%
                      </td>
                      <td class="text-end font-mono text-warning" style="background: transparent; border: none;">
                        ${art.bounce_rate || 0}%
                      </td>
                    </tr>
                  `;
                });
                tbody.innerHTML = html;
              }
            }
          }
        })
        .catch(err => console.error("Real-time telemetry stats offline:", err));
    }

    function checkActiveUsersAlerts(count) {
      const alertThresholds = [10, 20, 30, 40, 50, 60];
      
      for (let t of alertThresholds) {
        if (count >= t && !notifiedThresholds.has(t)) {
          notifiedThresholds.add(t);
          triggerAutomaticWhatsAppPush(t, count);
          break; // alert on highest reached newly-triggered milestone
        }
      }
    }

    function triggerAutomaticWhatsAppPush(threshold, count) {
      // 1. Generate futuristic sound chime
      try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx) {
          const oscSelected = audioCtx.createOscillator();
          const gainNode = audioCtx.createGain();
          oscSelected.connect(gainNode);
          gainNode.connect(audioCtx.destination);
          
          oscSelected.frequency.setValueAtTime(680, audioCtx.currentTime); // High cyber ping
          oscSelected.type = "sine";
          gainNode.gain.setValueAtTime(0.35, audioCtx.currentTime);
          gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.8);
          
          oscSelected.start();
          oscSelected.stop(audioCtx.currentTime + 0.8);
        }
      } catch (e) {
        console.warn("Audio Context deactivated or blocked by client permissions.");
      }
      
      // 2. Draft WhatsApp telemetry string
      const text = `🚨 *SurgeTechKnow.dev Live Traffic Alert*:\n============================\n👤 *Owner*: SurgeTechKnow\n🔥 *Traffic Threshold Exceeded*: \`${threshold}+ Active Users\`\n📈 *Current Metric*: \`${count} verified active readers\`\n⚡ *System Alert Action*: Automatic real-time telemetry socket dispatch.\n\n👉 Review Admin suite: ${window.location.origin}/admin`;
      const waUrl = "https://wa.me/254791204587?text=" + encodeURIComponent(text);
      
      // 3. Automatically execute redirect open
      const popup = window.open(waUrl, "_blank");
      if (!popup) {
        // Fallback: Reveal floating elegant notification action button
        showToastActionAlert(`🚨 REALTIME ALERT: Active users reached ${count}! Popup was blocked. Click here to WhatsApp SurgeTechKnow.`, waUrl);
      } else {
        showToastAlert(`🚀 Automated Traffic Alert dispatched to WhatsApp for ${threshold} active users!`);
      }
    }

    // Toast alert utility system
    function showToastAlert(message) {
      // Create element dynamically
      const toast = document.createElement("div");
      toast.className = "position-fixed bottom-0 start-0 m-4 p-3 rounded shadow text-white border border-info/30 font-sans";
      toast.style.background = "rgba(11, 21, 15, 0.95)";
      toast.style.zIndex = "4000";
      toast.style.maxWidth = "350px";
      toast.style.animation = "slideUp 0.35s ease-out forwards";
      toast.innerHTML = `<div class="d-flex align-items-center gap-2"><i class="bi bi-shield-fill-check text-info fs-5"></i><span style="font-size:0.85rem;">${message}</span></div>`;
      
      document.body.appendChild(toast);
      setTimeout(() => {
        toast.style.animation = "slideDown 0.35s ease-in forwards";
        setTimeout(() => toast.remove(), 400);
      }, 4500);
    }

    function showToastActionAlert(message, url) {
      const toast = document.createElement("div");
      toast.className = "position-fixed bottom-0 start-0 m-4 p-3 rounded shadow text-white border border-warning/30 font-sans";
      toast.style.background = "rgba(22, 18, 10, 0.95)";
      toast.style.zIndex = "4000";
      toast.style.maxWidth = "350px";
      toast.style.animation = "slideUp 0.35s ease-out forwards";
      toast.innerHTML = `
        <div class="d-flex flex-column gap-2">
          <div class="d-flex align-items-center gap-2">
            <i class="bi bi-exclamation-triangle-fill text-warning fs-5"></i>
            <span style="font-size:0.85rem;">${message}</span>
          </div>
          <a href="${url}" target="_blank" class="btn btn-warning btn-xs py-1 text-black font-semibold text-center rounded" style="font-size:0.75rem;">
            <i class="bi bi-whatsapp"></i> Launch WhatsApp Alert
          </a>
        </div>
      `;
      
      document.body.appendChild(toast);
      // Keep on screen longer since action is required
      setTimeout(() => {
        toast.style.animation = "slideDown 0.35s ease-in forwards";
        setTimeout(() => toast.remove(), 400);
      }, 10000);
    }

    // Interactive Left Sidebar Tab Selectors & Mobile Toggler Handler
    function selectTab(paneId) {
      // Find the bootstrap trigger button in our hidden UL deck
      const targetBtn = document.querySelector(`button[data-bs-target="${paneId}"]`);
      if (targetBtn) {
        const tabObj = new bootstrap.Tab(targetBtn);
        tabObj.show();
      }
      
      // Keep Left Sidebar state in visual sync
      document.querySelectorAll('.sidebar-link').forEach(link => {
        link.classList.remove('active');
      });
      const currentActiveLink = document.querySelector(`.sidebar-link[onclick*="${paneId}"]`);
      if (currentActiveLink) {
        currentActiveLink.classList.add('active');
      }
      
      // Auto-dismiss sidebar panel on mobile views
      const sidebarElement = document.querySelector('.sidebar-wrapper');
      if (sidebarElement && sidebarElement.classList.contains('show')) {
        toggleSidebar();
      }
    }

    function toggleSidebar() {
      const sidebarElement = document.querySelector('.sidebar-wrapper');
      if (sidebarElement) {
        sidebarElement.classList.toggle('show');
        
        let overlayElement = document.querySelector('.sidebar-overlay');
        if (!overlayElement) {
          overlayElement = document.createElement('div');
          overlayElement.className = 'sidebar-overlay';
          overlayElement.onclick = toggleSidebar;
          document.body.appendChild(overlayElement);
        } else {
          overlayElement.remove();
        }
      }
    }

    // Global CSS CSS keys inject for keyframes
    const styleSheet = document.createElement("style");
    styleSheet.innerText = `
      @keyframes slideUp {
        from { transform: translateY(100px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
      }
      @keyframes slideDown {
        from { transform: translateY(0); opacity: 1; }
        to { transform: translateY(100px); opacity: 0; }
      }
      .btn-xs {
        padding: 2px 8px;
        font-size: 0.75rem;
      }
    `;
    document.head.appendChild(styleSheet);

    // Initial setups
    pollRealTimeMetrics();
    pollVerifiedVisitorMetrics();
    setInterval(pollRealTimeMetrics, 8000);
    setInterval(pollVerifiedVisitorMetrics, 12000); // Verified visitor metrics stream polling every 12 seconds
  