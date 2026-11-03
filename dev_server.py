"""Local preview without Supabase and Telegram: python3 dev_server.py → http://localhost:8047 (admin password: dev).

Serves public/ like Vercel and runs the same api/*.py handlers; the database and the Telegram bot are replaced
by an in-memory list and a console print.
"""
import importlib, itertools, json, os, sys, urllib.parse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'api'))
os.environ.setdefault('ADMIN_PASSWORD', 'dev')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '123456:dev-token')  # fake: signs the test initData from /dev-initdata
import _lib

tables, ids = {}, itertools.count(1)


def fake_supabase(method, path, body=None, prefer=None):
    rows = tables.setdefault(path.split('?')[0], [])  # «leads», «generations»
    q = urllib.parse.parse_qs(urllib.parse.urlparse('/' + path).query)
    eq = {k: v[0].removeprefix('eq.') for k, v in q.items() if v[0].startswith('eq.')}
    if method == 'POST':
        row = dict(body, id=next(ids), created_at=datetime.now(timezone.utc).isoformat())
        rows.append(row)
        return [row]
    if method == 'GET':
        hit = [r for r in rows if all(str(r.get(k)) == v for k, v in eq.items())]
        return sorted(hit, key=lambda r: r['created_at'], reverse=True)
    if method == 'PATCH':
        hit = [r for r in rows if all(str(r.get(k)) == v for k, v in eq.items())]
        for r in hit:
            r.update(body)
        return hit


def sign_init_data(user, auth_date=None):
    import hashlib, hmac, time
    fields = {'auth_date': str(auth_date or int(time.time())), 'query_id': 'dev', 'user': json.dumps(user, ensure_ascii=False)}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', os.environ['TELEGRAM_BOT_TOKEN'].encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


_lib.supabase = fake_supabase
_lib.notify = lambda lead: print('TELEGRAM →', json.dumps(lead, ensure_ascii=False))
# Claude and Storage are faked too: a plain (small) picture is «not a document», a detailed one «is» a business card.
_lib.read_card = lambda data, mime: {'is_business_card': len(data) > 20000, 'reason': 'на фото пейзаж',
                                     'name': 'Ион Попеску', 'phone': '+373 69 777 888', 'company': 'Vinaria SRL',
                                     'position': 'директор', 'email': 'ion@vinaria.md', 'website': ''}
_lib.storage_link = lambda name, seconds=300, bucket=None: '/img/p3274_01.jpg' if 'sketch' in name else '/img/logo.svg'
_lib.storage_put = lambda name, data, mime, bucket=None: print('STORAGE ←', bucket or 'cards', name, len(data), 'bytes')
_lib.make_sketch = lambda photo, mime, style, wish: (b'fake-image', 'image/jpeg')  # Nano Banana faked: no key locally
handlers = {n: importlib.import_module(n).handler for n in ('lead', 'leads', 'login', 'tg', 'card')}


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(ROOT, 'public'), **kw)

    def route(self, verb):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/'):
            h = handlers.get(path[5:])
            if not h or not hasattr(h, 'do_' + verb):
                return self.send_error(404 if not h else 405)
            return getattr(h, 'do_' + verb)(self)
        if verb != 'GET':
            return self.send_error(405)
        if path in ('/admin', '/app'):  # Vercel cleanUrls
            self.path = path + '.html'
        if path == '/dev-initdata':  # initData as Telegram would sign it, for opening /app#tgWebAppData=… locally
            body = sign_init_data({'id': 42, 'first_name': 'Сергей', 'username': 'lh47_test'}).encode()
            self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8'); self.end_headers()
            return self.wfile.write(body)
        super().do_GET()

    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PATCH(self): self.route('PATCH')
    def do_DELETE(self): self.route('DELETE')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8047))
    print(f'http://localhost:{port}  (admin password: {os.environ["ADMIN_PASSWORD"]})')
    ThreadingHTTPServer(('127.0.0.1', port), Dev).serve_forever()
