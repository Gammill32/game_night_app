FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN chmod +x scripts/entrypoint.sh \
    # Run as an ordinary user (uid 1000, like the media dataset's owner), not root.
    # It needs to write session files under /app and uploads under /app/media.
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/media /app/flask_session \
    && chown -R app:app /app
USER app

# Required so entrypoint.sh can run `flask db upgrade` without FLASK_APP set at runtime
ENV FLASK_APP=app

EXPOSE 8000

ENTRYPOINT ["scripts/entrypoint.sh"]
