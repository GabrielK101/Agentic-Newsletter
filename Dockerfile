# Not deployed anywhere yet - this just makes the job container-ready.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DIGEST_CONFIG=config.prod.yaml \
    DIGEST_DB=/tmp/digest.db \
    DIGEST_STORAGE=gcs

WORKDIR /app

# requirements.txt first and installed before the rest of the code is
# copied in, so this (slow) layer is cached across builds that only
# change application code, not dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user. .dockerignore keeps .env/config.yaml/tests/.git/etc. out
# of the build context entirely, so there's nothing secret to accidentally
# own or ship in the first place.
#
# /app itself was created by WORKDIR above, before this user existed, so
# it's still root:root - COPY --chown only sets ownership on the files it
# copies IN, not retroactively on that pre-existing parent directory. Without
# the explicit chown below, digest can read everything under /app but can't
# create a new digests/ directory in it at runtime (found by actually
# running the container, not just by reading the Dockerfile).
RUN useradd --create-home --uid 1000 digest && chown digest:digest /app
COPY --chown=digest:digest . .

USER digest

# ENTRYPOINT/CMD split (not a single CMD) so Cloud Run - or `docker run
# ... news-digest --check` - can override just the args, without having to
# repeat "python digest.py" or override the whole command.
ENTRYPOINT ["python", "digest.py"]
CMD ["--send"]
