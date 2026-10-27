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
import _lib

rows, ids = [], itertools.count(1)


def fake_supabase(method, path, body=None, prefer=None):
    q = urllib.parse.parse_qs(urllib.parse.urlparse('/' + path).query)
    if method == 'POST':
        row = dict(body, id=next(ids), created_at=datetime.now(timezone.utc).isoformat())
        rows.append(row)
        return [row]
    if method == 'GET':
        st = (q.get('status') or [''])[0].removeprefix('eq.')
        return sorted((r for r in rows if not st or r['status'] == st), key=lambda r: r['created_at'], reverse=True)
    if method == 'PATCH':
        lid = int(q['id'][0].removeprefix('eq.'))
        hit = [r for r in rows if r['id'] == lid]
        for r in hit:
            r.update(body)
        return hit


_lib.supabase = fake_supabase
_lib.notify = lambda lead: print('TELEGRAM →', json.dumps(lead, ensure_ascii=False))
handlers = {n: importlib.import_module(n).handler for n in ('lead', 'leads', 'login')}


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
        if path == '/admin':  # Vercel cleanUrls
            self.path = '/admin.html'
        super().do_GET()

    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PATCH(self): self.route('PATCH')
    def do_DELETE(self): self.route('DELETE')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8047))
    print(f'http://localhost:{port}  (admin password: {os.environ["ADMIN_PASSWORD"]})')
    ThreadingHTTPServer(('127.0.0.1', port), Dev).serve_forever()
