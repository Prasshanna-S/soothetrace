FROM python:3.12-slim AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}"

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PORT=10000
ENV IM_DATA_ROOT=/var/data
ENV IM_DB_PATH=/var/data/episodes.db
ENV IM_AUDIO_DIR=/var/data/audio
ENV IM_MODEL_DIR=/var/data/models

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system soothetrace \
    && useradd --system --gid soothetrace --create-home soothetrace \
    && mkdir --parents /app /var/data \
    && chown --recursive soothetrace:soothetrace /app /var/data

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY web ./web
COPY data/calibration.json ./data/calibration.json
COPY deploy/population-baseline.json ./deploy/population-baseline.json
COPY demo_assets/baby_audio/warning-demo ./demo_assets/baby_audio/warning-demo
COPY scripts/prepare_care_demo.py scripts/hosted_bootstrap.py scripts/hosted_entrypoint.py ./scripts/

USER soothetrace

EXPOSE 10000

CMD ["python", "scripts/hosted_entrypoint.py"]
