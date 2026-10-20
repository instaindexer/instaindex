import os
import re
import hashlib
import sqlite3
import threading
import time
import base64
import requests
from datetime import datetime
from flask import Flask, request, render_template_string, Response, abort

# Google Indexing API Libraries
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)
app.url_map.strict_slashes = False

SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'pdfindex.onrender.com')
SITE_URL = f"https://{SITE_DOMAIN}"
SITE_NAME = "LinkIndexFast"
INDEXNOW_KEY = os.environ.get('INDEXNOW_KEY', 'lf2026pdf8x7y6z5w4v3u2t1s0r9q')
DB_PATH = "links.db"

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Google Service Account Config
SCOPES = ["https://www.googleapis.com/auth/indexing"]
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_JSON_KEY_PATH', 'service_account.json')


# ============ Database ============

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS links (
        slug TEXT PRIMARY KEY,
        target_url TEXT,
        title TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()


def save_link(slug, target_url, title=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO links (slug, target_url, title, created_at) VALUES (?, ?, ?, ?)",
        (slug, target_url, title, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_all_links():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT slug, target_url, title, created_at FROM links ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows


init_db()


def make_slug(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]


def get_wrapper_url(slug):
    return f"{SITE_URL}/out/{slug}"


# ============ Power Signal & Backlink Engines ============

def update_github_backlinks(rows):
    """GitHub repository-te automatically BACKLINKS.md file update kora"""
    github_token = os.environ.get('GITHUB_TOKEN', '')
    repo_name = os.environ.get('GITHUB_REPO', '') # e.g., 'instaindexer/instaindex'
    
    if not github_token or not repo_name:
        print("[GitHub Backlinks Skipped] GITHUB_TOKEN or GITHUB_REPO not configured.")
        return
        
    md_content = "# Auto Generated SEO Backlinks\n\n"
    for slug, target, title, created in rows[:500]:
        w_url = get_wrapper_url(slug)
        md_content += f"- [{title or target}]({w_url}) - Indexed on {created}\n"
        
    url = f"https://api.github.com/repos/{repo_name}/contents/BACKLINKS.md"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "vnd.github+json"
    }
    
    try:
        get_res = requests.get(url, headers=headers)
        sha = get_res.json().get('sha') if get_res.status_code == 200 else None
        
        payload = {
            "message": "Auto-update SEO backlinks [skip ci]",
            "content": base64.b64encode(md_content.encode()).decode(),
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha
            
        put_res = requests.put(url, json=payload, headers=headers, timeout=15)
        if put_res.status_code in [200, 201]:
            print("[GitHub Backlinks] BACKLINKS.md successfully updated!")
        else:
            print(f"[GitHub Backlinks Error] Status code: {put_res.status_code}, Response: {put_res.text}")
    except Exception as e:
        print(f"[GitHub Backlink Error] {e}")


def send_google_indexing_api(wrapper_url):
    """Google Indexing API diye sorasori Google-er crawler-ke Instant Indexing signal pathano"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[Google API Skipped] {SERVICE_ACCOUNT_FILE} file paowa jayni!")
        return
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('indexing', 'v3', credentials=credentials)
        body = {
            "url": wrapper_url,
            "type": "URL_UPDATED"
        }
        response = service.urlNotifications().publish(body=body).execute()
        print(f"[Google API Success] Indexed: {wrapper_url}")
    except Exception as e:
        print(f"[Google API Error] {e}")


def ping_indexnow(urls):
    if not urls:
        return
    try:
        r = requests.post("https://api.indexnow.org/indexnow", json={
            "host": SITE_DOMAIN,
            "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": urls if isinstance(urls, list) else [urls]
        }, timeout=15)
        print(f"[IndexNow Status] {r.status_code}")
    except Exception as e:
        print(f"[IndexNow Error] {e}")


def post_to_telegram(url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"🚀 New Indexed Link:\n{url}",
                "disable_web_page_preview": "false"
            },
            timeout=10
        )
    except Exception as e:
        print(f"[Telegram Error] {e}")


def save_wayback(url):
    try:
        requests.get(f"https://web.archive.org/save/{url}", timeout=30)
    except Exception as e:
        print(f"[Wayback Error] {e}")


def ping_rss_services():
    """Dynamic RSS Feed-ke powerful RPC Ping Server-e notify kora"""
    rss_url = f"{SITE_URL}/rss.xml"
    rpc_servers = [
        "http://rpc.pingomatic.com/",
        "http://rpc.technorati.com/rpc/ping",
        "http://ping.feedburner.com",
        "http://blogsearch.google.com/ping/RPC2"
    ]
    headers = {'Content-Type': 'text/xml'}
    xml_payload = f"""<?xml version="1.0"?>
    <methodCall>
      <methodName>weblogUpdates.ping</methodName>
      <params>
        <param><value>{SITE_NAME}</value></param>
        <param><value>{SITE_URL}</value></param>
      </params>
    </methodCall>"""

    for server in rpc_servers:
        try:
            requests.post(server, data=xml_payload, headers=headers, timeout=10)
        except Exception:
            pass


def blast_all(wrapper_urls, all_rows):
    """Shob signal background thread-e process kora"""
    def run():
        # 1. Update GitHub Backlinks (BACKLINKS.md)
        update_github_backlinks(all_rows)

        # 2. Direct Google Cloud Indexing API Hit
        for u in wrapper_urls[:200]:  # Daily Free Quota: 200 URLs
            send_google_indexing_api(u)
            time.sleep(0.3)

        # 3. IndexNow (Bing/Yandex Instant Index)
        ping_indexnow(wrapper_urls[:10000])

        # 4. Telegram Broadcast
        for u in wrapper_urls[:100]:
            post_to_telegram(u)
            time.sleep(0.3)

        # 5. Wayback Archive Engine
        for u in wrapper_urls[:10]:
            save_wayback(u)

        # 6. RSS Feed Ping Engine
        ping_rss_services()

        print(f"[BLAST COMPLETED] Total Processed: {len(wrapper_urls)} URLs")

    threading.Thread(target=run, daemon=True).start()


# ============ Routes ============

@app.route(f'/{INDEXNOW_KEY}.txt')
def indexnow_key():
    return INDEXNOW_KEY, 200, {'Content-Type': 'text/plain'}


@app.route('/google<google_verify>.html')
def google_verify(google_verify):
    code = os.environ.get('GOOGLE_VERIFY', '')
    return f'google-site-verification: google{code}.html'


@app.route('/')
def home():
    google_code = os.environ.get('GOOGLE_VERIFY', '')
    meta_tag = f'<meta name="google-site-verification" content="{google_code}" />' if google_code else ''
    return render_template_string('''
<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8">{{ meta_tag|safe }}
<title>{{ name }} — Premium Link & Content Indexer</title>
<style>
body{font-family:system-ui;max-width:900px;margin:40px auto;padding:20px;background:#f5f5f5}
textarea{width:100%;padding:12px;font-family:monospace;font-size:14px;border:2px solid #ddd;border-radius:8px;box-sizing:border-box}
button{padding:14px 40px;font-size:16px;background:#28a745;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:600}
button:disabled{background:#999}
#status{margin-top:24px;padding:16px;background:white;border-radius:8px;font-family:monospace;font-size:13px;max-height:500px;overflow-y:auto}
.ok{color:#28a745}.err{color:#dc3545}.info{color:#007bff}
</style></head><body>
<h1>⚡ {{ name }} — Premium Link Indexer</h1>
<p><b>Instagram, PDF, Netlify, Google Drive ba jekono link ekshathe paste korun:</b></p>
<ul>
<li>🚀 <b>Google Indexing API & GitHub Backlinks:</b> Fast indexing & High DA backlink generation</li>
<li>📡 <b>IndexNow:</b> Bing & Yandex indexing</li>
<li>📢 <b>RSS Multi-RPC Ping:</b> Feed bot crawler alert</li>
<li>📼 <b>Wayback Machine & Telegram Feed</b></li>
</ul>
<textarea id="links" rows="15" placeholder="https://www.instagram.com/p/...
https://deft-lokum-1718c2.netlify.app
https://drive.google.com/file/d/.../view
https://example.com/document.pdf"></textarea>
<br><br><button id="btn" onclick="start()">Send High-Power Signals</button>
<div id="status"></div>
<script>
async function start() {
    const btn = document.getElementById('btn'); btn.disabled = true;
    const links = document.getElementById('links').value.trim().split('\\n').map(l=>l.trim()).filter(l=>l);
    const status = document.getElementById('status');
    if (links.length === 0) { status.innerHTML = '<span class="err">⚠️ Kono link paowa jayni</span>'; btn.disabled = false; return; }
    status.innerHTML = `<span class="info">📥 Mot ${links.length} ti link process kora hocche...</span><br><br>`;
    let ok = 0, fail = 0;
    for (let i = 0; i < links.length; i++) {
        const fd = new FormData(); fd.append('target_url', links[i]);
        try {
            const r = await fetch('/submit', { method: 'POST', body: fd });
            if (r.ok) { ok++; status.innerHTML += `<span class="ok">✅ ${i+1}. ${links[i]}</span><br>`; }
            else { fail++; status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]}</span><br>`; }
        } catch (e) { fail++; status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]}</span><br>`; }
        status.scrollTop = status.scrollHeight;
        await new Promise(r => setTimeout(r, 100));
    }
    status.innerHTML += `<br><span class="info">⚡ GitHub BACKLINKS.md & Google Cloud API Signals pathano hocche...</span><br>`;
    try { const br = await fetch('/blast', { method: 'POST' }); const bt = await br.text(); status.innerHTML += `<span class="info">${bt}</span><br>`; } catch (e) {}
    status.innerHTML += `<br><b>🎉 Process shomponno! Shoful: ${ok}, Byortho: ${fail}</b><br>`;
    btn.disabled = false;
}
</script></body></html>
''', name=SITE_NAME, meta_tag=meta_tag)


@app.route('/submit', methods=['POST'])
def submit():
    target_url = request.form.get('target_url', '').strip()
    if not target_url.startswith('http'):
        return "Invalid URL", 400
    slug = make_slug(target_url)
    save_link(slug, target_url)
    return "OK", 200


@app.route('/blast', methods=['POST'])
def blast():
    rows = get_all_links()
    wrapper_urls = [get_wrapper_url(r[0]) for r in rows[:10000]]
    blast_all(wrapper_urls, rows)
    return f"✅ {len(wrapper_urls)} ti wrapper URL-e GitHub Backlinks + Google Indexing API Signals pathano hoyeche!", 200


# ============ Wrapper Pages ============

@app.route('/out/<slug>')
def wrapper_page(slug):
    rows = get_all_links()
    match = next((r for r in rows if r[0] == slug), None)
    if not match:
        abort(404)
    target_url = match[1]
    title = match[2] or "External Resource"
    return render_template_string('''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{ title }}</title>
<meta name="robots" content="index, follow">
<meta name="description" content="This page shares an external resource link. Click to visit the original source.">
<style>
body{font-family:system-ui,Arial;max-width:800px;margin:40px auto;padding:20px;line-height:1.6;color:#222}
h1{color:#111}
a{color:#0066cc;word-break:break-all}
.box{background:#f8f9fa;padding:20px;border-radius:8px;border-left:4px solid #28a745;margin:20px 0}
</style>
</head>
<body>
<h1>External Resource</h1>
<p>This page shares an external link. You can visit the original source below:</p>
<div class="box">
<p><b>🔗 Link:</b><br>
<a href="{{ target }}" rel="noopener" target="_blank">{{ target }}</a></p>
</div>
<hr>
<p style="color:#888;font-size:14px;">Generated by {{ site }}</p>
</body>
</html>''', target=target_url, title=title, site=SITE_NAME)


# ============ Dynamic RSS & Sitemap ============

@app.route('/rss.xml')
def rss():
    rows = get_all_links()[:100]
    items = ""
    for slug, target, title, created in rows:
        url = get_wrapper_url(slug)
        items += f'<item><title>{title or "Resource"}</title><link>{url}</link><guid>{url}</guid><pubDate>{created}</pubDate></item>'
    xml = f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{SITE_NAME}</title><link>{SITE_URL}/</link>{items}</channel></rss>'
    return Response(xml, mimetype='application/rss+xml')


@app.route('/sitemap.xml')
def sitemap_xml():
    rows = get_all_links()
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>'
    for slug, _, _, created in rows:
        xml += f'<url><loc>{get_wrapper_url(slug)}</loc><lastmod>{created[:10]}</lastmod></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
