# perfora — container image
#
# Default behaviour: start the guided quickstart notebook, so a user needs no
# Python, no uv and no Tesseract install of their own.
#
#   docker run --rm -p 8888:8888 -v "$PWD:/data" ghcr.io/perfora-project/perfora
#
# Any other entry point is available by naming it after the image:
#
#   docker run --rm -v "$PWD:/data" ghcr.io/perfora-project/perfora \
#       perfora -i /data/roll.tif -o /data/roll.perfora.json --dpi 600
#
# Included: the core pipeline, the sample roll, the quickstart notebook, and
# Tesseract for printed-text OCR. Excluded: TrOCR/EasyOCR (they pull in PyTorch,
# which would multiply the image size) — install those in a derived image if you
# need handwriting recognition.

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="perfora" \
      org.opencontainers.image.description="Digitize player-piano roll scans and videos into a reversible, millimetre-based model of perforations and text." \
      org.opencontainers.image.source="https://github.com/perfora-project/Perfora" \
      org.opencontainers.image.documentation="https://perfora.readthedocs.io" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# libmagic1 -> content-based source-type detection (python-magic)
# tesseract-ocr -> the printed-text OCR engine behind the [tesseract] extra
# libglib2.0-0 -> runtime dependency of opencv's headless wheels
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        libmagic1 \
        tesseract-ocr \
        libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Install the package itself. Copying the whole tree keeps the build simple and
# reproducible; .dockerignore keeps it small.
COPY . /src
RUN pip install --no-cache-dir "/src[notebook,tesseract,cli]" \
 && rm -rf /src

# Run as a non-root user, and make /data the place where scans and results live.
RUN useradd --create-home --uid 1000 perfora \
 && mkdir -p /data \
 && chown -R perfora:perfora /data
USER perfora
WORKDIR /data
VOLUME ["/data"]

EXPOSE 8888

# 0.0.0.0 is required for the port to be reachable from outside the container.
# Jupyter still prints a one-time token in the log; copy the printed URL.
CMD ["perfora-notebook", "--dir", "/data", "--ip", "0.0.0.0", "--port", "8888", "--no-browser"]
