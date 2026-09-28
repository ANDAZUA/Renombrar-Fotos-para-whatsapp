import io
import json
import unittest
import zipfile

from whatsapp_photo_renamer.webapp import process_upload, safe_extract_zip


class WebAppTests(unittest.TestCase):
    def make_zip(self, files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_process_upload_returns_downloadable_zip_and_summary(self):
        payload = self.make_zip(
            {
                "_chat.txt": "1/1/24, 1:00 - Ana: IMG-001.jpg (file attached)\nPulsera Plata 925\n",
                "Media/IMG-001.jpg": b"fake-image",
            }
        )
        result_zip, summary = process_upload(payload)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["errors"], 0)
        with zipfile.ZipFile(io.BytesIO(result_zip)) as archive:
            self.assertIn("Pulsera Plata 925.jpg", archive.namelist())
            self.assertIn("report.csv", archive.namelist())
            self.assertIn("report.json", archive.namelist())

    def test_safe_extract_rejects_path_traversal(self):
        payload = self.make_zip({"../outside.txt": "blocked"})
        with self.assertRaises(ValueError):
            safe_extract_zip(payload)

    def test_process_upload_rejects_non_zip(self):
        with self.assertRaises(ValueError):
            process_upload(b"not a zip")


if __name__ == "__main__":
    unittest.main()
