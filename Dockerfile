# ---- CSS: Tailwind standalone CLI (pinned v3.4.17, checksum-verified; no Node) ----
FROM python:3.11-slim AS css
ARG TARGETARCH
WORKDIR /src
RUN case "${TARGETARCH:-amd64}" in \
      amd64) asset=tailwindcss-linux-x64;   sha=7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4 ;; \
      arm64) asset=tailwindcss-linux-arm64; sha=69b1378b8133192d7d2feb12a116fa12d035594f58db3eff215879e4ad8cf39b ;; \
      *) echo "unsupported arch ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && python -c "import urllib.request,sys; urllib.request.urlretrieve(sys.argv[1], '/usr/local/bin/tailwindcss')" \
         "https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/$asset" \
    && echo "$sha  /usr/local/bin/tailwindcss" | sha256sum -c - \
    && chmod +x /usr/local/bin/tailwindcss
COPY tailwind.config.js ./
COPY app ./app
RUN tailwindcss -c tailwind.config.js -i app/static/css/tailwind.input.css -o /tailwind.css --minify

# ---- App ----
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, then the freshly built stylesheet over the committed one
COPY . .
COPY --from=css /tailwind.css app/static/css/tailwind.css

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
