# Dockerfile PRODUCTION / DEV FastAPI compatible Railway
FROM python:3.11-slim

WORKDIR /app

# dépendances système
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# copier requirements
COPY requirements.txt /app/requirements.txt

# installer pytorch cpu (plus ligh possible pour railway)
RUN pip install --no-cache-dir torch==2.3.1+cpu -f https://download.pytorch.org/whl/torch_stable.html

# install deps python
RUN pip install --no-cache-dir -r /app/requirements.txt

# nltk + data
RUN python -m nltk.downloader punkt stopwords wordnet averaged_perceptron_tagger

# copier app
COPY . /app

# create dirs
RUN mkdir -p /app/models /app/logs /app/uploads

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000

# fastapi launch
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
