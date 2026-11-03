"""Telegram Mini App. Every call carries Telegram initData, checked on the server with the bot token.

POST /api/tg {initData}                                   → {user, services, styles, sketches_left} — who opened the app;
POST /api/tg {initData, service, phone, comment, send: 1} → the request goes to the CRM with source «Telegram»;
POST /api/tg {initData, sketch: 1, photo, mime, style, wish} → Nano Banana draws a house on the plot photo
                                                            (5 a day per Telegram user), saved to the history;
POST /api/tg {initData, history: 1}                       → this user's sketches, newest first.
Without valid initData (the page opened in an ordinary browser) → 401 and nothing else.
"""
import base64, binascii, os, secrets, sys, urllib.parse
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(__file__))
import _lib

PHOTO_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


def sketches_today(tg_id):
    since = urllib.parse.quote(_lib.day_start_utc())  # «+00:00» would read as a space
    rows = _lib.supabase('GET', f'generations?select=id&tg_id=eq.{tg_id}&created_at=gte.{since}')
    return len(rows)


def history(tg_id):
    rows = _lib.supabase('GET', f'generations?select=*&tg_id=eq.{tg_id}&order=created_at.desc&limit=20')
    return [{'id': r['id'], 'style': r['style'], 'wish': r['wish'], 'local_time': _lib.local_time(r['created_at']),
             'result': _lib.storage_link(r['result'], 3600, _lib.SKETCH_BUCKET),
             'photo': _lib.storage_link(r['photo'], 3600, _lib.SKETCH_BUCKET)} for r in rows]


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = _lib.read_json(self, limit=4_600_000)
        user = _lib.telegram_user(data.get('initData'))
        if not user:
            return _lib.send_json(self, 401, {'error': 'Откройте приложение через бота LH47 в Telegram.'})
        name, username = _lib.telegram_name(user), user.get('username') or ''
        if data.get('sketch'):
            return sketch(self, data, user, name)
        if data.get('history'):
            return _lib.send_json(self, 200, {'sketches': history(user['id'])})
        if not data.get('send'):
            return _lib.send_json(self, 200, {
                'user': {'name': name, 'username': username}, 'services': _lib.SERVICES,
                'styles': list(_lib.SKETCH_STYLES), 'limit': _lib.SKETCH_DAILY_LIMIT,
                'sketches_left': max(0, _lib.SKETCH_DAILY_LIMIT - sketches_today(user['id']))})
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


def sketch(self, data, user, name):
    style, wish, mime = data.get('style'), str(data.get('wish') or '').strip()[:500], data.get('mime')
    if style not in _lib.SKETCH_STYLES:
        return _lib.send_json(self, 400, {'error': 'Выберите стиль дома.'})
    if mime not in PHOTO_TYPES:
        return _lib.send_json(self, 400, {'error': 'Загрузите фото участка (JPG или PNG).'})
    try:
        photo = base64.b64decode(data.get('photo') or '', validate=True)
    except (binascii.Error, ValueError):
        photo = b''
    if not photo or len(photo) > 3_300_000:
        return _lib.send_json(self, 400, {'error': 'Фото пустое или больше 3 МБ.'})
    used = sketches_today(user['id'])
    if used >= _lib.SKETCH_DAILY_LIMIT:
        return _lib.send_json(self, 429, {'error': f'На сегодня все {_lib.SKETCH_DAILY_LIMIT} эскизов использованы. '
                                          'Новые станут доступны завтра — а пока можно оставить заявку архитектору.',
                                          'sketches_left': 0})
    try:
        image, image_mime = _lib.make_sketch(photo, mime, style, wish)
    except Exception as e:
        print('sketch failed:', repr(e))
        return _lib.send_json(self, 502, {'error': 'Нейросеть сейчас не ответила. Попробуйте ещё раз через минуту.'})
    if not image:
        return _lib.send_json(self, 422, {'error': 'Не получилось нарисовать эскиз по этому фото. '
                                          'Попробуйте другое фото участка или измените пожелания.'})
    key = secrets.token_hex(12)
    photo_name = f'{key}-plot.{PHOTO_TYPES[mime]}'
    result_name = f'{key}-sketch.{"jpg" if image_mime == "image/jpeg" else "png"}'
    try:
        _lib.storage_put(photo_name, photo, mime, _lib.SKETCH_BUCKET)
        _lib.storage_put(result_name, image, image_mime, _lib.SKETCH_BUCKET)
        _lib.supabase('POST', 'generations', {'tg_id': user['id'], 'tg_name': name, 'style': style, 'wish': wish,
                                              'photo': photo_name, 'result': result_name})
    except Exception as e:
        print('sketch save failed:', repr(e))
        return _lib.send_json(self, 500, {'error': 'Эскиз готов, но не сохранился. Попробуйте ещё раз.'})
    _lib.send_json(self, 200, {'result': _lib.storage_link(result_name, 3600, _lib.SKETCH_BUCKET),
                               'sketches_left': _lib.SKETCH_DAILY_LIMIT - used - 1})
