FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.2,<4"
COPY kpi kpi
COPY data data
COPY web web
COPY migrations migrations
RUN useradd --system kpi
USER kpi
EXPOSE 8765
CMD ["python", "-m", "kpi.server", "--host", "0.0.0.0"]

