# The same immutable image is used by every QOTD Cloud Run Job.  The job
# definition selects the QOTD command to execute.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY qotd ./qotd

RUN useradd --create-home --shell /usr/sbin/nologin qotd
USER qotd

ENTRYPOINT ["python", "-m", "qotd"]
