from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-change-me")
DEBUG = env_bool("DEBUG", True)

render_external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()

allowed_hosts = {"127.0.0.1", "localhost"}
if render_external_hostname:
    allowed_hosts.add(render_external_hostname)
if os.getenv("ALLOWED_HOSTS"):
    allowed_hosts.update(
        [host.strip() for host in os.getenv("ALLOWED_HOSTS", "").split(",") if host.strip()]
    )
ALLOWED_HOSTS = list(allowed_hosts)

csrf_trusted_origins = []
if render_external_hostname:
    csrf_trusted_origins.append(f"https://{render_external_hostname}")
if os.getenv("CSRF_TRUSTED_ORIGINS"):
    csrf_trusted_origins.extend(
        [
            origin.strip()
            for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
            if origin.strip()
        ]
    )
CSRF_TRUSTED_ORIGINS = csrf_trusted_origins

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'app.users',
    'app.chat',
    'app.flashcards',
    'app.quiz',
    'app.planner',
    'app.analytics',
    'app.documents',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        ssl_require=not DEBUG,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Bangkok'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",
    ),
}

JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "10080"))  # 7 days
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))

# CORS
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", True)
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# â”€â”€ Groq config (thay tháº¿ Gemini) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL   = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# Retry settings (dÃ¹ng chung cho Groq)
GROQ_RETRY_MAX          = int(os.getenv("GROQ_RETRY_MAX", "3"))
GROQ_RETRY_BASE_SECONDS = float(os.getenv("GROQ_RETRY_BASE_SECONDS", "8"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_RETRY_MAX = int(os.getenv("GEMINI_RETRY_MAX", "3"))
GEMINI_RETRY_BASE_SECONDS = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "8"))

# â”€â”€ Supabase Storage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SUPABASE_STORAGE_BUCKET  = os.getenv("SUPABASE_STORAGE_BUCKET", "study-documents")

# â”€â”€ Summary pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SUMMARY_MAX_FILE_MB      = int(os.getenv("SUMMARY_MAX_FILE_MB", "20"))
SUMMARY_CHUNK_CHARS      = int(os.getenv("SUMMARY_CHUNK_CHARS", "7000"))
SUMMARY_MAX_SOURCE_CHARS = int(os.getenv("SUMMARY_MAX_SOURCE_CHARS", "120000"))
SUMMARY_WORKER_THREADS   = int(os.getenv("SUMMARY_WORKER_THREADS", "1"))
SUMMARY_RETRY_ATTEMPTS   = int(os.getenv("SUMMARY_RETRY_ATTEMPTS", "1"))
SUMMARY_PDF_PAGES_PER_CHUNK = int(os.getenv("SUMMARY_PDF_PAGES_PER_CHUNK", "16"))

# Token budgets (Groq)
SUMMARY_CHUNK_MAX_TOKENS = int(os.getenv("SUMMARY_CHUNK_MAX_TOKENS", "650"))
SUMMARY_FINAL_MAX_TOKENS = int(os.getenv("SUMMARY_FINAL_MAX_TOKENS", "1200"))
SUMMARY_REPAIR_MAX_TOKENS = int(os.getenv("SUMMARY_REPAIR_MAX_TOKENS", "900"))
SUMMARY_KEYPOINTS_MAX_TOKENS = int(os.getenv("SUMMARY_KEYPOINTS_MAX_TOKENS", "450"))
SUMMARY_ENABLE_MODEL_REPAIR = env_bool("SUMMARY_ENABLE_MODEL_REPAIR", False)
SUMMARY_ENABLE_KEYPOINTS_FALLBACK = env_bool("SUMMARY_ENABLE_KEYPOINTS_FALLBACK", False)



