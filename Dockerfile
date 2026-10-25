# Use an official Python runtime as a parent image
FROM python:3.13.11-slim-bookworm

# Set environment variables
# PYTHONDONTWRITEBYTECODE: Prevents Python from writing pyc files to disc
# PYTHONUNBUFFERED: Prevents Python from buffering stdout and stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
# gcc and others needed for some python packages
# npm needed for tailwind build step
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libffi-dev \
    libssl-dev \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt
RUN pip install gunicorn

# Copy project
COPY . /app/

# Build TailwindCSS
RUN npm install
RUN npm run build:css

# Create necessary directories and set permissions for SQLite and Persistent Media in Coolify
RUN mkdir -p /app/data /app/db /app/db/media /app/media \
    && chmod -R 777 /app/db /app/data /app/media
# In Coolify: Mount persistent storage to /app/db (which preserves both SQLite db.sqlite3 and media/ photos)

# Collect static files
RUN python manage.py collectstatic --noinput
RUN python manage.py migrate

# Expose port
EXPOSE 7001

# Start script
# We run migrations and then start gunicorn
CMD ["sh", "-c", "python manage.py migrate && gunicorn --bind 0.0.0.0:8000 core.wsgi:application"]
