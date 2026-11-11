FROM python:3.13-alpine
RUN apk add --no-cache openssl && pip install --no-cache-dir aiohttp==3.14.5
WORKDIR /app
COPY capture.py entrust-root-g2.crt ./
CMD ["python", "-u", "capture.py"]
LABEL io.hass.name="iCOMM development harness" io.hass.description="Bounded HTTPS and UDP recording" io.hass.type="addon" io.hass.version="0.2.0-dev1"
