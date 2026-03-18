FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install .

EXPOSE 8000

CMD ["uvicorn", "sanitized_data_platform.bootstrap.production:create_production_fastapi_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
