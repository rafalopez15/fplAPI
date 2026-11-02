# Runs the API locally or on a container host. Production runs on Vercel, which
# builds from requirements.txt and doesn't use this file.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the API needs at runtime: no tests, migrations or sync workflows.
COPY main.py .
COPY src ./src

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
