import validators
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import time
import re
import threading
import sqlite3
import random
import logging
import os
from typing import Dict, List, Optional

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ====================
TOKEN = os.environ.get('VK_TOKEN')
GROUP_ID = int(os.environ.get('GROUP_ID', 237271112))

if not TOKEN:
    logger.error("❌ VK_TOKEN не найден!")
    exit(1)

# ==================== БАЗА ДАННЫХ ====================
class BotDatabase:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
    
    def _init_db(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        logger.info(f"Database {self.db_name} initialized")
    
    def add_link(self, link: str) -> bool:
        try:
            self.conn.execute("INSERT INTO groups (link) VALUES (?)", (link,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding link: {e}")
            return False
    
    def get_recent_links(self, limit: int = 5):
        try:
            cursor = self.conn.execute("SELECT DISTINCT link FROM groups ORDER BY id DESC LIMIT ?", (limit,))
            return [row['link'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting links: {e}")
            return []
    
    def close(self):
        self.conn.close()

# ==================== КЛАВИАТУРА ====================
def create_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("❤️ ПРАВИЛА ЧАТА ❤️", VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_openlink_button("❤️ ЛАЙК-ЧАТ ❤️", "https://vk.me/join/ссылку_на_лайк_чат")
    keyboard.add_openlink_button("💬 КОММЕНТАРИИ", "https://vk.me/join/ссылку_на_чат_комментариев")
    keyboard.add_line()
    keyboard.add_button("🚀 ТУРБО-VIP 🚀", VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("✨ УСЛУГА VIP ✨", VkKeyboardColor.NEGATIVE)
    return keyboard

# ==================== ОСНОВНОЙ БОТ ====================
class SubscribeBot:
    def __init__(self):
        self.db = BotDatabase('subscriptions.db')
        self.user_limits: Dict[int, int] = {}
        self.user_links: Dict[int, List[str]] = {}
        self.keyboard = create_keyboard()
    
    def is_subscribed(self, link: str, user_id: int) -> bool:
        try:
            if 'club' in link:
                group_id = link.split('club')[1].split('?')[0]
            else:
                group_id = link.split('vk.com/')[1].split('?')[0]
            result = vk.groups.isMember(group_id=group_id, user_id=user_id)
            return result
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
            return True
    
    def check_group(self, link: str) -> bool:
        try:
            group_id = link.split('vk.com/')[1].split('?')[0]
            vk.groups.getById(group_id=group_id)
            return True
        except:
            return False
    
    def send_message(self, peer_id: int, text: str):
        try:
            vk.messages.send(
                peer_id=peer_id,
                message=text,
                random_id=0,
                keyboard=self.keyboard.get_keyboard()
            )
            logger.info(f"Message sent to {peer_id}")
        except Exception as e:
            logger.error(f"Error sending: {e}")
    
    def delete_message(self, peer_id: int, msg_id: int):
        try:
            vk.messages.delete(
                conversation_message_ids=msg_id,
                peer_id=peer_id,
                delete_for_all=1
            )
            logger.info(f"Message {msg_id} deleted")
        except Exception as e:
            logger.error(f"Error deleting: {e}")
    
    def handle_message(self, peer_id: int, user_id: int, text: str, msg_id: int, user_name: str):
        logger.info(f"Handling message from {user_name}: {text[:50]}")
        
        # Команда "ПРАВИЛА ЧАТА"
        if 'ПРАВИЛА ЧАТА' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "🚀 ВЗАИМНЫЕ ПОДПИСКИ 5|5 🚀\n\n"
                "✅ Разрешается публиковать только ссылку на ГРУППУ\n"
                "✅ Подписывайтесь на 5 групп выше вашей ссылки\n"
                "✅ После подписки отправьте ссылку ПОВТОРНО\n"
                "❗ Запрещается отписываться от групп")
            return
        
        # VIP команды
        if 'УСЛУГА VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, "✨ VIP УСЛУГА ✨\n\nПо всем вопросам: https://vk.com/dianamaysky")
            return
        
        if 'ТУРБО-VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, "🚀 ТУРБО-VIP 🚀\n\nПо всем вопросам: https://vk.com/dianamaysky")
            return
        
        # Проверка на ссылку группы
        is_link = ('vk.com' in text and 'wall' not in text and self.check_group(text))
        
        if not is_link:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, f"⚠ {user_name}, разрешается публиковать только ссылку на ГРУППУ!")
            return
        
        # Проверка лимита (5 через 5)
        if user_id in self.user_limits and self.user_limits[user_id] > 0:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, f"⚠ {user_name}, ещё НЕ прошло 5 чужих ссылок. Дождитесь.")
            return
        
        # Получаем последние 5 ссылок
        last_links = self.db.get_recent_links(5)
        
        # Фильтруем те, на которые пользователь ещё не подписался
        pending = []
        for link in last_links:
            if not self.is_subscribed(link, user_id):
                pending.append(link)
        
        if pending:
            self.user_links[user_id] = pending
            self.delete_message(peer_id, msg_id)
            links_text = '\n'.join([f"{i+1}. {l}" for i, l in enumerate(pending)])
            self.send_message(peer_id,
                f"{user_name},\nпожалуйста, подпишитесь на эти группы:\n\n{links_text}\n\n"
                f"⌛ На выполнение: 6 минут\nПосле подписки отправьте ссылку ПОВТОРНО")
        else:
            # Все подписки выполнены — добавляем новую ссылку
            self.db.add_link(text)
            self.user_limits[user_id] = 5
            
            # Уменьшаем лимиты у других
            for uid in list(self.user_limits.keys()):
                if self.user_limits[uid] > 1:
                    self.user_limits[uid] -= 1
            
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                f"{user_name}, ваша ссылка успешно добавлена\n"
                f"🚀 По вопросам VIP: https://vk.com/dianamaysky")

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    try:
        logger.info("🚀 Запуск бота подписок...")
        
        vk_session = vk_api.VkApi(token=TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        bot = SubscribeBot()
        logger.info(f"✅ Бот запущен. Слушаем беседы...")
        
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                
                # Обрабатываем только нужные беседы
                if peer_id not in [2000000003, 2000000206]:
                    continue
                
                user_id = msg['from_id']
                text = msg.get('text', '')
                msg_id = msg['conversation_message_id']
                
                # Получаем имя пользователя
                try:
                    user = vk.users.get(user_ids=user_id)[0]
                    user_name = f"{user['first_name']} {user['last_name']}"
                except:
                    user_name = str(user_id)
                
                logger.info(f"📩 {peer_id} | {user_name}: {text[:50]}")
                
                # Обработка в отдельном потоке
                threading.Thread(
                    target=bot.handle_message,
                    args=(peer_id, user_id, text, msg_id, user_name),
                    daemon=True
                ).start()
                
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
