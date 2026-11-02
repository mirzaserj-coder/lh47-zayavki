"""GET /kp/<token> — постоянная ссылка и QR-код коммерческого предложения LH47.

Сам сайт КП работает на компьютере бюро через туннель, и его адрес меняется при перезапуске. Бот КП кладёт
текущий адрес и PDF каждого КП в публичное хранилище Supabase (bucket «kp»). Эта функция ведёт клиента на живую
страницу КП, а если компьютер бюро недоступен — на сохранённый PDF.
"""
import html, os, re, sys, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


def public(path):
    return _lib.env('SUPABASE_URL').rstrip('/') + '/storage/v1/object/public/kp/' + path


def get(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': 'lh47-kp-link'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(200)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        token = (q.get('t') or [''])[0]
        if not re.fullmatch(r'[\w-]{8,40}', token):
            return self.page(404, 'Ссылка на предложение неверная.')
        try:  # живая страница КП: отметка «клиент открыл», кнопка «Согласен»
            _, base = get(public('_base_url.txt'), 4)
            base = base.decode().strip()
            if base.startswith('https://') and get(f'{base}/o/{token}/alive', 5)[0] == 200:
                return self.go(f'{base}/o/{token}')
        except Exception as e:
            print('kp live page unavailable:', repr(e)[:200])
        try:  # компьютер бюро выключен — PDF из хранилища
            if get(public(f'{token}.pdf'), 5)[0] == 200:
                return self.go(public(f'{token}.pdf'))
        except Exception as e:
            print('kp pdf unavailable:', repr(e)[:200])
        self.page(503, 'Предложение временно недоступно. Попробуйте чуть позже или напишите нам: info@lh47arch.com')

    def go(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def page(self, code, text):
        body = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>LH47 — коммерческое предложение</title><body style="font:16px/1.5 Arial,sans-serif;max-width:520px;'
                f'margin:15vh auto;padding:0 20px;color:#141416"><b style="color:#FE4206">LH47 ARCH</b><p>{html.escape(text)}</p>').encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
