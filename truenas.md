# 🐳 TrueNAS SCALE App Config для VN Catalog (без сборки образа)

Вот готовый `docker-compose` конфиг в формате TrueNAS SCALE для вашего приложения. Используется официальный образ `python:3.12-slim`, код монтируется как volume, зависимости устанавливаются при старте.

```yaml
configs:
  permissions_actions_data:
    content: >-
      [
        {"read_only": false, "mount_path": "/app/data", "is_temporary": false, "identifier": "vn_catalog_data", "recursive": true, "mode": "check", "uid": 1000, "gid": 1000, "chmod": null},
        {"read_only": false, "mount_path": "/app/static", "is_temporary": false, "identifier": "vn_catalog_static", "recursive": true, "mode": "check", "uid": 1000, "gid": 1000, "chmod": null},
        {"read_only": true, "mount_path": "/mnt/permission/vn_catalog_games", "is_temporary": false, "identifier": "vn_catalog_games", "recursive": true, "mode": "check", "uid": 1000, "gid": 1000, "chmod": null}
      ]

networks:
  ix-internal-vn-catalog-net:
    enable_ipv6: false
    external: false
    labels:
      tn.network.internal: 'true'

services:
  vn-catalog:
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
      - NET_BIND_SERVICE
    cap_drop:
      - ALL
    depends_on:
      permissions:
        condition: service_completed_successfully
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1024M
    environment:
      # Пользователь/группа для запуска (должны совпадать с хостом)
      PUID: '1000'
      PGID: '1000'
      UID: '1000'
      GID: '1000'
      USER_ID: '1000'
      GROUP_ID: '1000'
      # Таймзона
      TZ: Europe/Moscow
      # Flask настройки
      FLASK_ENV: production
      FLASK_RUN_HOST: 0.0.0.0
      FLASK_RUN_PORT: '5000'
      # Путь к библиотеке игр (можно переопределить при деплое)
      VN_GAMES_PATH: /app/games
    group_add:
      - 1000
    healthcheck:
      test:
        - CMD-SHELL
        - python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/')" || exit 1
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 45s
    image: python:3.12-slim
    networks:
      ix-internal-vn-catalog-net: {}
    platform: linux/amd64
    ports:
      - mode: ingress
        protocol: tcp
        published: 5000
        target: 5000
    privileged: false
    restart: unless-stopped
    security_opt:
      - no-new-privileges=true
    stdin_open: false
    stop_grace_period: 30s
    tty: false
    # Установка зависимостей + запуск (только если requirements.txt изменился)
    command: >
      sh -c "
        apk add --no-cache curl &&
        if [ ! -f /app/.deps_installed ] || [ /app/requirements.txt -nt /app/.deps_installed ]; then
          pip install --no-cache-dir -r /app/requirements.txt && touch /app/.deps_installed;
        fi &&
        exec python3 /app/app.py
      "
    working_dir: /app
    volumes:
      # 📁 Исходный код приложения (read-only)
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: true
        source: /mnt/your-pool/vn_catalog/app_code
        target: /app
        type: bind
      # 🎮 Библиотека игр (read-only — только чтение файлов)
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: true
        source: /mnt/your-pool/vn_catalog/games
        target: /app/games
        type: bind
      # 💾 Кэш данных (writable — games_cache.json)
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: false
        source: /mnt/your-pool/vn_catalog/data
        target: /app/data
        type: bind
      # 🖼️ Обложки и скриншоты (writable — скачиваются с VNDB)
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: false
        source: /mnt/your-pool/vn_catalog/static
        target: /app/static
        type: bind

  permissions:
    # Вспомогательный контейнер для настройки прав на томах
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
    cap_drop:
      - ALL
    configs:
      - mode: 320
        source: permissions_actions_data
        target: /script/actions.json
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
    entrypoint:
      - python3
      - /script/permissions.py
    environment:
      PUID: '1000'
      PGID: '1000'
      UID: '1000'
      GID: '1000'
      TZ: Europe/Moscow
    group_add:
      - 1000
    healthcheck:
      disable: true
    image: ixsystems/container-utils:1.0.2
    network_mode: none
    platform: linux/amd64
    privileged: false
    restart: on-failure:1
    security_opt:
      - no-new-privileges=true
    stdin_open: false
    tty: false
    user: '0:0'
    volumes:
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: false
        source: /mnt/your-pool/vn_catalog/data
        target: /mnt/permission/vn_catalog_data
        type: bind
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: false
        source: /mnt/your-pool/vn_catalog/static
        target: /mnt/permission/vn_catalog_static
        type: bind
      - bind:
          create_host_path: false
          propagation: rprivate
        read_only: true
        source: /mnt/your-pool/vn_catalog/games
        target: /mnt/permission/vn_catalog_games
        type: bind

volumes: {}

x-notes: >
  # 📚 VN Catalog

  Каталог визуальных новелл с авто-подгрузкой метаданных с VNDB.

  ## 🔐 Безопасность

  ### Контейнер: [vn-catalog]
  - Запускается от пользователя 1000:1000
  - Ограниченные capabilities (только необходимые)
  - no-new-privileges: enabled
  - Сетевой доступ: только внутренний + проброшенный порт 5000

  ### Контейнер: [permissions]
  - **Короткоживущий**: выполняется только для настройки прав
  - Запускается от root, но с минимальными привилегиями

  ## 📁 Структура томов
  | Том | Путь в контейнере | Доступ | Назначение |
  |-----|------------------|--------|-----------|
  | app_code | `/app` | read-only | Исходный код приложения |
  | games | `/app/games` | read-only | Ваша библиотека новелл |
  | data | `/app/data` | read-write | Кэш: games_cache.json |
  | static | `/app/static` | read-write | Обложки и скриншоты с VNDB |

  ## 🌐 Доступ
  - Веб-интерфейс: `http://<ваш-сервер>:5000`
  - Порт настраивается в интерфейсе TrueNAS при установке

  ## 🔗 Ссылки
  - [Исходный код на GitHub](https://github.com/bysnik/vn_catalog)
  - [VNDB API](https://api.vndb.org/kana)

  ## 🐛 Баги и предложения
  Создавайте 이슈 на GitHub: https://github.com/bysnik/vn_catalog/issues

x-portals:
  - host: 0.0.0.0
    name: VN Catalog Web UI
    path: /
    port: 5000
    scheme: http
```

---

## ⚙️ Что нужно заменить перед деплоем

1. **Пути к томам** (`source:` в `volumes:`):
   ```yaml
   # Замените /mnt/your-pool/vn_catalog/... на реальные пути в вашей системе
   source: /mnt/your-pool/vn_catalog/app_code  # ← сюда скопируйте файлы приложения
   source: /mnt/your-pool/vn_catalog/games     # ← сюда ваша библиотека новелл
   source: /mnt/your-pool/vn_catalog/data      # ← для кэша
   source: /mnt/your-pool/vn_catalog/static    # ← для обложек/скриншотов
   ```

2. **UID/GID**: Если ваш пользователь на хосте не `1000:1000`, замените во всех `environment:` и `configs:`.

3. **Таймзона**: `TZ: Europe/Moscow` → ваша, если нужно.

---

## 💡 Важные нюансы

### 🔹 Почему `apk add curl` в команде?
Образ `python:3.12-slim` основан на Alpine, где нет `curl` по умолчанию. Healthcheck использует Python-урлитил, чтобы не зависеть от curl.

### 🔹 Установка зависимостей только при изменении
```bash
if [ ! -f /app/.deps_installed ] || [ /app/requirements.txt -nt /app/.deps_installed ]; then
  pip install ... && touch /app/.deps_installed
fi
```
Это предотвращает повторную установку пакетов при каждом рестарте контейнера.

### 🔹 Почему игры монтируются read-only?
Приложение только читает файлы игр, но пишет метаданные в `data/` и `static/`. Это повышает безопасность и предотвращает случайное изменение вашей коллекции.

### 🔹 permissions-контейнер
Использует официальный `ixsystems/container-utils` от TrueNAS для корректной установки прав на томах **до** запуска основного приложения. Не удаляйте его — без него могут быть проблемы с доступом к файлам.

---

## 🚀 Альтернатива: ещё проще (без permissions-контейнера)

Если вы уверены в правах на хосте и хотите минимизировать конфиг, можно убрать сервис `permissions` и `configs`, а в основном контейнере добавить:

```yaml
user: '1000:1000'
```

Но тогда убедитесь, что папки `data/` и `static/` уже имеют правильные права (`chown -R 1000:1000`) на хосте.

---

Нужно помочь с адаптацией под конкретную структуру пулов в вашем TrueNAS? Или добавить переменные для настройки порта/пути к играм через UI? 🛠️
