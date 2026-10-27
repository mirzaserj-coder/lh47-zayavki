"""Admin only. GET /api/leads[?status=новая] — list, newest first; PATCH /api/leads {id, status} — change status."""
import os, sys, urllib.parse
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


def view(row):
    return dict(row, local_time=_lib.local_time(row['created_at']))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        path = 'leads?select=*&order=created_at.desc&limit=500'
        status = (q.get('status') or [''])[0]
        if status in _lib.STATUSES:
            path += '&status=eq.' + urllib.parse.quote(status)
        rows = _lib.supabase('GET', path)
        _lib.send_json(self, 200, {'leads': [view(r) for r in rows]})

    def do_PATCH(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        data = _lib.read_json(self)
        status, lead_id = data.get('status'), data.get('id')
        if status not in _lib.STATUSES or not str(lead_id).isdigit():
            return _lib.send_json(self, 400, {'error': 'Неверный статус'})
        rows = _lib.supabase('PATCH', f'leads?id=eq.{int(lead_id)}', {'status': status}, prefer='return=representation')
        if not rows:
            return _lib.send_json(self, 404, {'error': 'Заявка не найдена'})
        _lib.send_json(self, 200, {'lead': view(rows[0])})
