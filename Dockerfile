FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements-web.txt
COPY cad_engine/requirements.txt ./requirements-cad.txt
RUN pip install --no-cache-dir -r requirements-web.txt -r requirements-cad.txt
COPY app ./app
COPY cad_engine ./cad_engine
COPY tests ./tests
COPY data ./data
COPY start_services.sh ./start_services.sh
RUN chmod +x ./start_services.sh
ENV DATA_DIR=/data
ENV CAD_DESIGNER_URL=http://127.0.0.1:8081
CMD ["./start_services.sh"]
