#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VNDB Scraper — финальная версия с надёжным поиском и корректной записью URL в кэш"""
import requests
import json
import re
import time
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
from urllib.parse import quote

DEBUG = False

def dprint(*args, level: int = 1, **kwargs):
    """Умный вывод отладочной информации"""
    if DEBUG:
        prefix = "[DEBUG] " + "  " * (level - 1)
        print(prefix, *args, **kwargs)


class VNDBScraper:
    """Скрапер для VNDB.org с поддержкой HTML-парсинга и API"""

    def __init__(self, debug: bool = False):
        self.api_url = "https://api.vndb.org/kana"
        self.headers = {
            'User-Agent': 'VN-Catalog/1.0 (by your@email)',
            'Content-Type': 'application/json'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.debug = debug
        dprint("🔧 VNDBScraper инициализирован", level=1)

    # ─────────────────────────────────────────────────────────────
    # УЛУЧШЕННАЯ нормализация
    # ─────────────────────────────────────────────────────────────
    def _normalize_for_compare(self, s: str) -> str:
        """Приводит строку к сравниваемому виду"""
        if not s:
            return ''
        s = s.lower().strip()
        # ✅ Удаляем только чистые иероглифы, оставляем романизацию, цифры, латиницу
        s = re.sub(r'[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uffef\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af]+', ' ', s)
        # ✅ Заменяем спецсимволы на пробелы, но сохраняем буквы
        s = re.sub(r'[\~\`\!\@\#\$\%\^\&\*\(\)\_\+\=\-\[\]\{\}\\\|\;\:\'\"\<\>\,\.\?\/]+', ' ', s)
        # Нормализация пробелов
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _titles_match(self, target: str, found: str) -> bool:
        """Умное сравнение названий с учётом подзаголовков, сокращений"""
        t_norm = self._normalize_for_compare(target)
        f_norm = self._normalize_for_compare(found)

        if not t_norm or not f_norm:
            return False

        # 1. Прямое вхождение
        if t_norm in f_norm or f_norm in t_norm:
            return True

        # 2. Сравнение по ключевым словам (первые 3-4 слова)
        t_words = set(t_norm.split()[:4])
        f_words = set(f_norm.split())
        if t_words and f_words and len(t_words & f_words) >= 2:
            return True

        # 3. Убираем подзаголовки в скобках/тильдах и сравниваем основу
        t_base = re.sub(r'[\(\[\{~].*$', '', t_norm).strip()
        f_base = re.sub(r'[\(\[\{~].*$', '', f_norm).strip()
        if t_base and f_base and (t_base in f_base or f_base in t_base):
            return True

        return False

    def extract_vndb_id(self, url: str) -> Optional[str]:
        """Извлекает VNDB ID из URL"""
        if not url:
            return None
        match = re.search(r'(?:vndb\.org/|id[:\s])(v?\d+)', url, re.IGNORECASE)
        if match:
            vn_id = match.group(1)
            return vn_id if vn_id.startswith('v') else f'v{vn_id}'
        return None

    # ─────────────────────────────────────────────────────────────
    # НАДЁЖНЫЙ поиск по названию
    # ─────────────────────────────────────────────────────────────
    def search_by_title_exact(self, title: str) -> Optional[str]:
        """Поиск по названию через HTML-поиск VNDB — с обработкой авто-редиректа"""
        dprint(f"🔍 ПОИСК: '{title}'", level=1)

        try:
            clean_title = re.sub(r'[^\w\sа-яА-ЯёЁ\-~]', ' ', title).strip()
            clean_title = re.sub(r'\s+', ' ', clean_title)
            query = quote(clean_title)
            search_url = f"https://vndb.org/v?sq={query}&sb=Search!"
            dprint(f"🌐 URL: {search_url}", level=2)

            resp = self.session.get(
                search_url,
                timeout=10,
                headers={'User-Agent': self.headers['User-Agent']},
                allow_redirects=True
            )

            # ✅ ПРОВЕРКА: если нас редиректнуло на страницу игры — извлекаем ID сразу!
            final_url = resp.url
            dprint(f"🔗 Финальный URL: {final_url}", level=2)

            match = re.search(r'https://vndb\.org/(v\d+)', final_url)
            if match:
                vn_id = match.group(1)
                dprint(f"✅ Авто-редирект на страницу игры! ID: {vn_id}", level=1)
                return vn_id

            if resp.status_code != 200:
                dprint(f"❌ HTTP {resp.status_code}", level=1)
                return None

            soup = BeautifulSoup(resp.text, 'lxml')

            if soup.find('p') and 'no results' in soup.find('p').text.lower():
                dprint("❌ Страница 'No results'", level=1)
                return None

            table = soup.find('table')
            if not table:
                dprint("❌ Таблица не найдена", level=1)
                return None

            dprint(f"🎯 Цель: '{self._normalize_for_compare(title)}'", level=2)

            for row in table.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) < 2:
                    continue

                title_cell = cells[0]
                link = title_cell.find('a', href=re.compile(r'^/v\d+'))
                if not link:
                    continue

                candidates = []
                # 🔥 ЦЕЛЕВАЯ ОТЛАДКА — вставьте ВНУТРЬ цикла, ПЕРЕД поиском link:
                row_index = list(table.find_all('tr')).index(row)  # Номер строки
                dprint(f"\n🔎 Строка #{row_index}:", level=3)
                dprint(f"   Ячеек: {len(cells)}", level=3)
                dprint(f"   Текст первой ячейки: '{cells[0].text.strip()[:60]}'", level=3)

                link = title_cell.find('a', href=re.compile(r'^/v\d+'))
                dprint(f"   🔗 Link найден: {link is not None}", level=3)

                if link:
                    dprint(f"   🔗 href: '{link.get('href')}'", level=3)
                    dprint(f"   🔗 text: '{link.text.strip()}'", level=3)
                    dprint(f"   🔗 title attr: '{link.get('title', '')}'", level=3)

                    # Проверка нормализации
                    found_title = link.text.strip()
                    t_norm = self._normalize_for_compare(title)
                    f_norm = self._normalize_for_compare(found_title)
                    dprint(f"   🎯 target_norm: '{t_norm}'", level=3)
                    dprint(f"   📋 found_norm:  '{f_norm}'", level=3)
                    dprint(f"   ✅ _titles_match: {self._titles_match(title, found_title)}", level=3)
                link_text = link.text.strip()
                link_title = link.get('title', '').strip()
                if link_text:
                    candidates.append(link_text)
                if link_title and link_title != link_text:
                    candidates.append(link_title)

                found_href = link.get('href', '')

                for found_title in candidates:
                    dprint(f"📋 Проверяем: '{found_title}'", level=2)
                    if self._titles_match(title, found_title):
                        vn_id = found_href.split('/')[-1]
                        result_id = f"v{vn_id}" if not vn_id.startswith('v') else vn_id
                        dprint(f"✅ СОВПАДЕНИЕ! Возвращаем: {result_id}", level=1)
                        return result_id

            dprint(f"❌ Не найдено совпадений", level=1)
            return None

        except Exception as e:
            dprint(f"💥 Ошибка: {e}", level=1)
            import traceback
            dprint(traceback.format_exc(), level=2)
            return None

    # ─────────────────────────────────────────────────────────────
    # Поиск по ID через API
    # ─────────────────────────────────────────────────────────────
    def search_by_id(self, vn_id: str) -> Optional[Dict]:
        """Поиск данных по ID через официальный API VNDB"""
        if not vn_id.startswith('v'):
            vn_id = f'v{vn_id}'

        dprint(f"🔍 ПОИСК ПО ID: {vn_id}", level=1)

        try:
            query = {
                "filters": [["id", "=", vn_id]],
                "fields": "id,title,description,image.url,screenshots.url,tags.name,tags.category,released,langs,devs.name,devs.id"
            }
            response = self.session.post(f"{self.api_url}/vn", json=query, timeout=10)

            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                if results:
                    return results[0]
        except Exception as e:
            dprint(f"💥 API ошибка: {e}", level=1)

        return None

    # ─────────────────────────────────────────────────────────────
    # Парсинг страницы
    # ─────────────────────────────────────────────────────────────
    def parse_vndb_page(self, url: str) -> Optional[Dict]:
        """Парсит страницу VNDB и извлекает структурированные данные"""
        dprint(f"📄 ПАРСИНГ: {url}", level=1)

        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, 'lxml')

            # ✅ Инициализация с полями для URL
            data: Dict[str, any] = {
                'title': '', 'description': '', 'description_plain': '',
                'image': '', 'screenshots': [], 'tags': [], 'released': '',
                'developers': [], 'developer_links': {}, 'releases_ru': [],
                'vndb_id': '', 'vndb_url': '', 'manual_vndb_url': '',  # ← Добавлено
                'parsed': True
            }

            # ✅ ID и URL
            match = re.search(r'/v(\d+)', url)
            if match:
                data['vndb_id'] = f"v{match.group(1)}"
                data['vndb_url'] = f"https://vndb.org/{data['vndb_id']}"  # ← Добавлено

            # ✅ Название — с улучшенными фолбэками
            title = ''
            h1 = soup.find('h1', attrs={'lang': True})
            if not h1:
                main = soup.find('main')
                if main:
                    h1 = main.find('h1')
            if h1:
                title = h1.text.strip()
            if not title:
                og = soup.find('meta', property='og:title')
                if og and og.get('content'):
                    title = og['content'].split(' | ')[0].strip()
            if not title:
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.text.split(' | ')[0].strip()
            data['title'] = title
            dprint(f"📛 Название: '{title}'", level=2)

            # Обложка
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                data['image'] = og_image['content']
            else:
                vnimg = soup.find('div', class_='vnimg')
                if vnimg:
                    img = vnimg.find('img', src=True)
                    if img and img.get('src'):
                        data['image'] = img['src'].replace('/cv.t/', '/cv/')

            # Описание из td.vndesc
            vndesc = soup.find('td', class_='vndesc')
            if vndesc:
                p = vndesc.find('p')
                if p:
                    data['description'] = p.decode_contents().strip()
                    data['description_plain'] = p.get_text(' ', strip=True)

            # Скриншоты
            scr = soup.find('article', id='screenshots')
            if scr:
                for div in scr.find_all('div', class_='scr'):
                    for img in div.find_all('img', src=True):
                        if 'nsfw' not in img.get('class', []) and img.get('src'):
                            src = img['src'].replace('/sf.t/', '/sf/')
                            if src not in data['screenshots']:
                                data['screenshots'].append(src)

            # Теги
            vntags = soup.find('div', id='vntags')
            if vntags:
                for span in vntags.find_all('span', class_=re.compile(r'tagspl')):
                    a = span.find('a', href=re.compile(r'^/g\d+'))
                    if a and a.text.strip():
                        tag = a.text.strip()
                        if tag and tag not in data['tags']:
                            data['tags'].append(tag)

            # Разработчики
            table = soup.find('table', class_='stripe')
            if table:
                for row in table.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) >= 2 and 'developer' in cells[0].text.lower():
                        for a in cells[1].find_all('a', href=re.compile(r'^/p\d+')):
                            name = a.text.strip()
                            href = a.get('href', '')
                            if name and href:
                                if name not in data['developers']:
                                    data['developers'].append(name)
                                data['developer_links'][name] = f"https://vndb.org{href}"

            # Русские релизы
            data['releases_ru'] = self._parse_ru_releases(soup)

            # Чистка
            data['tags'] = list(dict.fromkeys(t for t in data['tags'] if isinstance(t, str) and t))
            data['screenshots'] = list(dict.fromkeys(s for s in data['screenshots'] if isinstance(s, str) and s))
            data['developers'] = list(dict.fromkeys(d for d in data['developers'] if isinstance(d, str) and d))

            if data['title']:
                dprint(f"✅ Парсинг успешен", level=1)
                return data
            return None

        except Exception as e:
            dprint(f"💥 Ошибка парсинга: {e}", level=1)
            return None

    def _parse_ru_releases(self, soup: BeautifulSoup) -> List[Dict]:
        """Извлекает информацию о русских релизах"""
        releases = []
        try:
            for details in soup.find_all('details'):
                summary = details.find('summary')
                if not summary:
                    continue
                abbr = summary.find('abbr', title=lambda t: t and 'russian' in t.lower())
                if not abbr:
                    continue
                table = details.find('table', class_='releases')
                if not table:
                    continue
                for row in table.find_all('tr')[1:]:
                    cells = row.find_all('td')
                    if len(cells) < 4:
                        continue
                    rel = {
                        'date': cells[0].text.strip(),
                        'rating': cells[1].text.strip(),
                        'platform': cells[2].text.strip(),
                        'name': '', 'name_link': '', 'link_url': ''
                    }
                    name_a = cells[3].find('a', href=re.compile(r'^/r\d+'))
                    if name_a:
                        rel['name'] = name_a.text.strip()
                        rel['name_link'] = f"https://vndb.org{name_a['href']}"
                    else:
                        rel['name'] = cells[3].text.strip()
                    links_cell = cells[-1] if len(cells) >= 7 else None
                    if links_cell:
                        link_a = links_cell.find('a', href=lambda h: h and h.startswith('http'))
                        if link_a:
                            rel['link_url'] = link_a['href']
                    if rel['name']:
                        releases.append(rel)
                        break
        except:
            pass
        return releases

    # ─────────────────────────────────────────────────────────────
    # Основной метод
    # ─────────────────────────────────────────────────────────────
    def fetch_game_data(self, title: str, manual_url: Optional[str] = None) -> Optional[Dict]:
        """
        Главный метод: получает данные игры по названию или ручному URL.
        Гарантирует запись vndb_id, vndb_url, manual_vndb_url в результат.
        """
        dprint(f"\n{'='*60}\n🎮 ЗАПРОС: '{title}'\n{'='*60}\n", level=0)

        # 1. Ручная ссылка — приоритет
        if manual_url:
            vndb_id = self.extract_vndb_id(manual_url)
            if vndb_id:
                page_url = f"https://vndb.org/{vndb_id}"
                data = self.parse_vndb_page(page_url)
                if data:
                    # ✅ Гарантируем запись всех трёх полей
                    data['manual_vndb_url'] = manual_url  # ← Явно переданный URL
                    dprint(f"✅ По ручной ссылке: {manual_url}", level=0)
                    return data

        # 2. Поиск по названию
        vndb_id = self.search_by_title_exact(title)
        if vndb_id:
            page_url = f"https://vndb.org/{vndb_id}"
            data = self.parse_vndb_page(page_url)
            if data:
                # ✅ Если manual_url не задан, но нашли через поиск — записываем найденный URL
                if not data.get('manual_vndb_url'):
                    data['manual_vndb_url'] = page_url
                dprint(f"✅ Успех через поиск! {page_url}", level=0)
                return data

        dprint(f"❌ Не найдено", level=0)
        return None

    # ─────────────────────────────────────────────────────────────
    # Для совместимости
    # ─────────────────────────────────────────────────────────────
    def get_game_info(self, title: str, manual_url: Optional[str] = None,
                      existing_data: Optional[Dict] = None, force_fetch: bool = False) -> Dict:
        """
        Обёртка для обратной совместимости.
        Гарантирует запись vndb_id, vndb_url, manual_vndb_url в кэш.
        """
        # Если есть кэш и не требуется обновление — возвращаем как есть
        if existing_data and existing_data.get('parsed') and not force_fetch:
            return existing_data

        # Шаблон результата — с пустыми значениями для URL
        result = existing_data.copy() if existing_data else {
            'title': title, 'description': '', 'description_plain': '',
            'image': '', 'screenshots': [], 'tags': [], 'released': '',
            'developers': [], 'developer_links': {}, 'releases_ru': [],
            'vndb_id': '', 'vndb_url': '', 'manual_vndb_url': manual_url or '',  # ← manual_vndb_url из параметра
            'parsed': False, 'fetched': False
        }

        # Пытаемся получить свежие данные
        data = self.fetch_game_data(title, manual_url)
        if data:
            result.update(data)  # Обновляем всеми полями из data

            # ✅ Гарантируем, что все три поля заполнены корректно
            if data.get('vndb_id') and not result.get('vndb_url'):
                result['vndb_url'] = f"https://vndb.org/{data['vndb_id']}"

            # manual_vndb_url: приоритет — явный параметр, затем найденный через поиск
            if manual_url:
                result['manual_vndb_url'] = manual_url
            elif data.get('vndb_id') and not result.get('manual_vndb_url'):
                result['manual_vndb_url'] = f"https://vndb.org/{data['vndb_id']}"

            result['parsed'] = True
            result['fetched'] = True

        return result

    def _format_api_data(self, data: Dict) -> Dict:
        """Конвертирует ответ API в формат, совместимый с HTML-парсером"""
        developers = []
        developer_links = {}

        for dev in data.get('devs', []):
            if dev.get('name'):
                developers.append(dev['name'])
                if dev.get('id'):
                    developer_links[dev['name']] = f"https://vndb.org/{dev['id']}"

        vndb_id = data.get('id', '')

        return {
            'vndb_id': vndb_id,
            'vndb_url': f"https://vndb.org/{vndb_id}" if vndb_id else '',  # ← Добавлено
            'manual_vndb_url': '',  # ← Добавлено: для API-запросов оставляем пустым
            'title': data.get('title', ''),
            'description': data.get('description', ''),
            'description_plain': data.get('description', ''),
            'image': data.get('image', {}).get('url', '') if data.get('image') else '',
            'screenshots': [s.get('url', '') for s in data.get('screenshots', []) if s.get('url')],
            'tags': [t.get('name', '') for t in data.get('tags', []) if t.get('name')],
            'released': data.get('released', ''),
            'developers': developers,
            'developer_links': developer_links,
            'releases_ru': [],  # API не возвращает информацию о релизах по языкам
            'parsed': True,
            'fetched': True
        }


