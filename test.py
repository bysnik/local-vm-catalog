import requests
from bs4 import BeautifulSoup

url = "https://vndb.org/v?sq=Kanon"
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(resp.text, 'lxml')

print(f"Финальный URL: {resp.url}")
print(f"Статус: {resp.status_code}")

table = soup.find('table')
if table:
    print(f"\nНайдено строк: {len(table.find_all('tr'))}")
    for i, row in enumerate(table.find_all('tr')[:10]):
        cells = row.find_all('td')
        if len(cells) >= 2:
            link = cells[0].find('a', href=True)
            if link:
                print(f"{i}. {link.text.strip():40} → {link['href']} (title='{link.get('title', '')}')")
