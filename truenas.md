services:
  vn-catalog:
    image: python:3.12-slim
    read_only: false
    restart: unless-stopped
    working_dir: /app
    environment:
      TZ: Europe/Moscow
      FLASK_RUN_HOST: "0.0.0.0"
      FLASK_RUN_PORT: "5000"
    ports:
      - "5000:5000"
    command: ["sh", "-c", "pip install --no-cache-dir -r requirements.txt && python3 app.py"]
    volumes:
      # Фактические права на файлах контролируются ACL датасета, а не контейнером.
      - type: bind
        source: /mnt/base/vn-catalog
        target: /app
      # Игры монтируем отдельно в read-only
      - type: bind
        source: /mnt/base/games/novells
        target: /app/games
        read_only: true

x-portals:
  - host: 0.0.0.0
    name: VN Catalog
    path: /
    port: 5000
    scheme: http
