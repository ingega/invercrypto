# Use a lightweight, official Python runtime as a parent image
FROM python:3.11-slim

# Set system-level environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies (build-essential for potential C-based math packages later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements or package lists first to leverage Docker layer caching
COPY strategy/requirements.txt .

# Install Python requirements
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Explicitly build our strategy folder architecture inside the container
RUN mkdir -p strategy/common_files strategy/tangent_fomo config utils data

# Copy the rest of our application code into the container
COPY . .

# As a placeholder/sanity check for Phase 1, we will just print a system readiness statement
CMD ["python", "-c", "print('🚀 Invercrypto Engine Live on EC2. Architecture Verified!')"]