import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import time
import threading
import sqlite3
import logging
import os
from typing import Dict, List

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
    def __init__(self):
        self.conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT NOT NULL,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        logger.info("Database initialized")
    
    def add_link(self, link: str, user_id: int) -> bool:
        try:
            self.conn.execute("INSERT INTO groups (link, user_id) VALUES (?, ?)", (link, user_id))
            self.conn.commit()
            logger.info(f"Link added: {link} by user {user_id}")
            return True
        except Exception as e:
            logger.error(f"DB error: {e}")
            return False
    
    def get_all_links(self, limit: int = 20):
        try:
            cursor = self.conn.execute("SELECT link, user_id FROM groups ORDER BY id DESC LIMIT ?", (limit,))
            return [{'link': row[0], 'user_id': row[1]} for row in cursor.fetchall()]
        except:
            return []

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
        self.db = BotDatabase()
        self.user_states: Dict[int, str] = {}
        self.pending_links: Dict[int, List[str]] = {}
        self.keyboard = create_keyboard()
    
    def is_subscribed(self, link: str, user_id: int) -> bool:
        """Проверка подписки через API"""
        try:
            if 'club' in link:
                group_id = link.split('club')[1].split('?')[0]
            elif 'public' in link:
                group_id = link.split('public')[1].split('?')[0]
            else:
                group_id = link.split('vk.com/')[1].split('/')[0].split('?')[0]
            result = vk.groups.isMember(group_id=group_id, user_id=user_id)
            return result
        except Exception as e:
            logger.error(f"Subscription check error: {e}")
            return True
    
    def is_group_link(self, text: str) -> bool:
        """Проверяет, что сообщение похоже на ссылку на группу VK"""
        return ('vk.com' in text and 
                'wall' not in text and 
                'photo' not in text and 
                'video' not in text and
                'album' not in text)
    
    def send_message(self, peer_id: int, text: str, delete_after: int = 15):
        """Отправка сообщения с автоматическим удалением"""
        try:
            response = vk.messages.send(
                peer_id=peer_id,
                message=text,
                random_id=0,
                keyboard=self.keyboard.get_keyboard()
            )
            logger.info(f"Message sent, msg_id: {response}")
            
            if delete_after > 0:
                def delete_later():
                    time.sleep(delete_after)
                    try:
                        vk.messages.delete(
                            conversation_message_ids=response,
                            peer_id=peer_id,
                            delete_for_all=1
                        )
                        logger.info(f"Auto-deleted message {response}")
                    except Exception as e:
                        logger.error(f"Auto-delete error: {e}")
                
                threading.Thread(target=delete_later, daemon=True).start()
                
        except Exception as e:
            logger.error(f"Send error: {e}")
    
    def delete_message(self, peer_id: int, msg_id: int):
        """Немедленное удаление сообщения"""
        try:
            vk.messages.delete(
                conversation_message_ids=msg_id,
                peer_id=peer_id,
                delete_for_all=1
            )
            logger.info(f"Message {msg_id} deleted")
        except Exception as e:
            logger.error(f"Delete error: {e}")
    
    def get_pending_links(self, user_id: int, limit: int = 10) -> List[str]:
        """Возвращает ссылки, на которые пользователь ещё не подписался"""
        all_links = self.db.get_all_links(limit)
        pending = []
        for item in all_links:
            if item['user_id'] == user_id:
                continue
            if not self.is_subscribed(item['link'], user_id):
                pending.append(item['link'])
        return pending
    
    def handle_message(self, peer_id: int, user_id: int, text: str, msg_id: int, user_name: str):
        logger.info(f"Handling: {user_name} -> {text[:50]}")
        
        # ========== КОМАНДЫ (удаляются через 15 сек) ==========
        if 'ПРАВИЛА ЧАТА' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "🚀 ВЗАИМНЫЕ ПОДПИСКИ 5|5 🚀\n\n"
                "✅ Разрешается публиковать только ссылку на ГРУППУ\n"
                "✅ Подписывайтесь на ВСЕ группы из списка\n"
                "✅ После подписки отправьте ссылку ПОВТОРНО\n"
                "❗ Запрещается отписываться от групп",
                delete_after=15)
            return
        
        if 'УСЛУГА VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "✨ УСЛУГА VIP ✨\n\n"
                "🎯 Ссылка закрепляется в чате\n"
                "🎯 Взамен никого проходить не надо\n\n"
                "По вопросам: https://vk.com/1morion11",
                delete_after=15)
            return
        
        if 'ТУРБО-VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "🚀 ТУРБО-VIP 🚀\n\n"
                "🎯 200+ лайков в день\n"
                "🎯 Ссылка закрепляется в чате\n\n"
                "По вопросам: https://vk.com/1morion11",
                delete_after=15)
            return
        
        # ========== ПРОВЕРКА ССЫЛКИ ==========
        if not self.is_group_link(text):
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, f"⚠ {user_name}, разрешены только ссылки на ГРУППЫ VK", delete_after=15)
            return
        
        # Получаем неподписанные ссылки
        pending = self.get_pending_links(user_id, limit=10)
        
        if pending:
            # Есть неподписанные ссылки
            self.user_states[user_id] = 'waiting'
            self.pending_links[user_id] = pending
            
            # Удаляем сообщение пользователя со ссылкой
            self.delete_message(peer_id, msg_id)
            
            links_text = '\n'.join([f"{i+1}. {l}" for i, l in enumerate(pending[:5])])
            self.send_message(peer_id,
                f"{user_name},\n👉 Подпишитесь на эти группы:\n\n{links_text}\n\n"
                f"✅ После подписки отправьте ссылку ПОВТОРНО",
                delete_after=15)
        else:
            # ✅ ВСЕ ПОДПИСКИ ВЫПОЛНЕНЫ
            # НЕ УДАЛЯЕМ ссылку пользователя — она остаётся в чате навсегда!
            if self.db.add_link(text, user_id):
                # Отправляем подтверждение (удалится через 15 сек)
                self.send_message(peer_id,
                    f"{user_name}, ✅ ваша ссылка успешно добавлена!\n\n"
                    f"📢 Теперь другие участники увидят её в списке",
                    delete_after=15)
            else:
                self.delete_message(peer_id, msg_id)
                self.send_message(peer_id, "❌ Ошибка при добавлении", delete_after=15)
            
            self.user_states.pop(user_id, None)
            self.pending_links.pop(user_id, None)

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    try:
        logger.info("🚀 Запуск бота подписок...")
        
        vk_session = vk_api.VkApi(token=TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        bot = SubscribeBot()
        logger.info(f"✅ Бот запущен. GROUP_ID: {GROUP_ID}")
        
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                
                # Только нужные беседы
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
