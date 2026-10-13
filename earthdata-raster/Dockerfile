FROM ghcr.io/osgeo/gdal:ubuntu-small-3.10.3
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt
COPY app.py .
EXPOSE 8000
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8000"]
