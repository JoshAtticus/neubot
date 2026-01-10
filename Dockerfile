FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_FILE=/app/neubot/data/neubot.db

# Set work directory
WORKDIR /app/neubot

# Install system dependencies
# gcc and python3-dev might be needed for some python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create directory for persistent storage
RUN mkdir -p /app/neubot/data

# Expose port
EXPOSE 3006

# Run gunicorn
# Using the config file we modified earlier
CMD ["gunicorn", "--config", "gunicorn_config.py", "main:app"]
