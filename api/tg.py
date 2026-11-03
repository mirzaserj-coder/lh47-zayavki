"""Telegram Mini App. Every call carries Telegram initData, checked on the server with the bot token.

POST /api/tg {initData}                                  → {user: {name, username}} — who opened the app;
POST /api/tg {initData, service, phone, comment, send: 1} → the request goes to the CRM with source «Telegram».
Without valid initData (the page opened in an ordinary browser) → 401 and nothing else.
"""
import os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = _lib.read_json(self)
        user = _lib.telegram_user(data.get('initData'))
        if not user:
            return _lib.send_json(self, 401, {'error': 'Откройте приложение через бота LH47 в Telegram.'})
        name, username = _lib.telegram_name(user), user.get('username') or ''
        if not data.get('send'):
            return _lib.send_json(self, 200, {'user': {'name': name, 'username': username}, 'services': _lib.SERVICES})
        service = data.get('service')
        if service not in _lib.SERVICES:
            return _lib.send_json(self, 400, {'error': 'Выберите услугу.'})
        details = str(data.get('comment') or '').strip()
        comment = f'Услуга: {service}' + (f'\n{details}' if details else '') + \
                  f'\nTelegram: {"@" + username if username else "id " + str(user["id"])}'
        lead, error = _lib.clean_lead({'name': name, 'phone': str(data.get('phone') or '').strip() or '@' + username,
                                       'comment': comment})
        if error:
            return _lib.send_json(self, 400, {'error': error})
        try:
            saved = _lib.supabase('POST', 'leads', _lib.new_lead(lead, 'Telegram'), prefer='return=representation')[0]
        except Exception as e:
            print('tg lead save failed:', repr(e))
            return _lib.send_json(self, 500, {'error': 'Не удалось сохранить заявку. Попробуйте ещё раз.'})
        try:
            _lib.notify(saved)
        except Exception as e:
            print('telegram failed:', repr(e))
        _lib.send_json(self, 200, {'ok': True, 'id': saved['id']})
