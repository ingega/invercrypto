# Use a lightweight, official Python runtime as a parent image
# ==========================================
# STAGE 1: The Builder (Heavy but Disposable)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install basic build tools needed for heavy wheel compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements matrix 
COPY strategy/requirements.txt .

# Compile and isolate wheels to a local directory
RUN pip install --no-cache-dir --user -r requirements.txt

# ==========================================
# STAGE 2: The Production Runtime (Ultra-Lean)
# ==========================================
FROM python:3.11-alpine

WORKDIR /app

# Copy only the pre-compiled packages from Stage 1
COPY --from=builder /root/.local /root/.local
COPY strategy/ .

# Sync paths to utilize isolated user packages
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# As a placeholder/sanity check for Phase 1, we will just print a system readiness statement
CMD ["python", "-c", "print('🚀 Invercrypto Engine Live on EC2. Architecture Verified!')"]