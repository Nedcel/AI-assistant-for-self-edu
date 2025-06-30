import telebot
from telebot.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import TOKEN
from database import DatabaseManager
from recommender import HybridRecommender
import logging
from typing import Dict, Any, Optional
import threading
import time
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

class RecommendationBot:
    def __init__(self, token: str):
        self.bot = telebot.TeleBot(token)
        self.db = DatabaseManager()
        self.recommender = HybridRecommender(self.db)
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.setup_handlers()
        
        # Запуск фоновых задач
        self._start_background_tasks()

    def _start_background_tasks(self):
        """Запуск фоновых задач (обновление БД, обучение моделей)"""
        def update_database():
            while True:
                try:
                    logging.info("Running scheduled database update...")
                    time.sleep(3600)  # Каждый час
                except Exception as e:
                    logging.error(f"Background task error: {str(e)}")
                    time.sleep(60)
        
        threading.Thread(target=update_database, daemon=True).start()

    def setup_handlers(self):
        """Настройка обработчиков сообщений"""
        @self.bot.message_handler(commands=['start', 'help'])
        def handle_start(message):
            self._handle_start(message)

        @self.bot.message_handler(commands=['preferences'])
        def handle_preferences(message):
            self._handle_preferences(message)

        @self.bot.message_handler(commands=['history'])
        def handle_history(message):
            self._handle_history(message)

        @self.bot.message_handler(func=lambda m: True)
        def handle_text(message):
            self._handle_text(message)

        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback(call):
            self._handle_callback(call)

    def _handle_start(self, message):
        """Обработка команды /start"""
        user_id = message.from_user.id
        self._register_user(message.from_user)
        
        welcome_text = (
            "🎉 Добро пожаловать в систему рекомендаций мероприятий и курсов!\n\n"
            "Я могу помочь вам найти:\n"
            "- Конференции и митапы по IT-направлениям\n"
            "- Обучающие курсы и программы\n"
            "- Хакатоны и конкурсы\n\n"
            "🔍 Просто напишите, что вас интересует (например: 'машинное обучение' или 'курсы по фронтенду').\n\n"
            "Также вы можете использовать команды:\n"
            "/preferences - Настроить предпочтения\n"
            "/history - Посмотреть историю запросов"
        )
        
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        popular_tags = ["ML", "Frontend", "DevOps", "Python", "JavaScript", "Data Science"]
        markup.add(*[KeyboardButton(tag) for tag in popular_tags])
        
        self.bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            reply_markup=markup
        )
        
        logging.info(f"New user session started: {user_id}")

    def _register_user(self, user):
        """Регистрация/обновление данных пользователя в БД"""
        user_data = {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }
        self.db.update_user(user_data)

    def _handle_preferences(self, message):
        """Обработка команды настройки предпочтений"""
        user_id = message.from_user.id
        preferences = self.db.get_user_preferences(user_id)
        
        text = (
            "⚙️ <b>Ваши предпочтения</b>\n\n"
            "Текущие предпочтения:\n"
            f"{self._format_preferences(preferences)}\n\n"
            "Выберите действие:"
        )
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("Изменить теги", callback_data="pref_tags"),
            InlineKeyboardButton("Сбросить", callback_data="pref_reset")
        )
        
        self.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=markup,
            parse_mode='HTML'
        )

    def _format_preferences(self, preferences: Dict) -> str:
        """Форматирование предпочтений для отображения"""
        if not preferences:
            return "Не заданы"
        
        tags = preferences.get('preferred_tags', [])
        if tags:
            return "🔹 " + "\n🔹 ".join(tags)
        return "Не заданы"

    def _handle_history(self, message):
        """Обработка команды просмотра истории"""
        user_id = message.from_user.id
        history = self.db.get_user_history(user_id, limit=10)
        
        if not history:
            self.bot.send_message(
                chat_id=message.chat.id,
                text="📜 Ваша история запросов пока пуста."
            )
            return
        
        text = "📜 <b>Ваша история запросов:</b>\n\n" + "\n".join(
            f"{i+1}. {item['query']} ({item['timestamp']})"
            for i, item in enumerate(history)
        )
        
        self.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode='HTML'
        )

    def _handle_text(self, message):
        """Обработка текстовых запросов"""
        user_id = message.from_user.id
        query = message.text.strip()
        
        # Сохраняем запрос в историю
        self.db.log_user_query(user_id, query)
        
        # Получаем рекомендации
        recommendations = self.recommender.recommend(
            query=query,
            user_id=user_id,
            limit=5
        )
        
        if not recommendations:
            self.bot.send_message(
                chat_id=message.chat.id,
                text="❌ По вашему запросу ничего не найдено. Попробуйте изменить формулировку."
            )
            return
        
        # Отправляем рекомендации
        self._send_recommendations(message.chat.id, recommendations)

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("👍 Понравилось", callback_data="feedback_good"),
            InlineKeyboardButton("👎 Не подходит", callback_data="feedback_bad")
        )
        
        self.bot.send_message(
            chat_id=message.chat.id,
            reply_markup=markup
        )

    def _send_recommendations(self, chat_id, recommendations):
        """Отправка рекомендаций пользователю"""
        for rec in recommendations:
            item_type = "🎤 Мероприятие" if rec['type'] == 'event' else "📚 Курс"
            score = f"Рейтинг: {rec['score']:.2f}" if rec['score'] > 0 else ""
            
            text = (
                f"{item_type}\n"
                f"<b>{rec['title']}</b>\n\n"
                f"{rec['description'][:200]}...\n\n"
                f"🏷️ <i>{rec['tags']}</i>\n"
                f"{score}\n\n"
                f"🔗 <a href='{rec['url']}'>Подробнее</a>"
            )
            
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("👍", callback_data=f"like_{rec['type']}_{rec['id']}"),
                InlineKeyboardButton("👎", callback_data=f"dislike_{rec['type']}_{rec['id']}"),
                InlineKeyboardButton("⭐ Сохранить", callback_data=f"bookmark_{rec['type']}_{rec['id']}")
            )
            
            self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=True
            )

    def _handle_callback(self, call):
        """Обработка callback-запросов от кнопок"""
        user_id = call.from_user.id
        data = call.data
        
        try:
            if data.startswith(('like_', 'dislike_', 'bookmark_')):
                # Обработка лайков/дизлайков
                action, item_type, item_id = data.split('_')
                interaction_type = {
                    'like': 'like',
                    'dislike': 'dislike',
                    'bookmark': 'bookmark'
                }[action]
                
                self.db.log_interaction(
                    user_id=user_id,
                    item_id=int(item_id),
                    item_type=item_type,
                    interaction_type=interaction_type
                )
                
                # Обновляем предпочтения пользователя
                self.recommender.train_user_preferences(user_id)
                
                self.bot.answer_callback_query(
                    call.id,
                    text="Спасибо за ваш отзыв! Мы учтем ваши предпочтения.",
                    show_alert=False
                )
                
            elif data == 'feedback_good':
                self.bot.answer_callback_query(
                    call.id,
                    text="Рады, что вам понравилось!",
                    show_alert=False
                )
                
            elif data == 'feedback_bad':
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="Жаль, что не подошло. Попробуйте уточнить ваш запрос."
                )
                
            elif data.startswith('pref_'):
                # Обработка настроек предпочтений
                if data == 'pref_tags':
                    self._edit_tags(call)
                elif data == 'pref_reset':
                    self.db.update_user_preferences(user_id, {})
                    self.bot.answer_callback_query(
                        call.id,
                        text="Ваши предпочтения сброшены",
                        show_alert=False
                    )
                
        except Exception as e:
            logging.error(f"Callback error: {str(e)}")
            self.bot.answer_callback_query(
                call.id,
                text="Произошла ошибка",
                show_alert=True
            )

    def _edit_tags(self, call):
        """Редактирование тегов предпочтений"""
        user_id = call.from_user.id
        all_tags = self.db.get_all_tags()
        
        markup = InlineKeyboardMarkup(row_width=3)
        for tag in all_tags[:15]:  # Ограничиваем количество для отображения
            markup.add(InlineKeyboardButton(
                text=f"{'✅' if tag in self.db.get_user_preferences(user_id).get('preferred_tags', []) else '🔹'} {tag}",
                callback_data=f"tag_toggle_{tag}"
            ))
        
        markup.row(
            InlineKeyboardButton("Готово", callback_data="tags_done"),
            InlineKeyboardButton("Отмена", callback_data="tags_cancel")
        )
        
        self.bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Выберите интересующие вас теги:",
            reply_markup=markup
        )

    def run(self):
        """Запуск бота"""
        logging.info("Starting recommendation bot...")
        self.bot.infinity_polling()

if __name__ == "__main__":
    bot = RecommendationBot(TOKEN)
    bot.run()