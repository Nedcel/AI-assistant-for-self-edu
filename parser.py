import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from typing import List, Dict, Optional
import time
import random

class ConferenceParser:
    def __init__(self):
        self.base_url = "https://all-events.ru/events/calendar/city-is-moskva/type-is-conferencia/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('parser.log'),
                logging.StreamHandler()
            ]
        )

    def parse_conferences(self, pages: int = 3) -> List[Dict]:
        """Парсинг конференций с нескольких страниц"""
        conferences = []
        
        for page in range(1, pages + 1):
            logging.info(f"Парсинг страницы {page}")
            url = f"{self.base_url}?PAGEN_1={page}"
            
            try:
                page_data = self.parse_page(url)
                conferences.extend(page_data)
                time.sleep(random.uniform(1, 3))  # Задержка для избежания блокировки
            except Exception as e:
                logging.error(f"Ошибка при парсинге страницы {page}: {str(e)}")
                continue
                
        logging.info(f"Всего найдено {len(conferences)} конференций")
        return conferences

    def parse_page(self, url: str) -> List[Dict]:
        """Парсинг одной страницы с конференциями"""
        response = self.session.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        conference_blocks = soup.find_all('div', class_='event_flex_item')
        
        conferences = []
        for block in conference_blocks:
            try:
                conference = self.parse_conference_block(block)
                if conference:
                    conferences.append(conference)
            except Exception as e:
                logging.warning(f"Ошибка при парсинге блока конференции: {str(e)}")
                continue
                
        return conferences

    def parse_conference_block(self, block) -> Optional[Dict]:
        """Парсинг отдельного блока с конференцией"""
        title_elem = block.find('a', class_='event_name_new')
        if not title_elem:
            return None
            
        title = title_elem.text.strip()
        url = title_elem.get('href', '')
        if url and not url.startswith('http'):
            url = f"https://all-events.ru{url}"
            
        date_elem = block.find('div', class_='event_date')
        date = self.normalize_date(date_elem.text.strip() if date_elem else '')
        
        place_elem = block.find('div', class_='event_place')
        place = place_elem.text.strip() if place_elem else 'Не указано'
        
        price_elem = block.find('div', class_='event_price')
        price = price_elem.text.strip() if price_elem else 'Бесплатно'
        
        return {
            'title': title,
            'url': url,
            'date': date,
            'place': place,
            'price': price,
            'source': 'all-events.ru',
            'parsed_at': datetime.now().isoformat(),
            'categories': self.extract_categories(block)
        }

    def extract_categories(self, block) -> List[str]:
        """Извлечение категорий/тегов конференции"""
        categories = []
        tags = block.find_all('a', class_='event_tag')
        for tag in tags:
            categories.append(tag.text.strip().lower())
        return categories

    def save_to_json(self, data: List[Dict], filename: str = 'conferences.json'):
        """Сохранение данных в JSON файл"""
        import json
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Данные сохранены в {filename}")

if __name__ == "__main__":
    parser = ConferenceParser()
    conferences = parser.parse_conferences(pages=3)

    # Сохранение всех данных в файл
    parser.save_to_json(conferences)