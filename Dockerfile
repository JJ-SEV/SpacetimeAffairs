FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLIGHT_RECORD_HOST=0.0.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flight_record_site ./flight_record_site
COPY scripts/render_xia_yizhou_pilot_flight_record_v2.py ./scripts/render_xia_yizhou_pilot_flight_record_v2.py
COPY assets/xia_yizhou_chinese_signature.png ./assets/xia_yizhou_chinese_signature.png
COPY assets/xia_yizhou_id_photo.jpg ./assets/xia_yizhou_id_photo.jpg
COPY assets/farspace_fleet_stamp_mask.png ./assets/farspace_fleet_stamp_mask.png

EXPOSE 8787

CMD ["python", "flight_record_site/server.py"]
