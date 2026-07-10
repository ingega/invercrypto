FROM python:3.11-slim AS builder

WORKDIR /build

COPY strategy/requirements.txt .

RUN pip install --no-cache-dir \
    --prefix=/install \
    -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY strategy/ .

# activate logs
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "tangent.main"]