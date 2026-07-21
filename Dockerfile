# Use an official Python runtime
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy dependency file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY . .

# Expose the application port
EXPOSE 8000

# Start Gunicorn
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]