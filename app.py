import os
import json
import re
import sqlite3
import threading
import requests
from datetime import datetime
from flask import Flask, request, render_template_string, Response

app = Flask(__name__)
app.url_map.strict_slashes = False

SITE_DOMAIN = "instaindex.onrender.com"
SITE_URL = f"https://{SITE_DOMAIN}"
SITE_NAME = "IndexFast"
INDEXNOW_KEY = os.environ.get('INDEXNOW_KEY', 'if2026trevomo9x8y7z6w5v4u3t2s1r0q')
DB_PATH = "posts.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (
        slug TEXT PRIMARY KEY,
        post_type TEXT,
        insta_url TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()


def save_post(slug, post_type, insta_url):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO posts (slug, post_type, insta_url, created_at) VALUES (?, ?, ?, ?)",
        (slug, post_type, insta_url, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_all_posts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT slug, post_type, created_at FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows


init_db()


def extract_post_info(url):
    m = re.search(r'instagram\.com/(p|reel|tv)/([A-Za-z0-9_-]+)/?', url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def get_insta_url(t, slug):
    return f"https://www.instagram.com/{t}/{slug}/"


def get_mirror_url(t, slug):
    prefix = {'reel': 'r', 'tv': 'tv', 'p': 'c'}[t]
    return f"{SITE_URL}/{prefix}/{slug}"


def ping_indexnow(urls):
    try:
        r = requests.post("https://api.indexnow.org/indexnow", json={
            "host": SITE_DOMAIN,
            "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": urls if isinstance(urls, list) else [urls]
        }, timeout=15)
        print(f"IndexNow: {r.status_code}")
    except Exception as e:
        print(f"IndexNow error: {e}")


def ping_google_sitemap():
    try:
        requests.get(f"https://www.google.com/ping?sitemap={SITE_URL}/sitemap.xml", timeout=10)
    except:
        pass


def ping_bing_sitemap():
    try:
        requests.get(f"https://www.bing.com/ping?sitemap={SITE_URL}/sitemap.xml", timeout=10)
    except:
        pass


def ping_pingomatic():
    try:
        requests.post("https://pingomatic.com/ping/", data={
            "title": SITE_NAME,
            "blogurl": SITE_URL,
            "rssurl": f"{SITE_URL}/rss.xml",
            "chk_weblogscom": "on", "chk_blogs": "on", "chk_feedburner": "on",
            "chk_google": "on", "chk_technorati": "on", "chk_bloglines": "on",
            "chk_newsgator": "on", "chk_myyahoo": "on", "chk_pubsubcom": "on",
            "chk_blogdigger": "on", "chk_weblogalot": "on", "chk_newsisfree": "on",
            "chk_topicexchange": "on", "chk_tailrank": "on", "chk_syndic8": "on",
            "chk_icerocket": "on", "chk_newsburst": "on", "chk_feedster": "on",
        }, timeout=20)
    except Exception as e:
        print(f"Pingomatic: {e}")


def save_wayback(url):
    try:
        requests.get(f"https://web.archive.org/save/{url}", timeout=40)
    except Exception as e:
        print(f"Wayback: {e}")


def blast_all(mirror_urls):
    def run():
        if mirror_urls:
            ping_indexnow(mirror_urls[:10000])
        for u in mirror_urls[:10]:
            save_wayback(u)
        ping_google_sitemap()
        ping_bing_sitemap()
        ping_pingomatic()
        print(f"[BLAST DONE] {len(mirror_urls)} URLs")
    threading.Thread(target=run, daemon=True).start()


@app.route(f'/{INDEXNOW_KEY}.txt')
def indexnow_key():
    return INDEXNOW_KEY, 200, {'Content-Type': 'text/plain'}


@app.route('/')
def home():
    return render_template_string('''
<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<title>{{ name }} — Bulk Instagram Indexer</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; background: #f5f5f5; }
h1 { color: #222; }
textarea { width: 100%; padding: 12px; font-family: monospace; font-size: 14px; border: 2px solid #ddd; border-radius: 8px; box-sizing: border-box; }
button { padding: 14px 40px; font-size: 16px; background: #007bff; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; }
button:disabled { background: #999; cursor: not-allowed; }
#status { margin-top: 24px; padding: 16px; background: white; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 500px; overflow-y: auto; }
.ok { color: #28a745; }
.err { color: #dc3545; }
.info { color: #007bff; }
a { color: #007bff; }
</style>
</head>
<body>
<h1>🚀 {{ name }}</h1>
<p>প্রতি লাইনে একটি Instagram URL পেস্ট করুন। সব অটো হবে।</p>

<textarea id="links" rows="15" placeholder="https://www.instagram.com/p/ABC123/
https://www.instagram.com/reel/XYZ789/"></textarea>
<br><br>
<button id="btn" onclick="start()">Start Indexing</button>

<div id="status"></div>

<script>
async function start() {
    const btn = document.getElementById('btn');
    btn.disabled = true;
    const raw = document.getElementById('links').value.trim();
    const links = raw.split('\\n').map(l => l.trim()).filter(l => l);
    const status = document.getElementById('status');

    if (links.length === 0) {
        status.innerHTML = '<span class="err">⚠️ কোনো লিংক নেই</span>';
        btn.disabled = false;
        return;
    }

    status.innerHTML = `<span class="info">📥 মোট ${links.length} টি লিংক</span><br><br>`;
    let ok = 0, fail = 0;

    for (let i = 0; i < links.length; i++) {
        const fd = new FormData();
        fd.append('insta_url', links[i]);
        try {
            const r = await fetch('/submit', { method: 'POST', body: fd });
            if (r.ok) {
                ok++;
                status.innerHTML += `<span class="ok">✅ ${i+1}. ${links[i]}</span><br>`;
            } else {
                fail++;
                status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]}</span><br>`;
            }
        } catch (e) {
            fail++;
            status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]} — ${e.message}</span><br>`;
        }
        status.scrollTop = status.scrollHeight;
        await new Promise(r => setTimeout(r, 150));
    }

    status.innerHTML += `<br><span class="info">📡 সিগন্যাল পাঠানো হচ্ছে...</span><br>`;
    try {
        const br = await fetch('/blast', { method: 'POST' });
        const bt = await br.text();
        status.innerHTML += `<span class="info">${bt}</span><br>`;
    } catch (e) {
        status.innerHTML += `<span class="err">Blast error: ${e.message}</span><br>`;
    }

    status.innerHTML += `<br><b>🎉 শেষ! সফল: ${ok}, ব্যর্থ: ${fail}</b><br>`;
    btn.disabled = false;
}
</script>
</body>
</html>
''', name=SITE_NAME)


@app.route('/submit', methods=['POST'])
def submit():
    insta_url = request.form.get('insta_url', '').strip()
    t, slug = extract_post_info(insta_url)
    if not slug:
        return "Invalid Instagram URL", 400
    save_post(slug, t, insta_url)
    return "OK", 200


@app.route('/blast', methods=['POST'])
def blast():
    rows = get_all_posts()
    urls = [get_mirror_url(t, s) for s, t, _ in rows[:10000]]
    blast_all(urls)
    return f"✅ {len(urls)} URL পাঠানো হয়েছে (background)", 200


def render_post_page(t, slug):
    insta_url = get_insta_url(t, slug)
    mirror_url = get_mirror_url(t, slug)
    published = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    schema = {
        "@context": "https://schema.org",
        "@type": "SocialMediaPosting",
        "url": mirror_url,
        "sameAs": insta_url,
        "headline": f"Instagram {t} - {slug}",
        "datePublished": published,
        "author": {"@type": "Organization", "name": SITE_NAME}
    }

    return f'''<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Instagram {t} - {slug} | {SITE_NAME}</title>
<meta name="description" content="Instagram {t} পোস্ট {slug} এর রেফারেন্স পেজ। {SITE_NAME} এ দেখুন।">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{mirror_url}" />
<meta property="og:url" content="{mirror_url}" />
<meta property="og:title" content="Instagram {t} - {slug}" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="{SITE_NAME}" />
<script type="application/ld+json">{json.dumps(schema)}</script>
</head>
<body style="max-width:720px;margin:0 auto;padding:24px;font-family:system-ui;line-height:1.7;color:#222;">
<h1>Instagram {t}: {slug}</h1>
<p style="color:#666;font-size:14px;">প্রকাশিত: {datetime.utcnow().strftime("%Y-%m-%d")}</p>
<p>এই পেজটি Instagram পোস্ট <strong>{slug}</strong> এর একটি রেফারেন্স পেজ।</p>
<p style="margin:24px 0;">
<a href="{insta_url}" rel="noopener" style="display:inline-block;padding:12px 24px;background:#E1306C;color:white;text-decoration:none;border-radius:6px;font-weight:600;">
👉 Instagram এ মূল পোস্ট
</a>
</p>
<table style="border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;"><b>Post ID</b></td><td style="padding:8px;border:1px solid #ddd;"><code>{slug}</code></td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><b>Type</b></td><td style="padding:8px;border:1px solid #ddd;">{t}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><b>Source</b></td><td style="padding:8px;border:1px solid #ddd;">instagram.com</td></tr>
</table>
<p style="margin-top:40px;padding-top:20px;border-top:1px solid #ddd;font-size:14px;">
<a href="/">← হোম</a> | <a href="/sitemap.html">সব পেজ</a>
</p>
</body>
</html>'''


@app.route('/c/<slug>')
def page_c(slug):
    return render_post_page('p', slug)


@app.route('/r/<slug>')
def page_r(slug):
    return render_post_page('reel', slug)


@app.route('/tv/<slug>')
def page_tv(slug):
    return render_post_page('tv', slug)


@app.route('/sitemap.xml')
def sitemap_xml():
    rows = get_all_posts()
    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>'
    for slug, t, created in rows:
        xml += f'<url><loc>{get_mirror_url(t, slug)}</loc><lastmod>{created[:10]}</lastmod><priority>0.8</priority></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


@app.route('/rss.xml')
def rss():
    rows = get_all_posts()[:100]
    items = ""
    for slug, t, created in rows:
        url = get_mirror_url(t, slug)
        items += f'<item><title>Instagram {t} - {slug}</title><link>{url}</link><guid>{url}</guid><pubDate>{created}</pubDate></item>'
    xml = f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{SITE_NAME}</title><link>{SITE_URL}/</link><description>Instagram Index</description>{items}</channel></rss>'
    return Response(xml, mimetype='application/rss+xml')


@app.route('/sitemap.html')
def sitemap_html():
    rows = get_all_posts()
    links = "".join(
        f'<li><a href="{get_mirror_url(t, s)}">{t}/{s}</a> — {c[:10]}</li>'
        for s, t, c in rows
    )
    return f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>All Posts</title></head><body style="font-family:system-ui;max-width:900px;margin:40px auto;padding:20px;"><h1>সব পেজ ({len(rows)})</h1><ul>{links}</ul><p><a href="/">← হোম</a></p></body></html>'


@app.route('/robots.txt')
def robots():
    txt = f"User-agent: *\\nAllow: /\\n\\nSitemap: {SITE_URL}/sitemap.xml\\nSitemap: {SITE_URL}/rss.xml\\n"
    return txt, 200, {'Content-Type': 'text/plain'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
