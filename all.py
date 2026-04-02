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
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        logger.info(f"Database {self.db_name} initialized")
    
    def add_link(self, link: str, user_id: int) -> bool:
        try:
            self.conn.execute("INSERT INTO groups (link, user_id) VALUES (?, ?)", (link, user_id))
            self.conn.commit()
            logger.info(f"Link added: {link} by user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding link: {e}")
            return False
    
    def get_all_links(self, limit: int = 20):
        try:
            cursor = self.conn.execute(
                "SELECT DISTINCT link, user_id FROM groups ORDER BY id DESC LIMIT ?", 
                (limit,)
            )
            return [{'link': row['link'], 'user_id': row['user_id']} for row in cursor.fetchall()]
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
        self.user_states: Dict[int, str] = {}
        self.pending_links: Dict[int, List[str]] = {}
        self.keyboard = create_keyboard()
    
    def is_subscribed(self, link: str, user_id: int) -> bool:
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
            logger.error(f"Error checking subscription: {e}")
            return True
    
    def check_group_exists(self, link: str) -> bool:
        """Проверяет только формат ссылки (не проверяет существование)"""
        # Проверяем, что это ссылка на группу VK (не на пост, фото, видео)
        if ('vk.com' not in link or 
            'wall' in link or 
            'photo' in link or 
            'video' in link or 
            'album' in link):
            return False
        
        # Извлекаем идентификатор
        try:
            if 'club' in link:
                group_id = link.split('club')[1].split('?')[0]
            elif 'public' in link:
                group_id = link.split('public')[1].split('?')[0]
            else:
                parts = link.split('vk.com/')[1].split('/')[0].split('?')[0]
                group_id = parts
            
            # Если есть ID, считаем ссылку валидной
            return group_id is not None and len(group_id) > 0
        except:
            return True  # Если не удалось разобрать, но похоже на ссылку VK — пропускаем
    
    def send_message(self, peer_id: int, text: str, delete_after: int = 15):
        try:
            response = vk.messages.send(
                peer_id=peer_id,
                message=text,
                random_id=0,
                keyboard=self.keyboard.get_keyboard()
            )
            logger.info(f"Message sent to {peer_id}, msg_id: {response}")
            
            if delete_after > 0:
                def delete_later():
                    time.sleep(delete_after)
                    try:
                        vk.messages.delete(
                            conversation_message_ids=response,
                            peer_id=peer_id,
                            delete_for_all=1
                        )
                        logger.info(f"Auto-deleted message {response} after {delete_after}s")
                    except Exception as e:
                        logger.error(f"Auto-delete error: {e}")
                
                threading.Thread(target=delete_later, daemon=True).start()
                
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
    
    def get_all_pending_links(self, user_id: int, limit: int = 15) -> List[str]:
        all_links = self.db.get_all_links(limit)
        pending = []
        for item in all_links:
            if item['user_id'] == user_id:
                continue
            if not self.is_subscribed(item['link'], user_id):
                pending.append(item['link'])
        return pending
    
    def handle_message(self, peer_id: int, user_id: int, text: str, msg_id: int, user_name: str):
        logger.info(f"Handling from {user_name}: {text[:50]}")
        
        # ========== КОМАНДЫ ==========
        if 'ПРАВИЛА ЧАТА' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "🚀 ВЗАИМНЫЕ ПОДПИСКИ 5|5 🚀\n\n"
                "✅ Разрешается публиковать только ссылку на ГРУППУ\n"
                "✅ Подписывайтесь на ВСЕ группы из списка\n"
                "✅ После подписки отправьте ссылку ПОВТОРНО\n"
                "✅ Можно публиковать ссылку в любое время\n"
                "❗ Запрещается отписываться от групп\n"
                "❗ Запрещены приватные группы",
                delete_after=15)
            return
        
        if 'УСЛУГА VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, 
                "✨ УСЛУГА VIP ✨\n\n"
                "🎯 Ссылка закрепляется в чате\n"
                "🎯 Взамен никого проходить не надо\n"
                "🎯 Ссылку можно менять\n\n"
                "По всем вопросам: https://vk.com/1morion11",
                delete_after=15)
            return
        
        if 'ТУРБО-VIP' in text:
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id,
                "🚀 ТУРБО-VIP 🚀\n\n"
                "🎯 200+ лайков в день\n"
                "🎯 Ссылка закрепляется в чате\n"
                "🎯 Взамен никого проходить не надо\n\n"
                "По всем вопросам: https://vk.com/1morion11",
                delete_after=15)
            return
        
        # ========== ПРОВЕРКА ССЫЛКИ ==========
        # Проверяем формат ссылки
        if not self.check_group_exists(text):
            self.delete_message(peer_id, msg_id)
            self.send_message(peer_id, f"⚠ {user_name}, разрешается публиковать только ссылку на ГРУППУ!\n\n"
                               f"Пример: https://vk.com/club123456789", 
                               delete_after=15)
            return
        
        # Проверяем, есть ли у пользователя неподписанные ссылки
        pending = self.get_all_pending_links(user_id, limit=15)
        
        if pending:
            self.user_states[user_id] = 'waiting'
            self.pending_links[user_id] = pending
            
            self.delete_message(peer_id, msg_id)
            
            links_text = '\n'.join([f"{i+1}. {l}" for i, l in enumerate(pending)])
            self.send_message(peer_id,
                f"{user_name},\nпожалуйста, подпишитесь на эти группы:\n\n{links_text}\n\n"
                f"⌛ На выполнение: 6 минут\n"
                f"✅ После подписки отправьте ссылку ПОВТОРНО\n\n"
                f"🎯 Ваша ссылка будет добавлена после выполнения всех подписок",
                delete_after=15)
        else:
            if self.db.add_link(text, user_id):
                self.send_message(peer_id,
                    f"{user_name}, ✅ ваша ссылка успешно добавлена!\n\n"
                    f"📢 Теперь другие участники увидят её в списке для подписки\n\n"
                    f"🚀 По вопросам VIP: https://vk.com/1morion11",
                    delete_after=15)
            else:
                self.delete_message(peer_id, msg_id)
                self.send_message(peer_id, "❌ Ошибка при добавлении ссылки", delete_after=15)
            
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
        logger.info(f"✅ Бот запущен. Слушаем беседы...")
        
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                
                if peer_id not in [2000000003, 2000000206]:
                    continue
                
                user_id = msg['from_id']
                text = msg.get('text', '')
                msg_id = msg['conversation_message_id']
                
                try:
                    user = vk.users.get(user_ids=user_id)[0]
                    user_name = f"{user['first_name']} {user['last_name']}"
                except:
                    user_name = str(user_id)
                
                logger.info(f"📩 {peer_id} | {user_name}: {text[:50]}")
                
                threading.Thread(
                    target=bot.handle_message,
                    args=(peer_id, user_id, text, msg_id, user_name),
                    daemon=True
                ).start()
                
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
