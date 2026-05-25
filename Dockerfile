FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OUTDIR=/data/outputs
RUN mkdir -p /data/outputs
EXPOSE 8080
ENTRYPOINT ["uvicorn", "conversational_agent:app", "--host", "0.0.0.0", "--port", "8080"]