# ─────────────────────────────────────────────────────────────
# Тест
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    if '--debug' in sys.argv:
        DEBUG = True

    print("🧪 ТЕСТ VNDB Scraper")
    scraper = VNDBScraper(debug=DEBUG)

    tests = [
        ("Higurashi no Naku Koro ni Kai", None),
        ("Hikari no Valusia", None),
        ("Higanbana no Saku Yoru ni - Dai Ni Ya", None),
        ("Little Busters", None),
        ("AIR", "https://vndb.org/v36"),  # Проблемный кейс с ручной ссылкой
    ]

    for title, url in tests:
        print(f"\n{'#'*60}")
        print(f"ТЕСТ: {title}" + (f" | URL: {url}" if url else ""))
        print(f"{'#'*60}")

        result = scraper.fetch_game_data(title, manual_url=url)

        if result:
            print(f"✅ {result.get('title')} (ID: {result.get('vndb_id')})")
            print(f"   📝 Описание: {len(result.get('description_plain', ''))} симв.")
            print(f"   🖼️ Обложка: {'✓' if result.get('image') else '✗'}")
            print(f"   📸 Скриншоты: {len(result.get('screenshots', []))}")
            print(f"   🔗 vndb_url: {result.get('vndb_url')}")
            print(f"   🔗 manual_vndb_url: {result.get('manual_vndb_url')}")
        else:
            print("❌ Не найдено")

        time.sleep(2)

    print(f"\n🏁 Готово!")
