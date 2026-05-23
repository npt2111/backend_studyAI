from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv



def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Always load the backend .env file, even when commands are launched from another cwd.
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True, encoding="utf-8-sig")

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
    'app.mindmap'
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

# PDF reader settings: pdfplumber first, EasyOCR only for pages with weak text.
DOCUMENT_MAX_FILE_MB = int(os.getenv("DOCUMENT_MAX_FILE_MB", "20"))
PDFPLUMBER_TEXT_MIN_WORDS_PER_PAGE = int(os.getenv("PDFPLUMBER_TEXT_MIN_WORDS_PER_PAGE", "20"))
EASYOCR_ENABLED = env_bool("EASYOCR_ENABLED", True)
EASYOCR_LANGS = os.getenv("EASYOCR_LANGS", "vi,en")
EASYOCR_GPU = env_bool("EASYOCR_GPU", False)
EASYOCR_DPI = int(os.getenv("EASYOCR_DPI", "130"))
EASYOCR_MAX_IMAGE_SIDE = int(os.getenv("EASYOCR_MAX_IMAGE_SIDE", "1800"))
EASYOCR_PARAGRAPH = env_bool("EASYOCR_PARAGRAPH", False)
PDF_OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "0"))

# Supabase Storage
SUPABASE_STORAGE_BUCKET  = os.getenv("SUPABASE_STORAGE_BUCKET", "study-documents")

# Groq quiz generation
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
GROQ_TIMEOUT_SECONDS = int(os.getenv("GROQ_TIMEOUT_SECONDS", "120"))
QUIZ_SOURCE_MAX_CHARS = int(os.getenv("QUIZ_SOURCE_MAX_CHARS", "16000"))

# Gemini mindmap generation
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
MINDMAP_SOURCE_MAX_CHARS = int(os.getenv("MINDMAP_SOURCE_MAX_CHARS", "18000"))

