FROM python:3-alpine AS steamscordbot-builder

RUN apk add --update --no-cache gcc musl-dev \
	&& rm -rf /var/cache/apk/*

COPY requirements.txt /steamscord/

ENV PYTHONDONTWRITEBYTECODE=1

RUN python -m venv --system-site-packages /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade -r /steamscord/requirements.txt

COPY steamscordbot steamscordbot

FROM python:3-alpine

COPY --from=steamscordbot-builder /opt/venv /opt/venv

COPY --from=steamscordbot-builder steamscordbot /steamscord/steamscordbot

ENV PATH="/opt/venv/bin:$PATH"

ENV PYTHONPATH="/steamscord"

ENTRYPOINT ["python", "-m", "steamscordbot"]

#CMD ["-e"]
