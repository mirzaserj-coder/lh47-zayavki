"""@lh47_zayavki_bot: replies to /start with a button that opens the Mini App.

POST /api/tgbot          — Telegram webhook (checked by the secret header);
GET  /api/tgbot?setup=1  — admin only: point the bot's webhook here and set the menu button to the Mini App.
"""
import hmac, os, sys, urllib.parse
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib

BOT = 'lh47_zayavki_bot'
SITE = 'https://lh47-zayavki.vercel.app'
APP = SITE + '/app'


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('X-Telegram-Bot-Api-Secret-Token') or '', _lib.webhook_secret()):
            return _lib.send_json(self, 403, {'ok': False})
        msg = _lib.read_json(self).get('message') or {}
        chat = (msg.get('chat') or {}).get('id')
        if chat and msg.get('chat', {}).get('type') == 'private':
            name = (msg.get('from') or {}).get('first_name') or ''
            _lib.tg_api('sendMessage', {
                'chat_id': chat,
                'text': f'Здравствуйте{", " + name if name else ""}! Это архитектурное бюро LH47.\n\n'
                        'Нажмите кнопку ниже — выберите услугу и оставьте заявку, архитектор свяжется с вами '
                        'в течение рабочего дня.',
                'reply_markup': {'inline_keyboard': [[{'text': '📐 Оставить заявку', 'web_app': {'url': APP}}]]}})
        _lib.send_json(self, 200, {'ok': True})

    def do_GET(self):
        if not _lib.is_admin(self):
            return _lib.send_json(self, 401, {'error': 'Нужен вход в админку'})
        if 'setup' not in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query):
            return _lib.send_json(self, 200, {'webhook': _lib.tg_api('getWebhookInfo', {}).get('result')})
        me = (_lib.tg_api('getMe', {}).get('result') or {}).get('username')
        if me != BOT:  # never repoint some other bot that may be polling with this token
            return _lib.send_json(self, 400, {'error': f'Токен в Vercel от бота @{me}, а не @{BOT}'})
        hook = _lib.tg_api('setWebhook', {'url': SITE + '/api/tgbot', 'secret_token': _lib.webhook_secret(),
                                          'allowed_updates': ['message'], 'drop_pending_updates': True})
        menu = _lib.tg_api('setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Заявка', 'web_app': {'url': APP}}})
        _lib.send_json(self, 200, {'bot': '@' + me, 'webhook': hook, 'menu_button': menu})
