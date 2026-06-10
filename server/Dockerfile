FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ml.txt

# insightface depends on full opencv-python (not just the headless build),
# which dynamically loads X11/GL libs absent from the slim base. Installed
# after the pip layer so the heavy ML wheels stay cached on rebuilds.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# So `alembic` (a console script that doesn't add CWD to sys.path) and any
# other entrypoint can import the `app` package. Placed after the pip layer to
# keep the heavy ML install cached.
ENV PYTHONPATH=/srv

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
