FROM ghcr.io/home-assistant/base:latest

LABEL \
  io.hass.version="1.0.0" \
  io.hass.type="addon" \
  io.hass.arch="aarch64|amd64|armhf|armv7"

# Install Python and pip
RUN apk add --no-cache python3 py3-pip wget

# Create virtual environment to avoid PEP 668 conflicts
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application
COPY app/ /app/

# Download Chart.js for offline use (falls back to CDN if no internet during build)
RUN mkdir -p /app/static/js \
  && ( wget -q -O /app/static/js/chart.umd.min.js \
       "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js" \
    && wget -q -O /app/static/js/chartjs-plugin-annotation.min.js \
       "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js" \
  ) || echo "[WARN] Chart.js download skipped — CDN fallback will be used at runtime"

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
