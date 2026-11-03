"""POST /api/lead — a visitor's request: validate, save to the CRM on the first stage with source «Сайт», notify Telegram."""
import os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # предзапрос браузера с русского сайта
        self.send_response(204)
        _lib.cors(self)
        self.end_headers()

    def do_POST(self):
        data = _lib.read_json(self)
        if data.get('website'):  # honeypot field, hidden from people
            return _lib.send_json(self, 200, {'ok': True})
        lead, error = _lib.clean_lead(data)
        if error:
            return _lib.send_json(self, 400, {'ok': False, 'error': error})
        try:
            saved = _lib.supabase('POST', 'leads', _lib.new_lead(lead, 'Сайт'), prefer='return=representation')[0]
        except Exception as e:
            print('lead save failed:', repr(e))
            return _lib.send_json(self, 500, {'ok': False, 'error': 'Не удалось сохранить заявку. Попробуйте ещё раз или позвоните нам.'})
        try:
            _lib.notify(saved)
        except Exception as e:  # the request is saved anyway; it's visible in the admin panel
            print('telegram failed:', repr(e))
        _lib.send_json(self, 200, {'ok': True, 'id': saved['id']})
