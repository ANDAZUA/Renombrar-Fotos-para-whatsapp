# WhatsApp Photo Renamer

Herramienta independiente para macOS y Windows que procesa por lotes fotos de una exportación de chat de WhatsApp y las copia a una carpeta de salida usando el pie de foto como nombre de archivo.

## Arquitectura

- **Entrada:** una carpeta con medios exportados y, opcionalmente, el `.txt` de exportación del chat.
- **Parser estable:** reconoce formatos comunes de exportación de WhatsApp para iOS y Android; no automatiza la interfaz de WhatsApp.
- **Procesador seguro:** nunca modifica los archivos originales; copia cada medio a la salida, limpia nombres inválidos, preserva la extensión y evita sobrescrituras con `_2`, `_3`, etc.
- **Reporte:** genera `report.csv` y `report.json` con procesados, sin caption, no encontrados y errores.

## Uso

Requiere Python 3.10+.

```bash
python -m whatsapp_photo_renamer \
  --media ./exportacion/Media \
  --chat ./exportacion/_chat.txt \
  --output ./renombradas
```

También se puede procesar una carpeta sin TXT; en ese caso los archivos se copian conservando sus nombres originales:

```bash
python -m whatsapp_photo_renamer --media ./Media --output ./renombradas
```

Para revisar el resultado sin copiar archivos:

```bash
python -m whatsapp_photo_renamer --media ./Media --chat ./_chat.txt \
  --output ./renombradas --dry-run
```

El reporte registra cada archivo con `status`: `processed`, `unchanged`, `not_in_chat`, `missing_media`, `skipped` o `error`.

## Exportar el chat

En WhatsApp: abre el chat → menú de opciones → **Más** → **Exportar chat** → **Incluir archivos**. Descomprime el resultado y pasa la carpeta `Media` y el archivo `_chat.txt` a la herramienta.

## Desarrollo

```bash
python -m unittest discover -s tests -v
```

Este repositorio es autónomo y no depende ni modifica AMS Rocío.

## Interfaz web

El MVP también incluye una interfaz web local. Para iniciarla:

```bash
PYTHONPATH=src python3 -m whatsapp_photo_renamer.webapp
```

Luego abre `http://127.0.0.1:8000` en el navegador. Selecciona el ZIP de la exportación de WhatsApp y pulsa **Procesar fotos**. El resultado se descarga como `whatsapp-renombradas.zip`.

El servidor acepta ZIP de hasta 50 MB y limita el contenido descomprimido a 250 MB. Los archivos se procesan en una carpeta temporal y se eliminan al terminar la respuesta. La interfaz exige autenticación, limita los intentos de inicio de sesión y protege el procesamiento con una cookie `HttpOnly`, `SameSite=Lax`. Los resultados solo se entregan a la sesión autenticada que realizó la operación y no se almacenan en el servidor.

### Configuración para compartir

1. Copia `.env.example` a `.env` y define `APP_USERNAME`.
2. Genera un hash de contraseña:

   ```bash
   PYTHONPATH=src python3 -m whatsapp_photo_renamer.webapp --hash-password
   ```

3. Guarda el resultado en `APP_PASSWORD_HASH` dentro de `.env` **entre comillas simples** (el hash contiene `$`), define `SESSION_SECRET` con una cadena aleatoria larga y carga las variables antes de iniciar el servidor:

   ```dotenv
   APP_USERNAME=equipo
   APP_PASSWORD_HASH='scrypt$...$...'
   SESSION_SECRET='...'
   ```

   ```bash
   set -a; source .env; set +a
   PYTHONPATH=src python3 -m whatsapp_photo_renamer.webapp
   ```

   Puedes generar el secreto con:

   ```bash
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```
4. En producción publica el contenedor detrás de un proxy HTTPS (por ejemplo, Caddy, Nginx o la terminación TLS del proveedor) y configura `COOKIE_SECURE=1`. No expongas el servidor HTTP directamente a internet.

La autenticación incluida es un acceso de equipo de una sola cuenta. Para varias personas con cuentas separadas, auditoría o recuperación de contraseña se requiere una fase posterior con una base de datos y un proveedor de identidad.

También se incluye un `Dockerfile` para desplegarlo en un servicio compatible con contenedores.
