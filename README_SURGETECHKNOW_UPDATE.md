# SurgeTechKnow Professional Update

This package keeps the existing Flask/GitHub structure and updates the look to a SurgeTechKnow / news-style layout.

Preserved:
- app.py as the single Flask backend
- data.py database layer
- templates/ structure
- static/ paths
- media routes
- admin route/functionality
- AdSense, ads.txt, Analytics and SEO tags

Updated:
- index.html content-first Tuko-inspired layout
- blog_list.html modern article listing
- blog_view.html cleaner reading page with related articles
- media.html Operations Gallery page
- media_view.html media detail page with full narration
- hub.html professional profile/competencies page
- admin blog category + trending fields
- admin media title + short narration + full narration
- data.py columns for category/trending/media narration

Before deployment:
1. Backup your current project.
2. Replace files with these files.
3. Keep your .env and live database credentials.
4. Deploy to Render.
5. Open /, /blog, /hub, /media and admin panel to verify.
