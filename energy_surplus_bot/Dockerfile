ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

WORKDIR /app
COPY . /app

RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
