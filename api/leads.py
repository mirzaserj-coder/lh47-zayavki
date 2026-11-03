"""Admin only — the CRM.

GET   /api/leads                      — all clients, newest first;
POST  /api/leads {name, phone, comment, doc?} — add a client by hand (source «Вручную»), or from a business card
                                        checked by the manager (doc from /api/card → source «Визитка»);
PATCH /api/leads {id, status?, notes?} — move to another stage (recorded in the history) and/or save notes.
"""
import os, re, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


def view(row):
    history = [dict(h, local_time=_lib.local_time(h['at'])) for h in row.get('history') or []]
    return dict(row, local_time=_lib.local_time(row['created_at']), history=history)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        rows = _lib.supabase('GET', 'leads?select=*&order=created_at.desc&limit=1000')
        _lib.send_json(self, 200, {'leads': [view(r) for r in rows], 'stages': _lib.STAGES})

    def do_POST(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        data = _lib.read_json(self)
        lead, error = _lib.clean_lead(data, manual=True)
        if error:
            return _lib.send_json(self, 400, {'error': error})
        doc = str(data.get('doc') or '')
        row = _lib.new_lead(lead, 'Вручную')
        if re.fullmatch(r'[0-9a-f]{24}\.(jpg|png|webp|pdf)', doc):
            row.update(source='Визитка', doc=doc)
        saved = _lib.supabase('POST', 'leads', row, prefer='return=representation')[0]
        _lib.send_json(self, 200, {'lead': view(saved)})

    def do_PATCH(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        data = _lib.read_json(self)
        lead_id = data.get('id')
        if not str(lead_id).isdigit():
            return _lib.send_json(self, 400, {'error': 'Нет номера клиента'})
        rows = _lib.supabase('GET', f'leads?select=*&id=eq.{int(lead_id)}')
        if not rows:
            return _lib.send_json(self, 404, {'error': 'Клиент не найден'})
        patch = {}
        if 'status' in data:
            if data['status'] not in _lib.STAGES:
                return _lib.send_json(self, 400, {'error': 'Неизвестный этап'})
            if data['status'] != rows[0]['status']:
                patch.update(_lib.move(rows[0], data['status']))
        if 'notes' in data:
            notes = str(data['notes'] or '').strip()
            if len(notes) > 5000:
                return _lib.send_json(self, 400, {'error': 'Заметка длиннее 5000 символов'})
            patch['notes'] = notes
        if patch:
            rows = _lib.supabase('PATCH', f'leads?id=eq.{int(lead_id)}', patch, prefer='return=representation')
        _lib.send_json(self, 200, {'lead': view(rows[0])})
