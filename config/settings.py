from pathlib import Path
from decouple import config
import dj_database_url
from datetime import timedelta

DATABASE_URL = config("DATABASE_URL")
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config("SECRET_KEY", default="dev-secret-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost,chemanalyst-backend.onrender.com").split(",")
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://chemanalyst-backend.onrender.com",
]
INSTA
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
    "django_celery_beat",
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


# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (Uploaded by users)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

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
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN", default="")
FACEBOOK_PAGE_ID = config("FACEBOOK_PAGE_ID", default="")

# frontend url used by OAuth callbacks
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# OAuth / API credentials for other platforms
FACEBOOK_APP_ID = config("FACEBOOK_APP_ID", default="")
FACEBOOK_APP_SECRET = config("FACEBOOK_APP_SECRET", default="")
INSTAGRAM_CLIENT_ID = config("INSTAGRAM_CLIENT_ID", default="")
INSTAGRAM_CLIENT_SECRET = config("INSTAGRAM_CLIENT_SECRET", default="")
TWITTER_API_KEY = config("TWITTER_API_KEY", default="")
TWITTER_API_SECRET = config("TWITTER_API_SECRET", default="")

GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET", default="")
GOOGLE_REDIRECT_URI = config("GOOGLE_REDIRECT_URI", default="")

LINKEDIN_CLIENT_ID = config("LINKEDIN_CLIENT_ID", default="")
LINKEDIN_CLIENT_SECRET = config("LINKEDIN_CLIENT_SECRET", default="")
LINKEDIN_REDIRECT_URI = config("LINKEDIN_REDIRECT_URI", default="")

FACEBOOK_LOGIN_REDIRECT_URI = config("FACEBOOK_LOGIN_REDIRECT_URI", default="")

FACEBOOK_API_VERSION = config('FACEBOOK_API_VERSION', 'v25.0')
FACEBOOK_REDIRECT_URI = config('FACEBOOK_REDIRECT_URI', default=f"{FRONTEND_URL}/api/platform/oauth/callback/")

# Twitter (X) API v2 OAuth settings
TWITTER_APP_ID = config("TWITTER_APP_ID", default="")
TWITTER_APP_SECRET = config("TWITTER_APP_SECRET", default="")
TWITTER_REDIRECT_URI = config("TWITTER_REDIRECT_URI", default=f"{FRONTEND_URL}/api/platform/oauth/callback/twitter")
TWITTER_API_VERSION = "v2"

# System pre-configured Meta credentials (for system-connect feature)
FACEBOOK_PAGE_ID = config("FACEBOOK_PAGE_ID", default="")
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN", default="")

# Celery and Redis settings
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    'fetch-all-platforms-hourly': {
        'task': 'platforms.tasks.trigger_all_platforms_sync',
        'schedule': timedelta(hours=1),
        'args': (),
    },
    'fetch-all-sentiment-hourly': {
        'task': 'sentiment.tasks.trigger_all_sentiment_sync',
        'schedule': timedelta(hours=1),
        'args': (),
    },
}

# Redis Cache for distributed locking
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config("REDIS_URL", default="redis://localhost:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}


# KAFKA CONFIG
KAFKA_BOOTSTRAP_SERVERS = config("KAFKA_BOOTSTRAP_SERVERS", default="localhost:9092")
KAFKA_PLATFORM_FETCH_TOPIC = 'platform-fetch-tasks'
KAFKA_SENTIMENT_TOPIC = "sentiment_quene"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=10),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Email Settings
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@chemanalyst.com')

