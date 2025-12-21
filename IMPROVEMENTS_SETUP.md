# Guide d'installation des dépendances pour les améliorations

## Dépendances requises

Ajoutez ces lignes à votre `requirements.txt`:

```txt
# Existant
fastapi
sqlalchemy
psycopg2-binary
alembic
pydantic
python-jose[cryptography]
passlib[bcrypt]
python-multipart
uvicorn[standard]

# Améliorations P0-P2
redis>=5.0.0                    # Cache
httpx>=0.25.0                   # Webhooks async
reportlab>=4.0.0                # Export PDF
pandas>=2.0.0                   # Export Excel
openpyxl>=3.1.0                 # Excel writer
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

### 1. Redis (Cache)

**Option A: Docker**
```bash
docker run -d -p 6379:6379 redis:alpine
```

**Option B: Installation locale**
```bash
# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis
```

### 2. Variables d'environnement

Ajoutez à votre `.env`:

```env
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=votre-email@gmail.com
SMTP_PASSWORD=votre-mot-de-passe-app

# Frontend URL (pour liens dans emails)
FRONTEND_URL=https://votre-frontend.vercel.app

# Sécurité
JWT_SECRET_KEY=votre-secret-key-super-securisee
```

### 3. Initialiser les rôles RBAC

Créez un script d'initialisation `init_roles.py`:

```python
from app.database import SessionLocal
from app.utils.permissions import PermissionService

db = SessionLocal()
permission_service = PermissionService()
permission_service.initialize_default_roles(db)
print("✅ Rôles initialisés")
db.close()
```

Exécutez:
```bash
python init_roles.py
```

## Utilisation

### Cache

```python
from app.utils.cache import cache_result, invalidate_cache

@cache_result(ttl=600, key_prefix="salary")
def get_salary_benchmark(db, job_category):
    # Fonction lourde...
    return data

# Invalider le cache
invalidate_cache("salary:*")
```

### Permissions

```python
from app.utils.permissions import require_permission, Permission

@router.post("/companies/{id}/verify")
@require_permission(Permission.VERIFY_COMPANY)
async def verify_company(company_id, db, current_user):
    # Seuls les admins peuvent vérifier
    pass
```

### Notifications

```python
from app.services.notification_service import NotificationService

notification_service = NotificationService()

# Créer notification
notification_service.create_notification(
    db, user_id, "application_status",
    "Candidature présélectionnée",
    "Votre candidature a été présélectionnée !"
)

# Envoyer email
await notification_service.send_email(
    "user@example.com",
    "Sujet",
    "Corps du message"
)
```

### Export

```python
from app.services.export_service import ExportService

export_service = ExportService()

# Export Excel
excel_data = export_service.export_to_excel(data)

# Export PDF
pdf_data = export_service.generate_recruitment_report_pdf(
    company_name, stats, applications
)
```

## Déploiement sur Railway

### 1. Ajouter Redis

Dans Railway:
1. New → Database → Redis
2. Copier les variables d'environnement générées
3. Les ajouter à votre service backend

### 2. Variables d'environnement

Configurez dans Railway:
- `REDIS_HOST`
- `REDIS_PORT`
- `SMTP_*` (pour emails)
- `FRONTEND_URL`

### 3. Migration base de données

```bash
# Générer migration
alembic revision --autogenerate -m "Add RBAC and improvements"

# Appliquer
alembic upgrade head
```

### 4. Initialiser les rôles

Après déploiement, exécutez une fois:
```bash
railway run python init_roles.py
```

## Vérification

Testez que tout fonctionne:

```bash
# Test cache
curl http://localhost:8000/api/v1/salary/benchmark?job_category=Développeur

# Test notifications
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/notifications/me

# Test export
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/export/applications/excel?company_id=<uuid>
```

## Troubleshooting

**Redis non connecté:**
- Vérifiez que Redis est démarré: `redis-cli ping`
- Le cache sera automatiquement désactivé si Redis n'est pas disponible

**Emails non envoyés:**
- Vérifiez les credentials SMTP
- Pour Gmail, utilisez un "App Password" (pas votre mot de passe normal)

**Exports PDF échouent:**
- Vérifiez que reportlab est installé: `pip install reportlab`
