"""Константы интеграции Domyland."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "domyland"

# --- Внешние сервисы ---------------------------------------------------------

# База customer-api платформы Domyland (проверено curl'ом вне приложения).
API_BASE = "https://customer-api.domyland.ru"

# Яндекс OAuth client_id приложения «Домиленд+» (namespace ru.domyland.superdom).
# Извлечён из перехвата (login.yandex.ru/info по рабочему токену вернул этот cid).
# Нужен только чтобы собрать ссылку implicit-авторизации — секрет для этого не требуется.
YANDEX_CLIENT_ID = "e9f2a97b605c4ad8aad0a3b3e68658af"
YANDEX_AUTHORIZE_URL = (
    f"https://oauth.yandex.ru/authorize?response_type=token&client_id={YANDEX_CLIENT_ID}"
)

# --- Заголовки, которые бэкенд Domyland требует на каждый запрос -------------

# Брендовая строка сборки. На выбор дома НЕ влияет (дом задаётся placeId/buildingId),
# поэтому берём нейтральную сборку «Домиленд+».
APP_NAME = "superdom-android"
ORIGINAL_APP_NAME = "superdom-android"
APP_VERSION = "4.23.1"
USER_AGENT = "okhttp/5.3.2"

# --- Config entry ------------------------------------------------------------

CONF_YANDEX_TOKEN = "yandex_token"  # x-yandex-oauth
CONF_JWT = "jwt"  # Authorization (JWT domyland, живёт ~10 лет)
CONF_CUSTOMER_ID = "customer_id"
CONF_CUSTOMER_NAME = "customer_name"
CONF_ENABLE_CAMERAS = "enable_cameras"

DEFAULT_ENABLE_CAMERAS = True

# --- Coordinator -------------------------------------------------------------

# streamURL камер подписаны и, предположительно, перевыпускаются при каждом
# GET /cameras — обновляем данные достаточно часто, чтобы ссылки не протухали,
# и чтобы подтягивались новые/убранные двери.
UPDATE_INTERVAL = timedelta(minutes=5)

# Таймаут HTTP-запросов к API.
REQUEST_TIMEOUT = 30

MANUFACTURER = "Domyland / UJIN"
