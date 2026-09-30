FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && chown -R appuser:appgroup /app
USER appuser

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '10000') + '/health')" || exit 1

CMD ["sh", "-c", "exec python -m whatsapp_photo_renamer.webapp --host 0.0.0.0 --port ${PORT:-10000}"]
