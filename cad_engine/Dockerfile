FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/cad-requirements.txt
RUN pip install --no-cache-dir -r /tmp/cad-requirements.txt
COPY . ./cad_engine
CMD ["sh","-c","uvicorn cad_engine.main_v15:app --host 0.0.0.0 --port ${PORT:-8080}"]
