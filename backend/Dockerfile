FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY pyproject.toml alembic.ini ./
COPY computeforgood ./computeforgood
COPY migrations ./migrations
RUN pip install --no-cache-dir --no-deps -e .
EXPOSE 8000
CMD ["uvicorn", "computeforgood.app:app", "--host", "0.0.0.0", "--port", "8000"]
