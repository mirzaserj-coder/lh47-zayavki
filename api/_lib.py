"""Shared helpers: Supabase REST, Telegram, admin session cookie, JSON responses.

All keys come from Vercel environment variables, never from the code:
SUPABASE_URL, SUPABASE_SERVICE_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_PASSWORD, ANTHROPIC_API_KEY, GEMINI_API_KEY.
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


def supabase_headers(content_type='application/json'):
    key = supabase_key()
    headers = {'apikey': key, 'Content-Type': content_type}
    if key.startswith('eyJ'):  # legacy service_role JWT; new sb_secret_… keys go in apikey only
        headers['Authorization'] = 'Bearer ' + key
    return headers


def supabase(method, path, body=None, prefer=None):
    url = env('SUPABASE_URL').rstrip('/') + '/rest/v1/' + path
    key = supabase_key()
    headers = supabase_headers()
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


# Originals of scanned documents live in the private Storage bucket «cards»; the admin panel opens them by a
# short-lived signed link, so a file is never public.
CARD_BUCKET = 'cards'


def storage_put(name, data, mime, bucket=CARD_BUCKET):
    url = f"{env('SUPABASE_URL').rstrip('/')}/storage/v1/object/{bucket}/{name}"
    req = urllib.request.Request(url, data=data, method='POST', headers=supabase_headers(mime))
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def storage_link(name, seconds=300, bucket=CARD_BUCKET):
    base = env('SUPABASE_URL').rstrip('/') + '/storage/v1'
    req = urllib.request.Request(f'{base}/object/sign/{bucket}/{name}', method='POST',
                                 data=json.dumps({'expiresIn': seconds}).encode(), headers=supabase_headers())
    with urllib.request.urlopen(req, timeout=10) as r:
        return base + json.load(r)['signedURL']


# ---------- Claude: business cards ----------
CARD_MODEL = 'claude-opus-5-5'
CARD_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'application/pdf': 'pdf'}
CARD_FIELDS = ('name', 'phone', 'company', 'position', 'email', 'website')
CARD_SCHEMA = {
    'type': 'object',
    'properties': {
        'is_business_card': {'type': 'boolean'},
        'reason': {'type': 'string'},
        **{f: {'type': 'string'} for f in CARD_FIELDS},
    },
    'required': ['is_business_card', 'reason', *CARD_FIELDS],
    'additionalProperties': False,
}
CARD_PROMPT = (
    'Это фото или PDF, загруженные в CRM архитектурного бюро после встречи с клиентом. '
    'Определи, визитка ли это (бумажная или электронная визитка человека или компании). '
    'Если да — is_business_card: true и перепиши с неё поля точно как напечатано: name — имя и фамилия человека, '
    'phone — основной телефон с кодом страны, company, position — должность, email, website. '
    'Если поля на визитке нет — пустая строка, ничего не придумывай. '
    'Если это не визитка (пейзаж, человек, чек, пустой лист, нечитаемо) — is_business_card: false, '
    'все поля пустые, а в reason коротко по-русски, что на фото.'
)


def read_card(data, mime):
    """Claude reads a business card → dict with is_business_card, reason and CARD_FIELDS."""
    import anthropic  # imported here: the other functions don't need the SDK
    source = {'type': 'base64', 'media_type': mime, 'data': base64.standard_b64encode(data).decode()}
    block = {'type': 'document' if mime == 'application/pdf' else 'image', 'source': source}
    client = anthropic.Anthropic(api_key=env('ANTHROPIC_API_KEY'), timeout=50, max_retries=1)
    response = client.beta.messages.create(
        model=CARD_MODEL, max_tokens=4000,
        betas=['server-side-fallback-2026-07-01'], fallbacks='default',
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': CARD_SCHEMA}},
        messages=[{'role': 'user', 'content': [block, {'type': 'text', 'text': CARD_PROMPT}]}],
    )
    if response.stop_reason != 'end_turn':
        raise RuntimeError(f'Claude stopped: {response.stop_reason}')
    return json.loads(next(b.text for b in response.content if b.type == 'text'))


def card_comment(card):
    labels = {'company': 'Компания', 'position': 'Должность', 'email': 'Email', 'website': 'Сайт'}
    return '\n'.join(f'{t}: {card[k].strip()}' for k, t in labels.items() if card.get(k, '').strip())


# ---------- Nano Banana: house sketches ----------
SKETCH_BUCKET = 'sketches'
SKETCH_MODEL = 'gemini-nano-banana-2.1'
SKETCH_DAILY_LIMIT = 5
SKETCH_STYLES = {
    'Современный': 'modern minimalist house with large panoramic windows and a flat roof',
    'Барнхаус': 'barnhouse with a steep gable roof, dark metal and wood cladding',
    'Скандинавский': 'Scandinavian house with light timber facade and a pitched roof',
    'Средиземноморский': 'Mediterranean villa with light stucco walls, terracotta roof and terraces',
}


def make_sketch(photo, mime, style, wish):
    """Nano Banana draws a house on the client's photo of the plot → (jpeg/png bytes, mime)."""
    prompt = (
        'Architectural exterior visualization by LH47 architecture bureau. On this photo of the land plot, '
        f'design and place a new {SKETCH_STYLES[style]}. Keep the real surroundings, terrain, trees, perspective '
        'and lighting of the photo; the house must sit naturally on the plot at a believable scale. '
        + (f'Client wishes (in Russian): {wish}. ' if wish else '') +
        'Photorealistic, daylight, no people, no text, no watermarks.'
    )
    body = {'contents': [{'parts': [{'inline_data': {'mime_type': mime, 'data': base64.b64encode(photo).decode()}},
                                    {'text': prompt}]}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': '4:3'}}}
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{SKETCH_MODEL}:generateContent'
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'x-goog-api-key': env('GEMINI_API_KEY')})
    try:
        with urllib.request.urlopen(req, timeout=110) as r:
            result = json.load(r)
    except urllib.error.HTTPError as e:  # bad key, no billing, wrong model — Google says which in the body
        print('gemini', e.code, e.read()[:400].decode('utf-8', 'replace'))
        raise
    for cand in result.get('candidates') or []:
        for part in (cand.get('content') or {}).get('parts') or []:
            data = part.get('inlineData') or part.get('inline_data')
            if data and data.get('data'):
                return base64.b64decode(data['data']), data.get('mimeType') or data.get('mime_type') or 'image/png'
    print('gemini: no image', json.dumps(result)[:400])
    return None, None


def day_start_utc():
    """Midnight in Chisinau as a UTC ISO string — the daily limit resets at local midnight."""
    now = datetime.now(TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(timespec='seconds')


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


def tg_api(method, body):
    token = env('TELEGRAM_BOT_TOKEN').removeprefix('bot')
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}') or {'ok': False, 'error_code': e.code}


def webhook_secret():
    # Telegram echoes it in X-Telegram-Bot-Api-Secret-Token, so only Telegram can post updates to /api/tgbot.
    return hashlib.sha256(('lh47-webhook:' + env('TELEGRAM_BOT_TOKEN')).encode()).hexdigest()[:48]


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
def read_json(handler, limit=20000):
    n = int(handler.headers.get('Content-Length') or 0)
    if n > limit:
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
