"""POST /api/lead — a visitor's request: validate, save to Supabase with status «новая», notify Telegram."""
import os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = _lib.read_json(self)
        if data.get('website'):  # honeypot field, hidden from people
            return _lib.send_json(self, 200, {'ok': True})
        lead, error = _lib.clean_lead(data)
        if error:
            return _lib.send_json(self, 400, {'ok': False, 'error': error})
        try:
            saved = _lib.supabase('POST', 'leads', dict(lead, status='новая'), prefer='return=representation')[0]
        except Exception as e:
            print('lead save failed:', repr(e))
            return _lib.send_json(self, 500, {'ok': False, 'error': 'Не удалось сохранить заявку. Попробуйте ещё раз или позвоните нам.'})
        try:
            _lib.notify(saved)
        except Exception as e:  # the request is saved anyway; it's visible in the admin panel
            print('telegram failed:', repr(e))
        _lib.send_json(self, 200, {'ok': True, 'id': saved['id']})
