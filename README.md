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

El servidor acepta ZIP de hasta 50 MB y limita el contenido descomprimido a 250 MB. Los archivos se procesan en una carpeta temporal y se eliminan al terminar la respuesta. Para compartirlo con un equipo, debe desplegarse detrás de HTTPS y autenticación; esta primera versión no incluye cuentas ni almacenamiento persistente.

También se incluye un `Dockerfile` para desplegarlo en un servicio compatible con contenedores.
