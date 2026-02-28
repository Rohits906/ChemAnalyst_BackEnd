from pathlib import Path
from decouple import config
import dj_database_url
from datetime import timedelta

DATABASE_URL = config("DATABASE_URL")
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config("SECRET_KEY", default="dev-secret-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost").split(",")
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
]
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "authentication",
    "contact",
    "platforms",
    "sentiment",
    "reports",
]
# AUTH_USER_MODEL = "authentication.User"

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}


from datetime import timedelta

# Social Media API Keys
INSTAGRAM_ACCESS_TOKEN = config("INSTAGRAM_ACCESS_TOKEN", default="")
INSTAGRAM_BUSINESS_ACCOUNT_ID = config("INSTAGRAM_BUSINESS_ACCOUNT_ID", default="")
YOUTUBE_API_KEY = config("YOUTUBE_API_KEY", default="")
TWITTER_BEARER_TOKEN = config("TWITTER_BEARER_TOKEN", default="")


# KAFKA CONFIG
KAFKA_BOOTSTRAP_SERVERS = config("KAFKA_BOOTSTRAP_SERVERS", default="localhost:9092")
KAFKA_PLATFORM_FETCH_TOPIC = 'platform-fetch-tasks'
KAFKA_SENTIMENT_TOPIC = "sentiment_quene"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=10),
    "AUTH_HEADER_TYPES": ("Bearer",),
}
