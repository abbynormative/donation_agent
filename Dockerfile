FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OUTDIR=/data/outputs
RUN mkdir -p /data/outputs

# Bake a seeded SQLite database into the image. Free hosting tiers (e.g.
# Render) have an ephemeral filesystem, so generating data at deploy time
# instead of build time would leave the app with an empty `donations`
# table after every restart/redeploy.
RUN python seed_donations.py

# Bind to $PORT so this works on hosts that assign it dynamically (e.g.
# Render defaults to 10000); falls back to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn conversational_agent:app --host 0.0.0.0 --port ${PORT}"]
