import os
import json
import re
import sqlite3
import threading
import time
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

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
MASTODON_INSTANCE = os.environ.get('MASTODON_INSTANCE', 'https://mastodon.social')
MASTODON_TOKEN = os.environ.get('MASTODON_TOKEN', '')


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
    rows = conn.execute("SELECT slug, post_type, insta_url, created_at FROM posts ORDER BY created_at DESC").fetchall()
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


# ============ Signal Blasters (সব Instagram URL-এর দিকে) ============

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
        print(f"IndexNow: {r.status_code}")
    except Exception as e:
        print(f"IndexNow: {e}")


def post_to_telegram(insta_url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"✈️ Flight Deal\n{insta_url}",
                "disable_web_page_preview": "false"
            },
            timeout=10
        )
    except Exception as e:
        print(f"Telegram: {e}")


def post_to_mastodon(insta_url):
    if not MASTODON_TOKEN:
        return
    try:
        requests.post(
            f"{MASTODON_INSTANCE}/api/v1/statuses",
            headers={"Authorization": f"Bearer {MASTODON_TOKEN}"},
            json={"status": f"✈️ New Flight Deal: {insta_url}"},
            timeout=10
        )
    except Exception as e:
        print(f"Mastodon: {e}")


def save_wayback(url):
    try:
        requests.get(f"https://web.archive.org/save/{url}", timeout=40)
    except Exception as e:
        print(f"Wayback: {e}")


