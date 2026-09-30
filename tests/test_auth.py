import unittest

from whatsapp_photo_renamer.auth import SessionStore, hash_password, verify_password


class AuthTests(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = hash_password("Una contraseña segura 2026")
        self.assertTrue(verify_password("Una contraseña segura 2026", encoded))
        self.assertFalse(verify_password("incorrecta", encoded))

    def test_session_store_expires_and_revokes(self):
        store = SessionStore(ttl_seconds=60)
        token = store.create("equipo")
        self.assertEqual(store.get(token).username, "equipo")
        store.revoke(token)
        self.assertIsNone(store.get(token))


if __name__ == "__main__":
    unittest.main()
