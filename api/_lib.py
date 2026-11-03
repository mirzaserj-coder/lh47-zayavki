"""Shared helpers: Supabase REST, Telegram, admin session cookie, JSON responses.

All keys come from Vercel environment variables, never from the code:
SUPABASE_URL, SUPABASE_SERVICE_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_PASSWORD.
"""
import base64, hashlib, hmac, json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Воронка CRM: первый этап — куда падают новые заявки, «Отказ» — последний.
STAGES = ('Новая', 'Связались', 'Встреча', 'КП отправлено', 'Оплачено', 'Отказ')
SOURCES = ('Сайт', 'Вручную', 'Визитка', 'Telegram')
MARKETS = {'md': '🇲🇩 Молдова', 'ru': '🇷🇺 Россия'}
# Сайты, с которых форма может слать заявки сюда (русский сайт — статичный, без своего сервера).
ALLOWED_ORIGINS = ('https://lh47-russia.vercel.app', 'https://lh47.ru', 'https://www.lh47.ru')
SESSION_COOKIE = 'lh47_admin'
SESSION_DAYS = 7
TZ = ZoneInfo('Europe/Chisinau')


def env(name):
    v = (os.environ.get(name) or '').strip()
    if not v:
        raise RuntimeError(f'Не задана переменная окружения {name}')
    return v


# ---------- validation ----------
def clean_lead(data, manual=False):
    """(lead, None) if the form is valid, else (None, error text for the visitor).

    manual — клиент, которого менеджер вносит сам после звонка или встречи: комментарий необязателен."""
    name = ' '.join(str(data.get('name') or '').split())
    phone = str(data.get('phone') or '').strip()
    comment = str(data.get('comment') or '').strip()
    market = data.get('market') if data.get('market') in MARKETS else 'md'
    if len(name) < 2 or len(name) > 80:
        return None, 'Укажите имя (от 2 до 80 символов).'
    digits = re.sub(r'\D', '', phone)
    telegram = re.fullmatch(r'@?[A-Za-z][\w]{4,31}', phone)  # «Телефон или Telegram» на русском сайте
    if not telegram and (not re.fullmatch(r'[+\d\s()\-]{6,25}', phone) or not 7 <= len(digits) <= 15):
        return None, 'Укажите телефон, например +7 900 123 45 67, или Telegram.' if market == 'ru' else 'Укажите телефон, например +373 69 123 456.'
    if len(comment) > 2000 or (not manual and len(comment) < 3):
        return None, 'Расскажите коротко о проекте (от 3 до 2000 символов).'
    return {'name': name, 'phone': phone, 'comment': comment, 'market': market}, None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_lead(lead, source):
    """Row for a new client: first stage of the funnel, the stage history starts with it."""
    return dict(lead, status=STAGES[0], source=source, notes='', history=[{'stage': STAGES[0], 'at': now_iso()}])


def move(row, stage):
    """PATCH body that moves a client to another stage and records the move in its history."""
    return {'status': stage, 'history': list(row.get('history') or []) + [{'stage': stage, 'at': now_iso()}]}


def local_time(iso):
    """Supabase timestamp → «27.10.2026 21:05» in Chisinau time (same in Telegram and in the admin panel)."""
    dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).strftime('%d.%m.%Y %H:%M')


# ---------- Supabase ----------
def supabase_key():
    # The Supabase ↔ Vercel integration syncs SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY; a hand-set
    # SUPABASE_SERVICE_KEY is the fallback.
    for name in ('SUPABASE_SECRET_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_SERVICE_KEY'):
        v = (os.environ.get(name) or '').strip()
        if v:
            return v
    raise RuntimeError('Не задан ключ Supabase (SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY)')


def supabase(method, path, body=None, prefer=None):
    url = env('SUPABASE_URL').rstrip('/') + '/rest/v1/' + path
    key = supabase_key()
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
        kind = next((p for p in ('sb_secret_', 'sb_publishable_', 'eyJ') if key.startswith(p)), 'unknown')
        print('supabase', method, path.split('?')[0], e.code, e.read()[:300].decode('utf-8', 'replace'),
              f'| key type={kind} length={len(key)}')  # never the key itself
        raise
    return json.loads(raw) if raw else None


# ---------- Telegram ----------
def notify(lead):
    text = (f"🟠 Новая заявка LH47 · {lead.get('source') or 'Сайт'} · {MARKETS.get(lead.get('market') or 'md')}\n\n"
            f"👤 {lead['name']}\n📞 {lead['phone']}\n💬 {lead['comment']}\n\n"
            f"🕒 {local_time(lead['created_at'])}\n№ {lead['id']} · статус: {lead['status']}")
    token = env('TELEGRAM_BOT_TOKEN').removeprefix('bot')
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    body = json.dumps({'chat_id': env('TELEGRAM_CHAT_ID'), 'text': text}).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get('ok')
    except urllib.error.HTTPError as e:  # 404 = bad token, 400/403 = bad chat id or bot not started
        shape = 'ok' if re.fullmatch(r'\d{6,12}:[\w-]{30,}', token) else 'bad'
        print('telegram', e.code, e.read()[:200].decode('utf-8', 'replace'),
              f'| token shape={shape} length={len(token)}')  # never the token itself
        raise


# ---------- Telegram Mini App ----------
SERVICES = ('Эскизный проект', 'Рабочий проект', 'Дизайн интерьера', 'Авторский надзор')
INIT_DATA_DAYS = 1


def telegram_user(init_data, max_age=INIT_DATA_DAYS * 86400):
    """Telegram user dict if initData is signed with our bot token and fresh, else None.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app — the browser can't forge it
    without the token, so the name and id come from Telegram, not from whoever opened the page."""
    try:
        fields = dict(urllib.parse.parse_qsl(str(init_data or ''), strict_parsing=True))
        given = fields.pop('hash')
        check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
        token = env('TELEGRAM_BOT_TOKEN').removeprefix('bot')
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        good = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(given, good) or time.time() - int(fields['auth_date']) > max_age:
            return None
        user = json.loads(fields['user'])
        return user if user.get('id') else None
    except (KeyError, ValueError, TypeError):
        return None


def telegram_name(user):
    return ' '.join(x for x in (user.get('first_name'), user.get('last_name')) if x).strip()[:80] or 'Без имени'


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


def cors(handler):
    """Разрешить форме русского сайта отправлять заявки (только с перечисленных адресов)."""
    origin = handler.headers.get('Origin') or ''
    if origin in ALLOWED_ORIGINS:
        handler.send_header('Access-Control-Allow-Origin', origin)
        handler.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
        handler.send_header('Vary', 'Origin')


def send_json(handler, code, data, headers=()):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    cors(handler)
    for k, v in headers:
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)
