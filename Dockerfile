# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

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
RUN npm run build

# Create necessary directories and set permissions for SQLite
# In container, user might be root or appuser. 
# We ensure DB path is writable.
RUN mkdir -p /app/data /app/db
# If you mount a volume to /app/db.sqlite3, that works too.
# For coolify/production with sqlite, best to use a volume for the db file.
# We will assume startup script handles migrations if db is fresh.

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Start script
# We run migrations and then start gunicorn
CMD ["sh", "-c", "python manage.py migrate && gunicorn --bind 0.0.0.0:8000 core.wsgi:application"]
