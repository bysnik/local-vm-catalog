import os
import math
import time
import requests
from typing import Dict, Optional, List
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from vn_scraper import VNDBScraper
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

GAMES_FOLDER = os.environ.get('GAMES_FOLDER', './games')
DATA_FOLDER = './data'
CACHE_FILE = os.path.join(DATA_FOLDER, 'games_cache.json')

scraper = VNDBScraper()


def ensure_dirs():
    """Создание необходимых директорий"""
    for d in [GAMES_FOLDER, DATA_FOLDER, 'static/covers', 'static/screenshots']:
        os.makedirs(d, exist_ok=True)


def load_cache() -> Dict:
    """Загрузка кэша"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_cache(cache: Dict):
    """Сохранение кэша"""
    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def download_image(url: str, folder: str, filename: str) -> Optional[str]:
    """
    Скачивание изображения.
    Возвращает локальный путь /static/folder/filename если успешно, иначе внешний URL.
    """
    if not url or not isinstance(url, str):
        return None

    # Определяем расширение
    ext = os.path.splitext(url)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        ext = '.jpg'

    filename = os.path.splitext(filename)[0] + ext
    filepath = os.path.join('static', folder, filename)

    # Если файл уже есть — не скачиваем повторно
    if os.path.exists(filepath):
        return f"/static/{folder}/{filename}"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return f"/static/{folder}/{filename}"
    except Exception as e:
        print(f"⚠️ Не удалось скачать {url}: {e}")

    # Фолбэк на внешний URL
    return url


def download_game_assets(game_info: Dict, folder_name: str) -> Dict:
    """
    Скачивает обложку и скриншоты для игры.
    Обновляет game_info локальными путями.
    """
    # === Обложка ===
    if game_info.get('image') and isinstance(game_info['image'], str):
        ext = os.path.splitext(game_info['image'])[1] or '.jpg'
        local_path = download_image(game_info['image'], 'covers', f"{folder_name}{ext}")
        game_info['local_image'] = local_path

    # === Скриншоты (первые 10) ===
    local_screenshots = []
    for i, ss_url in enumerate(game_info.get('screenshots', [])[:10]):
        if isinstance(ss_url, str):
            ext = os.path.splitext(ss_url)[1] or '.jpg'
            local_path = download_image(ss_url, 'screenshots', f"{folder_name}_{i}{ext}")
            if local_path:
                local_screenshots.append(local_path)
    game_info['local_screenshots'] = local_screenshots

    return game_info


def scan_games(base_path: str) -> Dict[str, List[Dict]]:
    """Сканирование структуры папок: серии и отдельные игры"""
    result = {'series': {}, 'standalone': []}
    if not os.path.exists(base_path):
        return result

    for item in os.listdir(base_path):
        item_path = os.path.join(base_path, item)
        if not os.path.isdir(item_path):
            continue

        # Проверяем, содержит ли папка только подпапки (серия)
        subitems = [f for f in os.listdir(item_path) if os.path.isdir(os.path.join(item_path, f))]
        has_files = any(os.path.isfile(os.path.join(item_path, f)) for f in os.listdir(item_path))

        if subitems and not has_files:
            # Это серия
            games = []
            for sub in subitems:
                subpath = os.path.join(item_path, sub)
                if os.path.isdir(subpath):
                    games.append({'folder': sub, 'path': subpath, 'series': item})
            if games:
                result['series'][item] = games
        else:
            # Отдельная игра
            result['standalone'].append({'folder': item, 'path': item_path, 'series': None})

    return result


def get_folder_contents(folder_path: str, limit: int = 300):
    """Сканирование содержимого папки"""
    items, truncated = [], False
    try:
        for name in os.listdir(folder_path):
            if len(items) >= limit:
                truncated = True
                break
            full = os.path.join(folder_path, name)
            items.append({
                'name': name,
                'is_dir': os.path.isdir(full),
                'size': os.path.getsize(full) if os.path.isfile(full) else 0
            })
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    except:
        pass
    return items, truncated


def fmt_size(b: int) -> str:
    """Форматирование размера файла"""
    if b == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(int(math.log(b, 1024)), len(units) - 1)
    return f"{round(b / (1024 ** i), 2)} {units[i]}"


@app.route('/')
def index():
    """Главная страница — только чтение из кэша, БЕЗ сетевых запросов"""
    ensure_dirs()
    cache = load_cache()
    structure = scan_games(GAMES_FOLDER)

    def get_display_info(folder: str, path: str, series: Optional[str]) -> Dict:
        data = cache.get(folder, {})
        # Проверяем, есть ли локальная обложка
        local_img = None
        if data.get('image'):
            ext = os.path.splitext(data['image'])[1] or '.jpg'
            test_path = os.path.join('static', 'covers', f"{folder}{ext}")
            if os.path.exists(test_path):
                local_img = f"/static/covers/{folder}{ext}"

        return {
            'folder': folder,
            'path': path,
            'series': series,
            'title': data.get('title') or folder,
            'image': data.get('image', ''),
            'local_image': local_img,
            'vndb_url': data.get('vndb_url', ''),
            'tags': data.get('tags', [])[:5] if isinstance(data.get('tags'), list) else [],
            'has_data': bool(data.get('parsed'))
        }

    def apply_filters(games: List[Dict]) -> List[Dict]:
        tag_f = request.args.get('tag', '')
        dev_f = request.args.get('dev', '')
        result = []
        for g in games:
            info = get_display_info(g['folder'], g['path'], g.get('series'))
            data = cache.get(g['folder'], {})
            if tag_f and tag_f not in data.get('tags', []):
                continue
            if dev_f and dev_f not in data.get('developers', []):
                continue
            result.append(info)

        # Сортировка
        sort = request.args.get('sort', 'name')
        if sort == 'released':
            result.sort(key=lambda x: cache.get(x['folder'], {}).get('released') or '9999', reverse=True)
        elif sort == 'title':
            result.sort(key=lambda x: x['title'].lower())
        else:
            result.sort(key=lambda x: x['folder'].lower())
        return result

    standalone = apply_filters(structure['standalone'])
    series_data = {}
    for name, games in structure['series'].items():
        filtered = apply_filters(games)
        if filtered:
            series_data[name] = filtered

    return render_template(
        'index.html',
        standalone_games=standalone,
        series_data=series_data,
        filters={'tags': [], 'devs': []},
        current_filters={k: request.args.get(k, '') for k in ['tag', 'dev', 'series', 'sort']},
        total_standalone=len(standalone),
        total_series=len(series_data)
    )


@app.route('/set_vndb/<path:folder>', methods=['POST'])
def set_vndb(folder: str):
    """Сохранение ручной ссылки VNDB + немедленная загрузка данных и изображений"""
    url = request.form.get('vndb_url', '').strip()
    cache = load_cache()
    existing = cache.get(folder, {'title': folder})

    if url:
        existing['manual_vndb_url'] = url
        # Получаем данные
        data = scraper.fetch_game_data(folder, url)
        if data:
            existing.update(data)
            existing['vndb_url'] = f"https://vndb.org/{data.get('vndb_id', '')}"
            # ✅ СРАЗУ скачиваем изображения
            download_game_assets(existing, folder)

    cache[folder] = existing
    save_cache(cache)
    return redirect(url_for('game_page', game_path=folder))


@app.route('/game/<path:game_path>')
def game_page(game_path: str):
    """Страница игры — ВСЕ данные уже в кэше, изображения уже скачаны"""
    ensure_dirs()
    cache = load_cache()

    folder = game_path.strip('/').split('/')[-1]
    full_path = os.path.join(GAMES_FOLDER, game_path.strip('/'))
    data = cache.get(folder, {})

    # Если вдруг изображения ещё не скачаны (старый кэш) — скачиваем сейчас
    if not data.get('local_image') and data.get('image'):
        download_game_assets(data, folder)
        cache[folder] = data
        save_cache(cache)

    # Содержимое папки
    files, truncated = get_folder_contents(full_path)
    for f in files:
        f['size_str'] = fmt_size(f['size'])

    return render_template(
        'game.html',
        game=data,
        folder=folder,
        full_path=game_path,
        folder_contents=files,
        is_truncated=truncated
    )


@app.route('/refresh')
def refresh():
    """
    Обновление кэша с ПРЕДЗАГРУЗКОЙ всех изображений.
    После этого все страницы грузятся мгновенно.
    """
    ensure_dirs()
    cache = load_cache()
    structure = scan_games(GAMES_FOLDER)

    all_games = structure['standalone'] + [g for series in structure['series'].values() for g in series]
    updated = 0

    for game in all_games:
        folder = game['folder']
        existing = cache.get(folder, {})

        # Обновляем ТОЛЬКО если данных ещё нет
        if not existing.get('parsed'):
            print(f"🔄 {folder}...")
            data = scraper.fetch_game_data(folder, existing.get('manual_vndb_url'))

            if data:
                # Объединяем с существующими данными
                merged = {**existing, **data}
                # ✅ СРАЗУ скачиваем ВСЕ изображения
                print(f"   📥 Скачиваем изображения...")
                download_game_assets(merged, folder)

                cache[folder] = merged
                print(f"   ✅ Готово")
                updated += 1
            else:
                # Если не нашли — сохраняем хотя бы название
                cache[folder] = {**existing, 'title': folder}

        time.sleep(0.5)  # Вежливая задержка для API

    save_cache(cache)

    # Редирект с мета-тегом
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta http-equiv="refresh" content="2;url={url_for('index')}">
    <title>Готово</title>
    <style>
        body{{font-family:sans-serif;text-align:center;padding:50px;
        background:linear-gradient(135deg,#667eea,#764ba2);color:white}}
        .box{{background:rgba(255,255,255,0.95);color:#333;padding:2rem;
        border-radius:12px;display:inline-block}}
    </style></head>
    <body><div class="box">
        <h2>✅ Обновление завершено!</h2>
        <p>Обновлено: <strong>{updated}</strong> игр</p>
        <p>🖼️ Все обложки и скриншоты скачаны</p>
        <p>Возврат на главную...</p>
    </div></body></html>'''


@app.route('/static/<path:f>')
def static_file(f):
    """Явная раздача статики"""
    return send_from_directory('static', f)


if __name__ == '__main__':
    ensure_dirs()
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
