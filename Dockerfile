# Dockerfile pour le développement FastAPI
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Installer les dépendances système
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copier le fichier requirements.txt
COPY requirements.txt .

# Installer PyTorch CPU compatible Python 3.11
RUN pip install --no-cache-dir torch==2.3.1+cpu -f https://download.pytorch.org/whl/torch_stable.html


# Installer NLTK avant de télécharger ses ressources
RUN pip install --no-cache-dir nltk==3.8.1

# Télécharger les données NLTK nécessaires
RUN python -m nltk.downloader punkt stopwords wordnet averaged_perceptron_tagger

# Installer les autres dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY . .

# Créer les répertoires nécessaires
RUN mkdir -p /app/models /app/logs /app/uploads

# Définir les variables d'environnement
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=development

# Exposer le port 8000
EXPOSE 8000

# Commande pour démarrer l'application FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--log-level", "debug"]
