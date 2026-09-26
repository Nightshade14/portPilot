# Deliberately bad: full python:3.8 image, no cleanup after apt-get, no
# multi-stage build, whole context copied before dependency install, runs
# as root, no .dockerignore. This is the eval target for image-optimization
# tooling, not a real deployment.
FROM python:3.8

RUN apt-get update && apt-get install -y curl git vim build-essential

COPY . /app
WORKDIR /app

RUN pip install -r requirements.txt

EXPOSE 8000
CMD ["python", "app.py"]
