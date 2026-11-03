"""Admin only — business cards → CRM.

POST /api/card {file: base64, mime} — Claude reads the card. Not a card → 422 and nothing is stored;
                                     a card → the original goes to Storage, the fields come back for review.
GET  /api/card?id=<lead id>        — open the original of that client's card (short-lived signed link).
The client itself is saved by POST /api/leads {…, doc} after the manager has checked the fields.
"""
import base64, binascii, os, secrets, sys, urllib.parse
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib

MAX_BYTES = 3_300_000  # Vercel accepts up to 4.5 MB per request, base64 adds a third


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        data = _lib.read_json(self, limit=4_600_000)
        mime = data.get('mime')
        if mime not in _lib.CARD_TYPES:
            return _lib.send_json(self, 400, {'error': 'Загрузите фото (JPG, PNG) или PDF.'})
        try:
            raw = base64.b64decode(data.get('file') or '', validate=True)
        except (binascii.Error, ValueError):
            raw = b''
        if not raw or len(raw) > MAX_BYTES:
            return _lib.send_json(self, 400, {'error': 'Файл пустой или больше 3 МБ.'})
        try:
            card = _lib.read_card(raw, mime)
        except Exception as e:
            print('card read failed:', repr(e))
            return _lib.send_json(self, 502, {'error': 'Не удалось распознать файл. Попробуйте ещё раз.'})
        if not card.get('is_business_card'):
            reason = card.get('reason', '').strip().rstrip('.')
            return _lib.send_json(self, 422, {'error': 'Это не похоже на визитку' + (f' — {reason}' if reason else '') +
                                              '. Ничего не сохранено, загрузите фото визитки.'})
        name = f'{secrets.token_hex(12)}.{_lib.CARD_TYPES[mime]}'
        try:
            _lib.storage_put(name, raw, mime)
        except Exception as e:
            print('card upload failed:', repr(e))
            return _lib.send_json(self, 500, {'error': 'Не удалось сохранить оригинал визитки.'})
        fields = {k: str(card.get(k) or '').strip() for k in ('name', 'phone')}
        _lib.send_json(self, 200, {'card': dict(fields, comment=_lib.card_comment(card)), 'doc': name})

    def do_GET(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход'})
        lead_id = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('id') or [''])[0]
        rows = _lib.supabase('GET', f'leads?select=doc&id=eq.{int(lead_id)}') if lead_id.isdigit() else []
        if not rows or not rows[0].get('doc'):
            return _lib.send_json(self, 404, {'error': 'У этого клиента нет документа'})
        self.send_response(302)
        self.send_header('Location', _lib.storage_link(rows[0]['doc']))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
