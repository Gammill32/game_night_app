FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN chmod +x scripts/entrypoint.sh

# Required so entrypoint.sh can run `flask db upgrade` without FLASK_APP set at runtime
ENV FLASK_APP=app

EXPOSE 8000

ENTRYPOINT ["sleep", "infinity"]
