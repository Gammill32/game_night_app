#!/bin/sh

# Export selected environment vars for cron
cat <<EOF > /app/scripts/cron_env.sh
export SQLALCHEMY_DATABASE_URI="$DATABASE_URL"
export FLASK_APP="$FLASK_APP"
export MAIL_SERVER="$MAIL_SERVER"
export MAIL_PORT="$MAIL_PORT"
export MAIL_USE_TLS="$MAIL_USE_TLS"
export MAIL_USE_SSL="$MAIL_USE_SSL"
export MAIL_USERNAME="$MAIL_USERNAME"
export MAIL_PASSWORD="$MAIL_PASSWORD"
export MAIL_DEFAULT_SENDER="$MAIL_DEFAULT_SENDER"
EOF

# Start cron in background
cron

# Start Flask app
exec gunicorn -w 4 -b 0.0.0.0:8000 'app:create_app()'
