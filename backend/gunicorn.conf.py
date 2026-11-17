"""Gunicorn settings. Command-line flags in entrypoint.sh set workers/threads/bind."""


def post_worker_init(worker):
    """Load the embedding models before the worker takes traffic, so the first search or
    photo upload doesn't pay the 2-3 s model-loading cost (measured: 2.6 s cold, ~40 ms warm)."""
    try:
        from PIL import Image

        from ai.embeddings import get_embedder
        from ai.visual import get_clip, visual_enabled

        get_embedder().embed_query("warm up")
        if visual_enabled():
            clip = get_clip()
            clip.embed_texts(["warm up"])
            clip.embed_image(Image.new("RGB", (32, 32)))
        worker.log.info("Models warmed up")
    except Exception:  # never stop a worker from starting; models then load on first use
        worker.log.exception("Model warm-up failed; models will load on first request")
