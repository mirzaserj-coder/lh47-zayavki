import os, sys, time, unittest
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

    def test_chisinau_time(self):
        self.assertEqual(_lib.local_time('2026-10-27T18:05:00+00:00'), '27.10.2026 20:05')


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
