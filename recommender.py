import sqlite3
import numpy as np
from typing import List, Dict, Tuple
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import logging
import torch
from transformers import AutoTokenizer, AutoModel
from database import DatabaseManager  # Используем наш улучшенный модуль БД

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('recommender.log'),
        logging.StreamHandler()
    ]
)

class HybridRecommender:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # Загрузка предобученных моделей
        try:
            # Модель для эмбеддингов (легкая версия для демонстрации)
            self.embedding_model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 
                                                     device=self.device)
            
            # Токенизатор и модель для релевантности (можно заменить на ruBERT)
            self.tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny")
            self.lm_model = AutoModel.from_pretrained("cointegrated/rubert-tiny").to(self.device)
            
            logging.info("Models loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load models: {str(e)}")
            raise

    def get_text_embedding(self, text: str) -> np.ndarray:
        """Получение векторного представления текста"""
        if not text:
            return np.zeros(384)  # Размерность для multilingual-MiniLM-L12-v2
            
        embedding = self.embedding_model.encode(text, convert_to_tensor=False)
        return embedding

    def semantic_similarity(self, query: str, texts: List[str]) -> np.ndarray:
        """Вычисление семантической близости между запросом и текстами"""
        query_embedding = self.get_text_embedding(query)
        text_embeddings = [self.get_text_embedding(text) for text in texts]
        similarities = cosine_similarity([query_embedding], text_embeddings)[0]
        return similarities

    def keyword_relevance(self, query: str, texts: List[str]) -> np.ndarray:
        """Вычисление релевантности по ключевым словам с использованием языковой модели"""
        try:
            inputs = self.tokenizer([query]*len(texts), texts, 
                                 padding=True, truncation=True, 
                                 return_tensors='pt', max_length=512).to(self.device)
            
            with torch.no_grad():
                outputs = self.lm_model(**inputs)
                scores = torch.sigmoid(outputs.logits).cpu().numpy()
            
            return scores[:, 0]
        except Exception as e:
            logging.error(f"Keyword relevance error: {str(e)}")
            return np.zeros(len(texts))

    def recommend(
        self, 
        query: str, 
        user_id: Optional[int] = None,
        limit: int = 5,
        hybrid_weight: float = 0.7
    ) -> List[Dict]:
        """
        Гибридная рекомендательная система (семантический поиск + ключевые слова + пользовательские предпочтения)
        
        Args:
            query: Поисковый запрос
            user_id: ID пользователя (опционально)
            limit: Количество рекомендаций
            hybrid_weight: Вес семантической составляющей (0-1)
            
        Returns:
            Список рекомендаций с метаданными
        """
        try:
            # Получаем все возможные элементы из БД
            items = self.db.get_all_items()
            
            if not items:
                logging.warning("No items found in database")
                return []
            
            # Подготовка текстов для анализа
            texts = [
                f"{item['title']}. {item['tags']}. {item['description']}" 
                for item in items
            ]
            
            # Семантическая схожесть
            semantic_scores = self.semantic_similarity(query, texts)
            
            # Релевантность по ключевым словам
            keyword_scores = self.keyword_relevance(query, texts)
            
            # Гибридная оценка
            hybrid_scores = (hybrid_weight * semantic_scores + 
                           (1 - hybrid_weight) * keyword_scores)
            
            # Учет пользовательских предпочтений
            if user_id:
                user_prefs = self.db.get_user_preferences(user_id)
                if user_prefs.get('preferred_tags'):
                    preferred_tags = set(user_prefs['preferred_tags'])
                    for i, item in enumerate(items):
                        item_tags = set(tag.strip() for tag in item['tags'].split(','))
                        common_tags = preferred_tags & item_tags
                        if common_tags:
                            hybrid_scores[i] *= 1 + 0.2 * len(common_tags)  # Увеличиваем вес на 20% за каждый совпадающий тег
            
            # Сортировка по убыванию релевантности
            sorted_indices = np.argsort(hybrid_scores)[::-1]
            
            # Формирование результатов
            recommendations = []
            for idx in sorted_indices[:limit]:
                item = items[idx]
                recommendations.append({
                    'type': item['item_type'],
                    'id': item['id'],
                    'title': item['title'],
                    'score': float(hybrid_scores[idx]),
                    'url': item['url'],
                    'tags': item['tags'],
                    'description': item['description'],
                    'semantic_score': float(semantic_scores[idx]),
                    'keyword_score': float(keyword_scores[idx])
                })
                
                # Логируем взаимодействие
                if user_id:
                    self.db.log_interaction(
                        user_id=user_id,
                        item_id=item['id'],
                        item_type=item['item_type'],
                        interaction_type='recommendation'
                    )
            
            logging.info(f"Generated {len(recommendations)} recommendations for query: '{query}'")
            return recommendations
            
        except Exception as e:
            logging.error(f"Recommendation error: {str(e)}")
            return []

    def train_user_preferences(self, user_id: int):
        """
        Дообучение модели на основе пользовательских предпочтений
        (Упрощенная реализация - в реальной системе нужно больше данных)
        """
        try:
            interactions = self.db.get_user_interactions(user_id)
            if not interactions:
                return False
                
            # Собираем положительные взаимодействия (лайки, закладки)
            positive_items = [
                (item['item_id'], item['item_type']) 
                for item in interactions 
                if item['interaction_type'] in ('like', 'bookmark')
            ]
            
            if not positive_items:
                return False
            
            # Анализ тегов положительных элементов
            preferred_tags = set()
            for item_id, item_type in positive_items:
                item = self.db.get_item(item_id, item_type)
                if item and item['tags']:
                    tags = set(tag.strip() for tag in item['tags'].split(','))
                    preferred_tags.update(tags)
            
            # Сохраняем предпочтения
            self.db.update_user_preferences(
                user_id=user_id,
                preferences={'preferred_tags': list(preferred_tags)}
            )
            
            logging.info(f"Trained preferences for user {user_id} with {len(preferred_tags)} tags")
            return True
            
        except Exception as e:
            logging.error(f"Training error for user {user_id}: {str(e)}")
            return False

if __name__ == "__main__":
    # Пример использования
    db = DatabaseManager()
    recommender = HybridRecommender(db)
