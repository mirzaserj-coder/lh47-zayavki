import os, sys, time, unittest
os.environ['TELEGRAM_BOT_TOKEN'] = '123456:test-token'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
os.environ['ADMIN_PASSWORD'] = 'test-password'
import _lib


class LeadValidation(unittest.TestCase):
    def test_empty_form_is_rejected(self):
        self.assertIsNone(_lib.clean_lead({})[0])

    def test_good_lead(self):
        lead, err = _lib.clean_lead({'name': '  Иван   Петров ', 'phone': '+373 69 123 456', 'comment': 'Дом 200 м²'})
        self.assertIsNone(err)
        self.assertEqual(lead['name'], 'Иван Петров')

    def test_bad_phone(self):
        for phone in ('123', 'abc-defg-hij', '+1' + '2' * 20):
            self.assertIsNotNone(_lib.clean_lead({'name': 'Иван', 'phone': phone, 'comment': 'дом'})[1], phone)

    def test_market(self):
        lead, err = _lib.clean_lead({'name': 'Пётр', 'phone': '@petr_msk', 'comment': 'Тип проекта: Частный дом', 'market': 'ru'})
        self.assertIsNone(err)
        self.assertEqual(lead['market'], 'ru')
        self.assertEqual(_lib.clean_lead({'name': 'Ion', 'phone': '+373 69 123 456', 'comment': 'casa', 'market': 'xx'})[0]['market'], 'md')

    def test_chisinau_time(self):
        self.assertEqual(_lib.local_time('2026-10-27T18:05:00+00:00'), '27.10.2026 20:05')


class Funnel(unittest.TestCase):
    def test_manual_client_needs_no_comment(self):
        self.assertIsNotNone(_lib.clean_lead({'name': 'Ион', 'phone': '+373 69 123 456'})[1])
        lead, err = _lib.clean_lead({'name': 'Ион', 'phone': '+373 69 123 456'}, manual=True)
        self.assertIsNone(err)

    def test_new_lead_starts_on_first_stage(self):
        row = _lib.new_lead({'name': 'Ион'}, 'Вручную')
        self.assertEqual((row['status'], row['source'], row['notes']), ('Новая', 'Вручную', ''))
        self.assertEqual([h['stage'] for h in row['history']], ['Новая'])

    def test_move_appends_history(self):
        row = _lib.new_lead({'name': 'Ион'}, 'Сайт')
        patch = _lib.move(row, 'Оплачено')
        self.assertEqual(patch['status'], 'Оплачено')
        self.assertEqual([h['stage'] for h in patch['history']], ['Новая', 'Оплачено'])
        self.assertEqual(len(row['history']), 1)  # the original row is untouched
        _lib.local_time(patch['history'][-1]['at'])  # stored time is readable back


class BusinessCard(unittest.TestCase):
    def test_comment_skips_empty_fields(self):
        card = {'company': 'Vinaria SRL', 'position': ' ', 'email': 'ion@vinaria.md', 'website': ''}
        self.assertEqual(_lib.card_comment(card), 'Компания: Vinaria SRL\nEmail: ion@vinaria.md')

    def test_schema_requires_every_field(self):
        self.assertEqual(set(_lib.CARD_SCHEMA['required']), set(_lib.CARD_SCHEMA['properties']))


class Sketch(unittest.TestCase):
    def test_day_starts_at_chisinau_midnight(self):
        from datetime import datetime
        start = datetime.fromisoformat(_lib.day_start_utc()).astimezone(_lib.TZ)
        self.assertEqual((start.hour, start.minute), (0, 0))

    def test_limit_is_enforced(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
        import tg
        calls = []
        _lib_supabase, _lib.supabase = _lib.supabase, lambda m, p, b=None, prefer=None: calls.append(p) or [{}] * 5
        try:
            self.assertEqual(tg.sketches_today(42), 5)
            self.assertIn('tg_id=eq.42', calls[0])
            self.assertIn('created_at=gte.', calls[0])
        finally:
            _lib.supabase = _lib_supabase


class TelegramInitData(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from dev_server import sign_init_data
        self.sign = sign_init_data

    def test_signed_user_is_accepted(self):
        user = _lib.telegram_user(self.sign({'id': 7, 'first_name': 'Сергей', 'last_name': 'М'}))
        self.assertEqual((user['id'], _lib.telegram_name(user)), (7, 'Сергей М'))

    def test_forged_or_old_is_rejected(self):
        good = self.sign({'id': 7, 'first_name': 'Сергей'})
        self.assertIn('%D0%A1', good)  # «С» of «Сергей»
        self.assertIsNone(_lib.telegram_user(good.replace('%D0%A1', '%D0%9F', 1)))  # name changed in the browser
        self.assertIsNone(_lib.telegram_user(good + 'x'))
        self.assertIsNone(_lib.telegram_user(self.sign({'id': 7}, auth_date=int(time.time()) - 3 * 86400)))
        self.assertIsNone(_lib.telegram_user(''))
        self.assertIsNone(_lib.telegram_user('user=%7B%22id%22%3A1%7D&auth_date=1'))


class Session(unittest.TestCase):
    def test_round_trip(self):
        self.assertTrue(_lib.valid_session(_lib.make_session()))

    def test_forged_or_expired(self):
        exp, sig = _lib.make_session().split('.')
        self.assertFalse(_lib.valid_session(f'{int(exp) + 1}.{sig}'))
        self.assertFalse(_lib.valid_session(''))
        self.assertFalse(_lib.valid_session(f'{int(time.time()) - 10}.{sig}'))

    def test_password(self):
        self.assertTrue(_lib.password_ok('test-password'))
        self.assertFalse(_lib.password_ok('nope'))


if __name__ == '__main__':
    unittest.main()
