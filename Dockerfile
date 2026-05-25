FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OUTDIR=/data/outputs
RUN mkdir -p /data/outputs
ENTRYPOINT ["python", "run_queries.py"]
