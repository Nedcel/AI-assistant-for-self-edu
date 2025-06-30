import sqlite3
from sqlite3 import Error
from typing import List, Dict, Optional, Union
import logging
from datetime import datetime
from contextlib import contextmanager
import json

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('database.log'),
        logging.StreamHandler()
    ]
)

class DatabaseManager:
    def __init__(self, db_path: str = 'recommendations.db'):
        self.db_path = db_path
        self._initialize_db()
        
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для управления соединением с БД"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Для доступа к полям по имени
            yield conn
        except Error as e:
            logging.error(f"Database error: {str(e)}")
            raise
        finally:
            if conn:
                conn.close()

    def _initialize_db(self):
        """Инициализация структуры БД"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица мероприятий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    date TEXT,
                    location TEXT,
                    tags TEXT,
                    description TEXT,
                    url TEXT UNIQUE,
                    source TEXT,
                    popularity INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            
            # Таблица курсов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    provider TEXT,
                    tags TEXT,
                    description TEXT,
                    start_date TEXT,
                    url TEXT UNIQUE,
                    duration TEXT,
                    price REAL,
                    rating REAL,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    preferences TEXT,  # JSON-строка с предпочтениями
                    registration_date TEXT DEFAULT (datetime('now')),
                    last_activity TEXT DEFAULT (datetime('now'))
                )
            ''')
            
            # Таблица взаимодействий (лайки, просмотры и т.д.)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(user_id),
                    item_id INTEGER,
                    item_type TEXT CHECK(item_type IN ('event', 'course')),
                    interaction_type TEXT CHECK(interaction_type IN ('view', 'like', 'dislike', 'bookmark')),
                    timestamp TEXT DEFAULT (datetime('now'))
                )
            ''')
            
            # Индексы для ускорения поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_tags ON events(tags)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_courses_tags ON courses(tags)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id)')
            
            conn.commit()
            logging.info("Database initialized successfully")

    def _fill_initial_data(self):
        """Заполнение начальными данными (для демонстрации)"""
        initial_events = [
            {
                "title": "Конференция по машинному обучению",
                "date": "2025-06-20",
                "location": "Москва",
                "tags": "машинное обучение, ML, искусственный интеллект",
                "description": "Обсуждение новых алгоритмов и практик в машинном обучении.",
                "url": "https://mlconf.ru",
                "source": "manual"
            }
        ]
        
        initial_courses = [
            {
                "title": "Машинное обучение с нуля на Python",
                "provider": "Coursera",
                "tags": "машинное обучение, python, ai",
                "description": "Вводный курс по машинному обучению с практическими заданиями.",
                "start_date": "2025-06-01",
                "url": "https://coursera.org/ml",
                "duration": "6 weeks",
                "price": 0.0,
                "source": "manual"
            }
        ]
        
        for event in initial_events:
            self.add_event(event)
        
        for course in initial_courses:
            self.add_course(course)
        
        logging.info("Initial data filled successfully")

    def add_event(self, event_data: Dict) -> int:
        """Добавление нового мероприятия"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (title, date, location, tags, description, url, source)
                VALUES (:title, :date, :location, :tags, :description, :url, :source)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    date = excluded.date,
                    location = excluded.location,
                    tags = excluded.tags,
                    description = excluded.description,
                    updated_at = datetime('now')
                RETURNING id
            ''', event_data)
            event_id = cursor.fetchone()[0]
            conn.commit()
            logging.info(f"Event added/updated: {event_data['title']}")
            return event_id

    def add_course(self, course_data: Dict) -> int:
        """Добавление нового курса"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO courses (
                    title, provider, tags, description, start_date, url, duration, price, rating, source
                )
                VALUES (
                    :title, :provider, :tags, :description, :start_date, :url, 
                    :duration, :price, :rating, :source
                )
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    provider = excluded.provider,
                    tags = excluded.tags,
                    description = excluded.description,
                    start_date = excluded.start_date,
                    duration = excluded.duration,
                    price = excluded.price,
                    rating = excluded.rating,
                    updated_at = datetime('now')
                RETURNING id
            ''', course_data)
            course_id = cursor.fetchone()[0]
            conn.commit()
            logging.info(f"Course added/updated: {course_data['title']}")
            return course_id

    def get_recommendations(
        self,
        user_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Получение рекомендаций с учетом предпочтений пользователя
        
        Args:
            user_id: ID пользователя (опционально)
            tags: Список тегов для фильтрации
            limit: Максимальное количество рекомендаций
            
        Returns:
            Список рекомендаций (смесь мероприятий и курсов)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Базовые запросы для мероприятий и курсов
            events_query = '''
                SELECT 
                    id, title, date, location, tags, description, url,
                    'event' as item_type,
                    popularity
                FROM events
                WHERE date >= date('now')
            '''
            
            courses_query = '''
                SELECT 
                    id, title, provider as location, tags, description, url,
                    'course' as item_type,
                    start_date as date,
                    popularity
                FROM courses
                WHERE start_date >= date('now')
            '''
            
            # Добавляем фильтр по тегам если они указаны
            if tags:
                tag_condition = " AND (" + " OR ".join(["tags LIKE ?" for _ in tags]) + ")"
                events_query += tag_condition
                courses_query += tag_condition
            
            # Объединяем запросы и сортируем
            union_query = f'''
                SELECT * FROM (
                    {events_query}
                    UNION ALL
                    {courses_query}
                )
                ORDER BY 
                    CASE WHEN ? IS NOT NULL THEN (
                        SELECT COUNT(*) FROM interactions 
                        WHERE user_id = ? AND item_id = id AND item_type = item_type AND interaction_type = 'like'
                    ) ELSE 0 END DESC,
                    popularity DESC,
                    date ASC
                LIMIT ?
            '''
            
            # Параметры для запроса
            params = [f"%{tag}%" for tag in tags] if tags else []
            params = params * 2 + [user_id, user_id, limit]
            
            cursor.execute(union_query, params)
            results = [dict(row) for row in cursor.fetchall()]
            
            logging.info(f"Found {len(results)} recommendations for user {user_id}")
            return results

    def log_interaction(
        self,
        user_id: int,
        item_id: int,
        item_type: str,
        interaction_type: str
    ) -> bool:
        """
        Логирование взаимодействия пользователя с элементом
        
        Args:
            user_id: ID пользователя
            item_id: ID элемента (мероприятия/курса)
            item_type: Тип элемента ('event' или 'course')
            interaction_type: Тип взаимодействия ('view', 'like', etc.)
            
        Returns:
            True если запись успешно добавлена
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Добавляем запись о взаимодействии
                cursor.execute('''
                    INSERT INTO interactions (user_id, item_id, item_type, interaction_type)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, item_id, item_type, interaction_type))
                
                # Обновляем популярность элемента
                if interaction_type in ('like', 'bookmark'):
                    table = 'events' if item_type == 'event' else 'courses'
                    cursor.execute(f'''
                        UPDATE {table} 
                        SET popularity = popularity + 1 
                        WHERE id = ?
                    ''', (item_id,))
                
                # Обновляем время последней активности пользователя
                cursor.execute('''
                    UPDATE users 
                    SET last_activity = datetime('now') 
                    WHERE user_id = ?
                ''', (user_id,))
                
                conn.commit()
                logging.info(f"Logged {interaction_type} for {item_type} {item_id} by user {user_id}")
                return True
        except Error as e:
            logging.error(f"Failed to log interaction: {str(e)}")
            return False

    def get_user_preferences(self, user_id: int) -> Dict:
        """Получение предпочтений пользователя"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT preferences FROM users WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result and result['preferences']:
                try:
                    return json.loads(result['preferences'])
                except json.JSONDecodeError:
                    logging.warning(f"Invalid preferences JSON for user {user_id}")
                    return {}
            return {}

    def update_user_preferences(self, user_id: int, preferences: Dict) -> bool:
        """Обновление предпочтений пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Проверяем существование пользователя
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id) VALUES (?)
                ''', (user_id,))
                
                # Обновляем предпочтения
                cursor.execute('''
                    UPDATE users 
                    SET preferences = ?, last_activity = datetime('now') 
                    WHERE user_id = ?
                ''', (json.dumps(preferences), user_id))
                
                conn.commit()
                logging.info(f"Updated preferences for user {user_id}")
                return True
        except Error as e:
            logging.error(f"Failed to update preferences: {str(e)}")
            return False

if __name__ == "__main__":
    # Пример использования
    db = DatabaseManager()
    
    # Добавление тестовых данных
    db._fill_initial_data()
