# ==========================================
# Production Runtime (Lean & glibc Compatible)
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# Set environment variables to optimize Python inside Docker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=
ENV PYTHONPATH=/app/strategy

# Copy requirements matrix
COPY strategy/requirements.txt .

# Install pre-compiled wheels directly (no compilation needed, no OOM)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your invercrypto 2.0 application code
COPY strategy/ ./strategy/

# Adjusted the command to point to your main file correctly
CMD ["python", "strategy/tangent/main.py"]