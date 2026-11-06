FROM python:3.13-slim-trixie
LABEL org.opencontainers.image.source="https://github.com/quinnuk/audiocleaner" \
      org.opencontainers.image.description="AudioCleaner headless CLI: keep the best English audio track in MKV files" \
      org.opencontainers.image.licenses="BSD-2-Clause"
RUN apt-get update \
 && apt-get install -y --no-install-recommends mkvtoolnix mediainfo \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY main.py ./
COPY audiocleaner ./audiocleaner
ENV HOME=/config PYTHONUNBUFFERED=1
VOLUME /config
ENTRYPOINT ["python", "main.py"]
CMD ["scan", "--help"]