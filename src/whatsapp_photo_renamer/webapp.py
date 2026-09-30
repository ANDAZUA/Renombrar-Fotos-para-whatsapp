from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .auth import SessionStore, hash_password, verify_password
from .core import MEDIA_EXTENSIONS, process, write_reports


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 1_000
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_LOGIN_BODY_BYTES = 8 * 1024
SESSION_COOKIE = "whatsapp_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"
SESSIONS = SessionStore(SESSION_TTL_SECONDS, os.getenv("SESSION_SECRET"))
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def safe_extract_zip(payload: bytes, destination: Path | None = None) -> None:
    """Validate a WhatsApp export ZIP and optionally extract it safely."""
    if len(payload) > MAX_UPLOAD_BYTES or not zipfile.is_zipfile(io.BytesIO(payload)):
        raise ValueError("El archivo debe ser un ZIP válido de máximo 50 MB.")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ValueError("El ZIP contiene demasiados archivos.")
        total_size = 0
        for member in members:
            name = member.filename.replace("\\", "/")
            parts = [part for part in name.split("/") if part]
            if name.startswith("/") or ".." in parts or "\x00" in name:
                raise ValueError("El ZIP contiene una ruta no segura.")
            if member.is_dir():
                continue
            # Reject Unix symlinks; extracting one could escape the staging folder.
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("El ZIP contiene un enlace simbólico no permitido.")
            total_size += member.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("El contenido descomprimido supera el límite permitido.")
        if destination is None:
            return
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            if member.is_dir():
                continue
            target = (destination / member.filename.replace("\\", "/")).resolve()
            if destination not in target.parents:
                raise ValueError("El ZIP contiene una ruta no segura.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _find_chat_file(root: Path) -> Path | None:
    candidates = sorted(root.rglob("*.txt"), key=lambda path: (path.name.casefold() != "_chat.txt", str(path)))
    return candidates[0] if candidates else None


def _stage_media(root: Path, media_dir: Path) -> None:
    media_dir.mkdir(parents=True, exist_ok=True)
    for source in root.rglob("*"):
        if not source.is_file() or source.suffix.casefold() not in MEDIA_EXTENSIONS:
            continue
        destination = media_dir / source.name
        index = 2
        while destination.exists():
            destination = media_dir / f"{source.stem}_{index}{source.suffix}"
            index += 1
        shutil.copy2(source, destination)


def process_upload(payload: bytes) -> tuple[bytes, dict[str, int]]:
    """Process one uploaded WhatsApp export and return a downloadable ZIP."""
    with tempfile.TemporaryDirectory(prefix="whatsapp-renamer-") as temp_dir:
        temp_root = Path(temp_dir)
        safe_extract_zip(payload, temp_root / "input")
        chat_file = _find_chat_file(temp_root / "input")
        media_dir = temp_root / "media"
        _stage_media(temp_root / "input", media_dir)
        output_dir = temp_root / "output"
        rows = process(media_dir, output_dir, chat_file)
        write_reports(rows, output_dir)
        summary = {
            "processed": sum(row.status == "processed" for row in rows),
            "unchanged": sum(row.status == "unchanged" for row in rows),
            "not_in_chat": sum(row.status == "not_in_chat" for row in rows),
            "missing_media": sum(row.status == "missing_media" for row in rows),
            "errors": sum(row.status == "error" for row in rows),
        }
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(output_dir.iterdir()):
                if file.is_file():
                    archive.write(file, file.name)
        return result.getvalue(), summary


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WhatsAppPhotoRenamer/0.1"

    def _send_json(self, status: int, body: dict[str, object]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if self._secure_cookie():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    @staticmethod
    def _secure_cookie() -> bool:
        return os.getenv("COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}

    def _cookie(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        for item in raw.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == SESSION_COOKIE:
                return value
        return None

    def _session(self):
        return SESSIONS.get(self._cookie())

    def _require_session(self) -> bool:
        if self._session() is not None:
            return True
        self._send_json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "AUTH_REQUIRED", "message": "Inicia sesión para continuar."}})
        return False

    def _set_session_cookie(self, token: str) -> None:
        attributes = f"{SESSION_COOKIE}={token}; Max-Age={SESSION_TTL_SECONDS}; Path=/; HttpOnly; SameSite=Lax"
        if self._secure_cookie():
            attributes += "; Secure"
        self.send_header("Set-Cookie", attributes)

    def _clear_session_cookie(self) -> None:
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")

    def _credentials(self) -> tuple[str, str] | None:
        username = os.getenv("APP_USERNAME", "").strip()
        password_hash = os.getenv("APP_PASSWORD_HASH", "").strip()
        return (username, password_hash) if username and password_hash else None

    def _login_allowed(self) -> bool:
        now = time.time()
        address = self.client_address[0]
        attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(address, []) if stamp > now - 15 * 60]
        LOGIN_ATTEMPTS[address] = attempts
        return len(attempts) < 10

    def _record_login_attempt(self) -> None:
        self._login_allowed()
        LOGIN_ATTEMPTS[self.client_address[0]].append(time.time())

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/api/session":
            session = self._session()
            self._send_json(HTTPStatus.OK, {"authenticated": session is not None, "username": session.username if session else None})
            return
        if path == "/" or path == "/index.html":
            self._serve_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._serve_file(WEB_ROOT / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(WEB_ROOT / "app.js", "text/javascript; charset=utf-8")
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": {"code": "NOT_FOUND", "message": "Recurso no encontrado."}})

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"code": "ASSET_ERROR", "message": "No se pudo cargar la interfaz."}})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/login":
            self._login()
            return
        if path == "/api/logout":
            SESSIONS.revoke(self._cookie())
            self.send_response(HTTPStatus.NO_CONTENT)
            self._clear_session_cookie()
            self._security_headers()
            self.end_headers()
            return
        if path != "/api/process":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"code": "NOT_FOUND", "message": "Recurso no encontrado."}})
            return
        if not self._require_session():
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": {"code": "UPLOAD_TOO_LARGE", "message": "El archivo debe pesar menos de 50 MB."}})
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": {"code": "INVALID_UPLOAD", "message": "Se requiere un formulario multipart."}})
            return
        body = self.rfile.read(content_length)
        boundary = content_type.split("boundary=", 1)[-1].strip().strip('"')
        marker = ("--" + boundary).encode()
        chunks = body.split(marker)
        uploaded = next((chunk for chunk in chunks if b"filename=" in chunk), None)
        if uploaded is None:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": {"code": "MISSING_FILE", "message": "Selecciona un archivo ZIP."}})
            return
        separator = b"\r\n\r\n"
        if separator not in uploaded:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": {"code": "INVALID_UPLOAD", "message": "No se pudo leer el archivo."}})
            return
        payload = uploaded.split(separator, 1)[1].rstrip(b"\r\n-")
        try:
            result, summary = process_upload(payload)
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": {"code": "PROCESSING_ERROR", "message": str(exc)}})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="whatsapp-renombradas.zip"')
        self.send_header("Content-Length", str(len(result)))
        self.send_header("X-WhatsApp-Summary", json.dumps(summary, separators=(",", ":")))
        self._security_headers()
        self.end_headers()
        self.wfile.write(result)

    def _login(self) -> None:
        if not self._login_allowed():
            self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": {"code": "LOGIN_RATE_LIMIT", "message": "Demasiados intentos. Espera 15 minutos."}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_LOGIN_BODY_BYTES:
                raise ValueError
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            username = str(body.get("username", ""))
            password = str(body.get("password", ""))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            self._record_login_attempt()
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "INVALID_LOGIN", "message": "Usuario o contraseña incorrectos."}})
            return
        credentials = self._credentials()
        valid = credentials is not None and secrets.compare_digest(username, credentials[0]) and verify_password(password, credentials[1])
        self._record_login_attempt()
        if not valid:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": {"code": "INVALID_LOGIN", "message": "Usuario o contraseña incorrectos."}})
            return
        token = SESSIONS.create(username)
        self.send_response(HTTPStatus.OK)
        self._set_session_cookie(token)
        self._security_headers()
        encoded = json.dumps({"authenticated": True, "username": username}).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        # Keep filenames and captions out of logs; only emit the request shape.
        print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the WhatsApp Photo Renamer web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--hash-password", action="store_true", help="Genera un hash scrypt para APP_PASSWORD_HASH y sale")
    args = parser.parse_args()
    if args.hash_password:
        print(hash_password(getpass.getpass("Contraseña (mínimo 12 caracteres): ")))
        return 0
    missing = [name for name in ("APP_USERNAME", "APP_PASSWORD_HASH", "SESSION_SECRET") if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Configura {', '.join(missing)} antes de iniciar el servidor.")
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"WhatsApp Photo Renamer: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
