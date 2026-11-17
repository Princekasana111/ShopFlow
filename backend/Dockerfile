FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_DIR=/app/.cache/fastembed

# Create the runtime user first. Files are then created or copied with the right owner, instead of a
# final `chown -R`, which would copy every file (including ~0.6 GB of models) into a new layer.
RUN useradd --create-home appuser && mkdir /app && chown appuser /app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

USER appuser

# Bake the models into the image so the container needs no download at runtime:
# bge-small (text search) and CLIP ViT-B/32 vision + text (photo search).
RUN python -c "from fastembed import TextEmbedding, ImageEmbedding; \
c='/app/.cache/fastembed'; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=c); \
ImageEmbedding('Qdrant/clip-ViT-B-32-vision', cache_dir=c); \
TextEmbedding('Qdrant/clip-ViT-B-32-text', cache_dir=c)"

COPY --chown=appuser . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
