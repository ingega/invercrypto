# ==========================================
# Production Runtime (Lean & glibc Compatible)
# ==========================================
FROM python:3.13-slim

WORKDIR /app

# Set environment variables to optimize Python inside Docker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install Poetry and configure it to install system-wide
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false

# Copy Poetry manifest and lockfile from strategy root
COPY pyproject.toml poetry.lock* ./

# Install production dependencies directly
RUN poetry install --no-root --only main --no-interaction --no-ansi

# Copy the application code
COPY . .

# Create application user matching EC2 ec2-user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser \
    && chown -R appuser:appuser /app

# Run application as non-root user
USER appuser

# Launch application
CMD ["python", "tangent/main_live.py"]