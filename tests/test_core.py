import tempfile
import unittest
from pathlib import Path

from whatsapp_photo_renamer.core import parse_chat, process


class CoreTests(unittest.TestCase):
    def test_parse_caption_same_line_and_continuation(self):
        text = (
            "12/03/2024, 10:15 - Ana: IMG-001.jpg (file attached)\n"
            "Pulsera / Plata: 925\n"
            "12/03/2024, 10:16 - Ana: IMG-002.PNG (file attached)\n"
        )
        rows = parse_chat(text)
        self.assertEqual(rows[0].filename, "IMG-001.jpg")
        self.assertEqual(rows[0].caption, "Pulsera _ Plata_ 925")
        self.assertEqual(rows[1].filename, "IMG-002.PNG")

    def test_process_copies_and_suffixes_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "media"
            output = root / "out"
            media.mkdir()
            (media / "a.jpg").write_bytes(b"a")
            (media / "b.JPG").write_bytes(b"b")
            chat = root / "_chat.txt"
            chat.write_text(
                "1/1/24, 1:00 - A: a.jpg (file attached)\nProducto\n"
                "1/1/24, 1:01 - A: b.JPG (file attached)\nProducto\n",
                encoding="utf-8",
            )
            rows = process(media, output, chat)
            self.assertEqual([r.output for r in rows], ["Producto.jpg", "Producto_2.JPG"])
            self.assertEqual((output / "Producto.jpg").read_bytes(), b"a")
            self.assertEqual((output / "Producto_2.JPG").read_bytes(), b"b")

    def test_unmatched_media_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "media"
            media.mkdir()
            (media / "orphan.png").write_bytes(b"x")
            chat = root / "_chat.txt"
            chat.write_text("1/1/24, 1:00 - A: missing.jpg (file attached)\n", encoding="utf-8")
            rows = process(media, root / "out", chat)
            self.assertEqual(rows[0].status, "not_in_chat")
            self.assertEqual(rows[1].status, "missing_media")

    def test_parse_ios_export_with_invisible_prefix_and_adjunto_marker(self):
        text = "\u200e[9/28/26, 2:13:18 p. m.] Stephanie: Filial #15 \u200e<adjunto: 00000009-PHOTO-2026-09-28-14-13-18.jpg>\n"
        rows = parse_chat(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].filename, "00000009-PHOTO-2026-09-28-14-13-18.jpg")
        self.assertEqual(rows[0].caption, "Filial #15")


if __name__ == "__main__":
    unittest.main()
