# game_night_app/Dockerfile

# Use the specified Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Ensure wrapper scripts are executable
RUN chmod +x /app/scripts/run_with_env.sh /app/scripts/entrypoint.sh

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install cron and clean up package lists to reduce image size
RUN apt-get update && apt-get install -y cron && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create cron log directory
RUN mkdir -p /app/logs && touch /app/logs/cron.log

# Add cron jobs
RUN echo "0 8 * * * /app/scripts/run_with_env.sh /usr/local/bin/python3 /app/scripts/fetch_bgg_data.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/bgg-cron
RUN echo "32 19 * * * /app/scripts/run_with_env.sh /usr/local/bin/python3 /app/scripts/run_check_reminders.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/reminders-cron
RUN chmod 0644 /etc/cron.d/bgg-cron /etc/cron.d/reminders-cron && \
    crontab /etc/cron.d/bgg-cron && crontab -l | cat - /etc/cron.d/reminders-cron | crontab -

# Expose port for app
EXPOSE 8000

# Default environment var
ENV FLASK_APP=app:app

# Run entrypoint which writes cron_env.sh and starts services
CMD ["/app/scripts/entrypoint.sh"]
