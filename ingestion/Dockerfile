FROM --platform=linux/amd64 python:3.14-slim AS build
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY sec_ingestion ./sec_ingestion
RUN pip install --no-cache-dir --no-deps .

FROM --platform=linux/amd64 python:3.14-slim
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /home/app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python", "-m", "sec_ingestion", "healthcheck"]
CMD ["uvicorn", "sec_ingestion.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--log-level", "warning", "--timeout-graceful-shutdown", "15"]
