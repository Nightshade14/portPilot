FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY contracts ./contracts

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 5001
CMD ["python", "app.py", "--port", "5001"]
