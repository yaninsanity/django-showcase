SECRET_KEY = "showcase-test-secret"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django_showcase",
    "tests.shop",
]
ROOT_URLCONF = "tests.urls"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
