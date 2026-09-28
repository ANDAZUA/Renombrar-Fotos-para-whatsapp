FROM python:3.12-slim

WORKDIR /app
COPY . .

ENV PYTHONPATH=/app/src
EXPOSE 8000

CMD ["python", "-m", "whatsapp_photo_renamer.webapp", "--host", "0.0.0.0", "--port", "8000"]