def ping_pingomatic():
    try:
        requests.post("https://pingomatic.com/ping/", data={
            "title": SITE_NAME, "blogurl": SITE_URL,
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


def blast_all(insta_urls):
    """সব সিগন্যাল Instagram URL-এর দিকে (background thread)"""
    def run():
        # ১. IndexNow — সব Instagram URL একসাথে
        ping_indexnow(insta_urls[:10000])
        
        # ২. Telegram — প্রতিটি Instagram URL
        for u in insta_urls[:200]:
            post_to_telegram(u)
            time.sleep(0.5)  # rate limit
        
        # ৩. Mastodon — প্রতিটি Instagram URL (৩০ সেকেন্ড delay)
        for u in insta_urls[:50]:
            post_to_mastodon(u)
            time.sleep(30)
        
        # ৪. Wayback — প্রথম ১০টা
        for u in insta_urls[:10]:
            save_wayback(u)
        
        # ৫. Ping-O-Matic
        ping_pingomatic()
        
        print(f"[BLAST DONE] {len(insta_urls)} Instagram URLs")
    
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
<title>{{ name }} — Instagram Indexer</title>
<style>
body{font-family:system-ui;max-width:900px;margin:40px auto;padding:20px;background:#f5f5f5}
textarea{width:100%;padding:12px;font-family:monospace;font-size:14px;border:2px solid #ddd;border-radius:8px;box-sizing:border-box}
button{padding:14px 40px;font-size:16px;background:#007bff;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:600}
button:disabled{background:#999}
#status{margin-top:24px;padding:16px;background:white;border-radius:8px;font-family:monospace;font-size:13px;max-height:500px;overflow-y:auto}
.ok{color:#28a745}.err{color:#dc3545}.info{color:#007bff}
</style></head><body>
<h1>🚀 {{ name }}</h1>
<p><b>Instagram URL পেস্ট করুন</b> — সিস্টেম সরাসরি Instagram URL-এ সিগন্যাল পাঠাবে:</p>
<ul>
<li>📡 IndexNow → Bing/Yandex</li>
<li>📱 Telegram channel</li>
<li>🐘 Mastodon</li>
<li>📼 Wayback Machine</li>
<li>📢 Ping-O-Matic</li>
</ul>
<textarea id="links" rows="15" placeholder="https://www.instagram.com/p/ABC123/
https://www.instagram.com/reel/XYZ789/"></textarea>
<br><br><button id="btn" onclick="start()">Send Signals</button>
<div id="status"></div>
<script>
async function start() {
    const btn = document.getElementById('btn'); btn.disabled = true;
    const links = document.getElementById('links').value.trim().split('\\n').map(l=>l.trim()).filter(l=>l);
    const status = document.getElementById('status');
    if (links.length === 0) { status.innerHTML = '<span class="err">⚠️ লিংক নেই</span>'; btn.disabled = false; return; }
    status.innerHTML = `<span class="info">📥 মোট ${links.length} টি Instagram URL</span><br><br>`;
    let ok = 0, fail = 0;
    for (let i = 0; i < links.length; i++) {
        const fd = new FormData(); fd.append('insta_url', links[i]);
        try {
            const r = await fetch('/submit', { method: 'POST', body: fd });
            if (r.ok) { ok++; status.innerHTML += `<span class="ok">✅ ${i+1}. ${links[i]}</span><br>`; }
            else { fail++; status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]}</span><br>`; }
        } catch (e) { fail++; status.innerHTML += `<span class="err">❌ ${i+1}. ${links[i]}</span><br>`; }
        status.scrollTop = status.scrollHeight;
        await new Promise(r => setTimeout(r, 100));
    }
    status.innerHTML += `<br><span class="info">📡 Instagram URL-এ সিগন্যাল পাঠানো হচ্ছে...</span><br>`;
    try { const br = await fetch('/blast', { method: 'POST' }); const bt = await br.text(); status.innerHTML += `<span class="info">${bt}</span><br>`; } catch (e) {}
    status.innerHTML += `<br><b>🎉 শেষ! সফল: ${ok}, ব্যর্থ: ${fail}</b><br>`;
    btn.disabled = false;
}
</script></body></html>
''', name=SITE_NAME, meta_tag=meta_tag)


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
    insta_urls = [row[2] for row in rows[:10000]]  # insta_url column
    blast_all(insta_urls)
    return f"✅ {len(insta_urls)} Instagram URL-এ সিগন্যাল পাঠানো হয়েছে (Telegram + Mastodon + IndexNow + Wayback + Ping)", 200


# ============ Mirror Pages (backup) ============

def render_post_page(t, slug):
    insta_url = get_insta_url(t, slug)
    mirror_url = get_mirror_url(t, slug)
    return f'''<!DOCTYPE html><html><head>
<meta charset="UTF-8"><title>Instagram {t} - {slug}</title>
<link rel="canonical" href="{mirror_url}" />
<meta http-equiv="refresh" content="2; url={insta_url}" />
</head><body style="font-family:system-ui;padding:40px;text-align:center;">
<h1>Instagram {t}: {slug}</h1>
<p>Redirecting to Instagram...</p>
<p><a href="{insta_url}">👉 Instagram এ যান</a></p>
</body></html>'''


@app.route('/c/<slug>')
def page_c(slug): return render_post_page('p', slug)

@app.route('/r/<slug>')
def page_r(slug): return render_post_page('reel', slug)

@app.route('/tv/<slug>')
def page_tv(slug): return render_post_page('tv', slug)


# ============ Sitemap & Misc ============

@app.route('/sitemap.xml')
def sitemap_xml():
    rows = get_all_posts()
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>'
    for slug, t, _, created in rows:
        xml += f'<url><loc>{get_mirror_url(t, slug)}</loc><lastmod>{created[:10]}</lastmod></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


@app.route('/rss.xml')
def rss():
    rows = get_all_posts()[:50]
    items = ""
    for slug, t, _, created in rows:
        url = get_mirror_url(t, slug)
        items += f'<item><title>Instagram {t} - {slug}</title><link>{url}</link><guid>{url}</guid><pubDate>{created}</pubDate></item>'
    xml = f'<?xml version="1.0"?><rss version="2.0"><channel><title>{SITE_NAME}</title><link>{SITE_URL}/</link>{items}</channel></rss>'
    return Response(xml, mimetype='application/rss+xml')


@app.route('/sitemap.html')
def sitemap_html():
    rows = get_all_posts()
    links = "".join(f'<li><a href="{r[2]}">{r[2]}</a></li>' for r in rows)
    return f'<h1>সব Instagram URL ({len(rows)})</h1><ul>{links}</ul><p><a href="/">← হোম</a></p>'


@app.route('/robots.txt')
def robots():
    nl = chr(10)
    txt = "User-agent: *" + nl + "Allow: /" + nl + nl
    txt += "Sitemap: " + SITE_URL + "/sitemap.xml" + nl
    return txt, 200, {'Content-Type': 'text/plain'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
