FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ml.txt

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Run as a non-root user. Pre-create the writable paths so Docker seeds the
# named volumes mounted here with appuser ownership (volumes inherit the
# image dir's ownership when first created) — otherwise the non-root process
# can't write thumbnails or download model weights on first boot.
RUN useradd --create-home appuser \
    && mkdir -p /srv/storage /home/appuser/.cache \
    && chown -R appuser:appuser /srv/storage /home/appuser/.cache
USER appuser

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
