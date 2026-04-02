import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import time
import re
import logging
import sqlite3
import threading
from typing import Dict, List, Optional

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ====================
TOKEN = os.environ.get('VK_TOKEN')
if not TOKEN:
    logger.error("❌ VK_TOKEN не найден!")
    raise ValueError("VK_TOKEN не задан")

GROUP_ID = int(os.environ.get('GROUP_ID', 237271112))
PEER_ID = int(os.environ.get('PEER_ID', 2000000204))  # ваша беседа

logger.info(f"🚀 Запуск бота подписок")
logger.info(f"   GROUP_ID: {GROUP_ID}")
logger.info(f"   PEER_ID (целевая беседа): {PEER_ID}")

# ==================== БАЗА ДАННЫХ ДЛЯ ССЫЛОК ====================
class Database:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self._local = threading.local()
        self._init_db()
    
    def _get_conn(self):
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    def _init_db(self):
        conn = self._get_conn()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT NOT NULL,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info(f"База данных {self.db_name} инициализирована")
    
    def add_link(self, link: str, user_id: int) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("INSERT INTO links (link, user_id) VALUES (?, ?)", (link, user_id))
            conn.commit()
            logger.info(f"Ссылка добавлена: {link} от user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления ссылки: {e}")
            return False
    
    def get_last_links(self, limit: int = 5) -> List[str]:
        try:
            conn = self._get_conn()
            cursor = conn.execute("SELECT DISTINCT link FROM links ORDER BY id DESC LIMIT ?", (limit,))
            return [row['link'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Ошибка получения ссылок: {e}")
            return []
    
    def close(self):
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            logger.info(f"База {self.db_name} закрыта")

# ==================== КЛАСС БОТА ====================
class SubscribeBot:
    def __init__(self):
        self.db = Database('subscriptions.db')
        self.user_limits: Dict[int, int] = {}  # сколько ссылок нужно пропустить
        self.user_states: Dict[int, str] = {}  # состояние пользователя
        self.keyboard = self._create_keyboard()
    
    def _create_keyboard(self) -> VkKeyboard:
        """Создание клавиатуры с кнопками"""
        keyboard = VkKeyboard(one_time=False)
        
        # Первая строка — правила чата
        keyboard.add_button("❤️ ПРАВИЛА ЧАТА ❤️", VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        
        # Вторая строка — переход в другие чаты
        keyboard.add_openlink_button("❤️ ЛАЙК-ЧАТ ❤️", "https://vk.me/join/ссылку_на_лайк_чат")
        keyboard.add_openlink_button("💬 КОММЕНТАРИИ", "https://vk.me/join/ссылку_на_чат_комментариев")
        keyboard.add_line()
        
        # Третья строка — турбо-VIP
        keyboard.add_button("🚀 ТУРБО-VIP 🚀", VkKeyboardColor.POSITIVE)
        keyboard.add_line()
        
        # Четвертая строка — услуга VIP
        keyboard.add_button("✨ УСЛУГА VIP ✨", VkKeyboardColor.NEGATIVE)
        
        return keyboard
    
    def is_subscribed(self, link: str, user_id: int) -> bool:
        """Проверка подписки на группу"""
        try:
            # Извлекаем ID группы из ссылки
            if 'club' in link:
                group_id = link.split('club')[1].split('?')[0]
            else:
                group_id = link.split('vk.com/')[1].split('?')[0]
            
            # Проверяем подписку через API
            result = vk.groups.isMember(group_id=group_id, user_id=user_id)
            return result
        except Exception as e:
            logger.error(f"Ошибка проверки подписки: {e}")
            return True  # если ошибка, считаем что подписан
    
    def check_group_exists(self, link: str) -> bool:
        """Проверка существования группы"""
        try:
            group_id = link.split('vk.com/')[1].split('?')[0]
            vk.groups.getById(group_id=group_id)
            return True
        except:
            return False
    
    def send_message(self, peer_id: int, message: str, **kwargs):
        """Отправка сообщения с клавиатурой"""
        try:
            params = {
                'peer_id': peer_id,
                'message': message,
                'random_id': 0,
                'keyboard': self.keyboard.get_keyboard()
            }
            params.update(kwargs)
            vk.messages.send(**params)
            logger.info(f"Сообщение отправлено в {peer_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
    
    def delete_message(self, peer_id: int, message_id: int):
        """Удаление сообщения"""
        try:
            vk.messages.delete(
                conversation_message_ids=message_id,
                peer_id=peer_id,
                delete_for_all=1
            )
            logger.info(f"Сообщение {message_id} удалено")
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
    
    def process_link(self, user_id: int, link: str, message_id: int, name: str) -> Optional[str]:
        """Обработка ссылки на группу"""
        # Проверка на приватную группу
        if not self.check_group_exists(link):
            self.delete_message(PEER_ID, message_id)
            return f"⚠ {name}, запрещено публиковать ссылку на приватную группу!"
        
        # Проверка лимита (5 через 5)
        if user_id in self.user_limits and self.user_limits[user_id] > 0:
            self.delete_message(PEER_ID, message_id)
            return f"⚠ {name}, ещё НЕ прошло 5 чужих ссылок. Дождитесь."
        
        # Получаем последние 5 ссылок
        last_links = self.db.get_last_links(5)
        
        # Фильтруем ссылки, на которые пользователь уже подписан
        pending_links = []
        for link_item in last_links:
            if not self.is_subscribed(link_item, user_id):
                pending_links.append(link_item)
        
        if pending_links:
            # Сохраняем состояние пользователя
            self.user_states[user_id] = 'waiting_for_subscribe'
            self.user_states[user_id + '_links'] = pending_links
            
            self.delete_message(PEER_ID, message_id)
            links_text = '\n'.join([f"{i+1}. {l}" for i, l in enumerate(pending_links)])
            return (f"{name},\n"
                    f"пожалуйста, подпишитесь на эти группы:\n\n"
                    f"{links_text}\n\n"
                    f"⌛ На выполнение: 6 минут\n"
                    f"После подписки отправьте ссылку ПОВТОРНО")
        else:
            # Все ссылки уже выполнены — добавляем новую
            self.db.add_link(link, user_id)
            self.user_limits[user_id] = 5  # следующий раз через 5 ссылок
            self.user_states.pop(user_id, None)
            self.user_states.pop(user_id + '_links', None)
            
            # Уменьшаем лимиты у других пользователей
            new_limits = {}
            for uid, limit in self.user_limits.items():
                if limit > 1:
                    new_limits[uid] = limit - 1
            self.user_limits = new_limits
            
            self.delete_message(PEER_ID, message_id)
            return (f"{name}, ваша ссылка успешно добавлена\n"
                    f"🚀 У нас можно заказать:\n"
                    f" ✨ Услугу VIP\n"
                    f" ✨ Бот под ключ\n"
                    f" ✨ Оформление сообщества\n\n"
                    f"По всем вопросам обращайтесь к админу\n👇\n"
                    f"https://vk.com/dianamaysky")
    
    def check_completion(self, user_id: int, name: str) -> Optional[str]:
        """Проверка выполнения подписок после повторной отправки"""
        if user_id not in self.user_states:
            return None
        
        state = self.user_states.get(user_id)
        if state != 'waiting_for_subscribe':
            return None
        
        pending_links = self.user_states.get(user_id + '_links', [])
        
        # Проверяем, на какие ссылки пользователь подписался
        still_pending = []
        for link in pending_links:
            if not self.is_subscribed(link, user_id):
                still_pending.append(link)
        
        if still_pending:
            # Не все подписки выполнены
            links_text = '\n'.join([f"{i+1}. {l}" for i, l in enumerate(still_pending)])
            return (f"{name},\n"
                    f"вы пропустили эти группы:\n\n"
                    f"{links_text}\n\n"
                    f"Пожалуйста, подпишитесь на них и отправьте ссылку ПОВТОРНО")
        else:
            # Все подписки выполнены — добавляем ссылку
            return None  # вернёмся к обработке ссылки
    
    def handle_message(self, message_text: str, user_id: int, message_id: int, name: str):
        """Главный обработчик сообщений"""
        # Команда "ПРАВИЛА ЧАТА"
        if 'ПРАВИЛА ЧАТА' in message_text:
            self.delete_message(PEER_ID, message_id)
            self.send_message(PEER_ID,
                "Вы в чате 🚀 ВЗАИМНЫЕ ПОДПИСКИ 5|5 🚀\n\n"
                "Здесь мы вступаем друг другу в группы.\n\n"
                "Участие в ленте чата БЕСПЛАТНОЕ\n\n"
                "Работаем 5 через 5 + отработка VIP.\n\n"
                "👇🏻👇🏻👇\n\n"
                "❗️ ПРАВИЛА ❗️\n\n"
                "✅ Разрешается публиковать только ссылку на ГРУППУ\n"
                "✅ Подписывайтесь на 5 групп выше вашей ссылки\n"
                "✅ После подписки отправьте ссылку ПОВТОРНО\n"
                "❗ Запрещается отписываться от групп\n"
                "❗ Запрещается публиковать ссылки на приватные группы")
            return
        
        # Команда "УСЛУГА VIP"
        if 'УСЛУГА VIP' in message_text:
            self.delete_message(PEER_ID, message_id)
            self.send_message(PEER_ID,
                "✨ УСЛУГА VIP ✨\n\n"
                "🎯 Ссылка закрепляется в чате\n"
                "🎯 Взамен никого проходить не надо\n"
                "🎯 Ссылку можно менять\n"
                "🎯 Неделя - 400 рублей\n\n"
                "По всем вопросам обращайтесь к админу\n👇\n"
                "https://vk.com/dianamaysky")
            return
        
        # Команда "ТУРБО-VIP"
        if 'ТУРБО-VIP' in message_text:
            self.delete_message(PEER_ID, message_id)
            self.send_message(PEER_ID,
                "🚀 ТУРБО-VIP 🚀\n\n"
                "🎯 Ссылка закрепляется в чате\n"
                "🎯 Взамен никого проходить не надо\n"
                "🎯 Ссылку можно менять\n"
                "🎯 День - 400 рублей\n\n"
                "По всем вопросам обращайтесь к админу\n👇\n"
                "https://vk.com/dianamaysky")
            return
        
        # Проверяем, является ли сообщение ссылкой на группу
        is_group_link = ('vk.com' in message_text and 
                         'wall' not in message_text and 
                         'photo' not in message_text and
                         self.check_group_exists(message_text))
        
        if is_group_link:
            # Проверяем, не ожидает ли пользователь проверки подписок
            completion_result = self.check_completion(user_id, name)
            if completion_result:
                self.delete_message(PEER_ID, message_id)
                self.send_message(PEER_ID, completion_result)
                return
            
            # Обрабатываем новую ссылку
            response = self.process_link(user_id, message_text, message_id, name)
            if response:
                self.send_message(PEER_ID, response)
        else:
            # Невалидное сообщение
            self.delete_message(PEER_ID, message_id)
            self.send_message(PEER_ID, f"⚠ {name}, разрешается публиковать только ссылку на ГРУППУ!")

# ==================== ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ====================
if __name__ == '__main__':
    try:
        logger.info("🚀 Запуск бота подписок...")
        
        # Подключение к VK API
        vk_session = vk_api.VkApi(token=TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        # Создание бота
        bot = SubscribeBot()
        
        logger.info(f"✅ Бот успешно запущен")
        logger.info(f"📡 Слушаем беседу: {PEER_ID}")
        
        # Основной цикл
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                
                # Обрабатываем только нашу беседу
                if peer_id != PEER_ID:
                    continue
                
                user_id = msg['from_id']
                text = msg.get('text', '')
                message_id = msg['conversation_message_id']
                
                # Получаем имя пользователя
                try:
                    user_info = vk.users.get(user_ids=user_id)[0]
                    name = f"{user_info['first_name']} {user_info['last_name']}"
                except:
                    name = f"Пользователь {user_id}"
                
                logger.info(f"📩 Сообщение от {name} (ID: {user_id}): {text[:50]}")
                
                # Обрабатываем сообщение
                try:
                    bot.handle_message(text, user_id, message_id, name)
                except Exception as e:
                    logger.error(f"Ошибка обработки: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
