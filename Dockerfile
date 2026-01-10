FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_FILE=/neubot/data/neubot.db

# Set work directory
WORKDIR /neubot

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN /usr/bin/python3 -m pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directory for persistent storage
RUN mkdir -p /neubot/data

# Ensure the database directory is writable
RUN chmod 777 /neubot/data

# Expose port
EXPOSE 3006

# Run gunicorn
# Explicitly calling python -m gunicorn to ensure path resolution
CMD ["/usr/bin/python3", "-m", "gunicorn", "--config", "gunicorn_config.py", "main:app"]

