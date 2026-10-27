"""POST /api/login {password} → admin session cookie; DELETE /api/login → log out; GET → am I logged in."""
import os, sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _lib.send_json(self, 200, {'admin': _lib.is_admin(self)})

    def do_POST(self):
        if not _lib.password_ok(_lib.read_json(self).get('password', '')):
            return _lib.send_json(self, 401, {'ok': False, 'error': 'Неверный пароль'})
        cookie = _lib.session_cookie(_lib.make_session(), _lib.SESSION_DAYS * 86400)
        _lib.send_json(self, 200, {'ok': True}, [('Set-Cookie', cookie)])

    def do_DELETE(self):
        _lib.send_json(self, 200, {'ok': True}, [('Set-Cookie', _lib.session_cookie('', 0))])
