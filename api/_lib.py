"""Shared helpers: Supabase REST, Telegram, admin session cookie, JSON responses.

All keys come from Vercel environment variables, never from the code:
SUPABASE_URL, SUPABASE_SERVICE_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_PASSWORD.
"""
import base64, hashlib, hmac, json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STATUSES = ('новая', 'в работе', 'закрыта')
SESSION_COOKIE = 'lh47_admin'
SESSION_DAYS = 7
TZ = ZoneInfo('Europe/Chisinau')


def env(name):
    v = (os.environ.get(name) or '').strip()
    if not v:
        raise RuntimeError(f'Не задана переменная окружения {name}')
    return v


# ---------- validation ----------
def clean_lead(data):
    """(lead, None) if the form is valid, else (None, error text for the visitor)."""
    name = ' '.join(str(data.get('name') or '').split())
    phone = str(data.get('phone') or '').strip()
    comment = str(data.get('comment') or '').strip()
    if len(name) < 2 or len(name) > 80:
        return None, 'Укажите имя (от 2 до 80 символов).'
    digits = re.sub(r'\D', '', phone)
    if not re.fullmatch(r'[+\d\s()\-]{6,25}', phone) or not 7 <= len(digits) <= 15:
        return None, 'Укажите телефон, например +373 69 123 456.'
    if len(comment) < 3 or len(comment) > 2000:
        return None, 'Расскажите коротко о проекте (от 3 до 2000 символов).'
    return {'name': name, 'phone': phone, 'comment': comment}, None


def local_time(iso):
    """Supabase timestamp → «27.10.2026 21:05» in Chisinau time (same in Telegram and in the admin panel)."""
    dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).strftime('%d.%m.%Y %H:%M')


# ---------- Supabase ----------
def supabase(method, path, body=None, prefer=None):
    url = env('SUPABASE_URL').rstrip('/') + '/rest/v1/' + path
    key = env('SUPABASE_SERVICE_KEY')
    headers = {'apikey': key, 'Content-Type': 'application/json'}
    if key.startswith('eyJ'):  # legacy service_role JWT; new sb_secret_… keys go in apikey only
        headers['Authorization'] = 'Bearer ' + key
    if prefer:
        headers['Prefer'] = prefer
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:  # Supabase explains why (bad key, RLS, missing table) in the body
        print('supabase', method, path.split('?')[0], e.code, e.read()[:300].decode('utf-8', 'replace'))
        raise
    return json.loads(raw) if raw else None


# ---------- Telegram ----------
def notify(lead):
    text = ('🟠 Новая заявка с сайта LH47\n\n'
            f"👤 {lead['name']}\n📞 {lead['phone']}\n💬 {lead['comment']}\n\n"
            f"🕒 {local_time(lead['created_at'])}\n№ {lead['id']} · статус: {lead['status']}")
    url = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage"
    body = json.dumps({'chat_id': env('TELEGRAM_CHAT_ID'), 'text': text}).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r).get('ok')


# ---------- admin session ----------
def _key():
    # Signing key derived from the admin password: changing the password logs everyone out.
    return hashlib.sha256(('lh47-admin:' + env('ADMIN_PASSWORD')).encode()).digest()


def make_session():
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = base64.urlsafe_b64encode(hmac.new(_key(), exp.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return f'{exp}.{sig}'


def valid_session(token):
    try:
        exp, sig = token.split('.')
        good = base64.urlsafe_b64encode(hmac.new(_key(), exp.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        return hmac.compare_digest(sig, good) and int(exp) > time.time()
    except (ValueError, AttributeError):
        return False


def password_ok(given):
    return hmac.compare_digest(hashlib.sha256(str(given).encode()).digest(),
                               hashlib.sha256(env('ADMIN_PASSWORD').encode()).digest())


def cookies(handler):
    out = {}
    for part in (handler.headers.get('Cookie') or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k:
            out[k] = v
    return out


def is_admin(handler):
    return valid_session(cookies(handler).get(SESSION_COOKIE, ''))


def session_cookie(value, max_age):
    return f'{SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict'


# ---------- HTTP ----------
def read_json(handler):
    n = int(handler.headers.get('Content-Length') or 0)
    if n > 20000:
        return {}
    try:
        return json.loads(handler.rfile.read(n) or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def send_json(handler, code, data, headers=()):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    for k, v in headers:
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)
