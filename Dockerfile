FROM python:3.12-slim
# libcairo2: nodig om SVG-teamlogo's (ESPN-logopakketten) te renderen
RUN apt-get update && apt-get install -y --no-install-recommends libcairo2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data
EXPOSE 8000
CMD ["python", "server.py", "--no-open"]
