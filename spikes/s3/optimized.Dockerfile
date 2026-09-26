FROM python:3.8-slim AS builder
RUN pip install --no-cache-dir --user requests==2.32.4

FROM python:3.8-slim
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
