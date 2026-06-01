FROM python:3.10-slim

WORKDIR /workspace

# Install shared library dependencies first
COPY services/shared /workspace/services/shared
RUN pip install --no-cache-dir -e /workspace/services/shared

# Copy service dependencies and install
COPY services/websocket-gateway /workspace/services/websocket-gateway
WORKDIR /workspace/services/websocket-gateway
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]