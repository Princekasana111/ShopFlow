FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_DIR=/app/.cache/fastembed

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the models into the image so the container needs no download at runtime:
# bge-small (text search) and CLIP ViT-B/32 vision + text (photo search).
RUN python -c "from fastembed import TextEmbedding, ImageEmbedding; \
c='/app/.cache/fastembed'; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=c); \
ImageEmbedding('Qdrant/clip-ViT-B-32-vision', cache_dir=c); \
TextEmbedding('Qdrant/clip-ViT-B-32-text', cache_dir=c)"

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x entrypoint.sh \
    && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
