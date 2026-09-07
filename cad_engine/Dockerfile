FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 fontconfig fonts-dejavu-core fonts-liberation \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements-web.txt
COPY cad_engine/requirements.txt ./requirements-cad.txt
RUN pip install --no-cache-dir -r requirements-web.txt -r requirements-cad.txt
COPY app ./app
COPY cad_engine ./cad_engine
COPY data ./data
COPY standards ./standards
ENV CAD_OUTPUT_DIR=/tmp/engitools-cad-output
ENV TMPDIR=/tmp/engitools-tmp
ENV CAD_ISOLATED_SERVICE=1
RUN mkdir -p /tmp/engitools-cad-output /tmp/engitools-tmp
CMD ["sh", "-c", "uvicorn cad_engine.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
