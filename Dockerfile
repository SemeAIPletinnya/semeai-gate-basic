FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY semeai_gate_basic ./semeai_gate_basic
COPY examples ./examples
COPY schemas ./schemas

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

ENV SEMEAI_GATE_HOST=0.0.0.0
ENV SEMEAI_GATE_PORT=8787
ENV SEMEAI_GATE_RECEIPT_DIR=/app/outputs/api_receipts

EXPOSE 8787

CMD ["python", "-m", "semeai_gate_basic.server", "--host", "0.0.0.0", "--port", "8787", "--receipt-dir", "/app/outputs/api_receipts"]
