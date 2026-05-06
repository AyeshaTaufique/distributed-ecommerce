FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Expose port
EXPOSE 5002

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5002"]



# FROM python:3.11-slim

# WORKDIR /app

# RUN pip install --no-cache-dir fastapi uvicorn redis pydantic requests

# COPY main.py /app/main.py

# EXPOSE 5002

# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5002"]