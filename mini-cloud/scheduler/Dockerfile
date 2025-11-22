# scheduler/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir requests pydantic fastapi uvicorn
ENV PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "9000"]
