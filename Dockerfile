# game_night_app/Dockerfile

# Use the specified Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Install cron and clean up package lists to reduce image size
RUN apt-get update && apt-get install -y cron && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add cron job for updating BGG data
RUN echo "0 3 * * * cd /app && /app/scripts/run_with_env.sh /usr/local/bin/python3 app/scripts/fetch_bgg_data.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/bgg-cron

# Add cron job for sending game night reminders
RUN echo "21 19 * * * cd /app && /app/scripts/run_with_env.sh /usr/local/bin/python3 app/scripts/run_check_reminders.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/reminders-cron

# Set permissions for cron jobs
RUN chmod 0644 /etc/cron.d/bgg-cron /etc/cron.d/reminders-cron

# Apply both cron jobs
RUN crontab /etc/cron.d/bgg-cron && crontab -l | cat - /etc/cron.d/reminders-cron | crontab -

# Create the log file and ensure the logs directory exists
RUN mkdir -p /app/logs && touch /app/logs/cron.log

# Expose port 8000 for the Flask app
EXPOSE 8000

# Set environment variable for Flask
ENV FLASK_APP=app:app

# Run cron in the background and the Flask app
CMD ["sh", "-c", "cron && gunicorn -w 4 -b 0.0.0.0:8000 'app:create_app()'"]
