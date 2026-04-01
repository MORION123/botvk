import validators
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.exceptions import VkApiError
import time
import re
import threading
from itertools import islice
from enum import Enum
from typing import Dict, Any, List, Optional
import sqlite3
import random
import logging
import os

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

# ==================== КЛАСС БАЗЫ ДАННЫХ ====================

class BotDatabase:
    def __init__(self, db_name: str, table_name: str, timeout: float = 30.0):
        self.db_name = db_name
        self.table_name = table_name
        self.timeout = timeout
        self._local = threading.local()
        self._init_database()
    
    def _init_database(self):
        """Инициализация базы и таблицы"""
        conn = self.get_connection()
        if self.table_name == 'links':
            conn.execute('''
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif self.table_name == 'groups':
            conn.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        elif self.table_name == 'posts':
            conn.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
        logger.info(f"Database {self.db_name} with table {self.table_name} initialized")
    
    def get_connection(self):
        """Получение соединения (отдельное для каждого потока)"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                self.db_name,
                check_same_thread=False,
                timeout=self.timeout
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    def execute_with_retry(self, sql: str, params=(), max_retries: int = 5):
        """Выполнение SQL с повторными попытками при блокировке"""
        for attempt in range(max_retries):
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute(sql, params)
                conn.commit()
                return cursor
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    delay = 0.1 * (2 ** attempt) + random.uniform(0, 0.1)
                    logger.warning(f"DB {self.db_name} locked, retry {attempt + 1}/{max_retries} in {delay:.2f}s")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"SQL error after {max_retries} retries: {e}")
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in execute_with_retry: {e}")
                raise
    
    def execute_query(self, sql: str, params=()):
        """Выполнение SELECT запроса"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Query error in {self.db_name}: {e}")
            return []
    
    def add_link(self, link: str) -> bool:
        """Добавление ссылки в базу"""
        try:
            self.execute_with_retry(f"INSERT INTO {self.table_name} (link) VALUES (?)", (link,))
            logger.info(f"Link added to {self.db_name}: {link}")
            return True
        except Exception as e:
            logger.error(f"Error adding link to {self.db_name}: {e}")
            return False
    
    def get_recent_links(self, limit: int):
        """Получение последних ссылок"""
        try:
            sql = f"SELECT DISTINCT link FROM {self.table_name} ORDER BY id DESC LIMIT ?"
            return self.execute_query(sql, (limit,))
        except Exception as e:
            logger.error(f"Error getting links from {self.db_name}: {e}")
            return []
    
    def close(self):
        """Закрытие соединения"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            del self._local.connection
            logger.info(f"Database {self.db_name} connection closed")

# ==================== КОНСТАНТЫ И УТИЛИТЫ ====================

n1, n2, n3, n4 = 2000000003, 2000000005, 2000000006, 2000000008
admins = [794312655, 838744775, 814161744, 147438490]
lim = {n1: 11, n2: 6, n3: 4, n4: 21}

banner_text = (
    ', ваша ссылка успешно добавлена\n'
    '🚀 У нас можно заказать:\n'
    ' ✨Услугу вип;\n'
    ' ✨Бот под ключ;\n'
    ' ✨Оформление сообщества;\n'
    ' ✨Создание сайта.\n\n'
    'По всем вопросам обращайтесь к админу\n👇\n'
    'https://vk.com/dianamaysky'
)

def filer(user_id: str, path: str) -> bool:
    """Проверка наличия пользователя в файле"""
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return user_id in content
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        return False

def safe_eval(data: str) -> Dict[str, Any]:
    """Безопасное преобразование строки в словарь"""
    try:
        return eval(data) if data else {}
    except Exception as e:
        logger.error(f"Error in safe_eval: {e}")
        return {}

def save_vip_data(path: str, data: Dict[str, Any]) -> bool:
    """Сохранение VIP данных в файл"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(data))
        return True
    except Exception as e:
        logger.error(f"Error saving VIP data to {path}: {e}")
        return False

alp = set('абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz0123456789')

# ==================== МОДЕЛИ ДАННЫХ ====================

class UserState(Enum):
    START = "start"
    PROCESSING_LINKS = "processing_links"
    CHECKING_COMPLETION = "checking_completion"

class User:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.state = UserState.START
        self.last_activity = time.time()
        self.data: Dict[str, Any] = {}
    
    def set_state(self, new_state: UserState):
        self.state = new_state
        self.last_activity = time.time()
    
    def is_expired(self, timeout: int = 3600) -> bool:
        return time.time() - self.last_activity > timeout
    
    def update_activity(self):
        self.last_activity = time.time()

# ==================== ОСНОВНАЯ ЛОГИКА БОТА ====================

def main2(event) -> None:
    """Обработка одного события"""
    if event.type == VkBotEventType.MESSAGE_NEW:
        try:
            q = event.obj.message['from_id']
            z = event.obj.message['peer_id']
            
            if z not in ql:
                logger.warning(f"Unknown peer_id: {z}")
                return
                
            cl = ql[z]
            x = event.obj.message['text']
            a = vk.users.get(user_id=q)[0]
            i1, i2 = a['first_name'], a['last_name']
            namesurname = f'{i1} {i2}'
            y = event.obj.message['conversation_message_id']
            
            if q not in cl.user_states:
                cl.user_states[q] = User(q)
                
            user = cl.user_states[q]
            user.update_activity()
            
            # Обработка через конечный автомат
            cl.cond(x, y, q, namesurname)
            
        except Exception as e:
            logger.error(f"Error in main2: {e}")

def main() -> None:
    """Главный цикл бота"""
    for event in longpoll.listen():
        try:
            threading.Thread(target=main2, args=(event,), daemon=True).start()
        except Exception as e:
            logger.error(f"Error starting thread: {e}")

# ==================== БАЗОВЫЙ КЛАСС БОТА ====================

class BaseBot:
    def __init__(self):
        self.user_states: Dict[int, User] = {}
        self.limit: Dict[int, int] = {}
        self.vipslovar: Dict[int, List[str]] = {}
        self.posts: Dict[int, List[str]] = {}
        self.Ax: Dict[int, List[str]] = {}
        self.viptime: Dict[int, float] = {}
        self.ab = 1
    
    def get_user_state(self, user_id: int) -> UserState:
        if user_id not in self.user_states:
            self.user_states[user_id] = User(user_id)
        return self.user_states[user_id].state
    
    def set_user_state(self, user_id: int, state: UserState):
        if user_id not in self.user_states:
            self.user_states[user_id] = User(user_id)
        self.user_states[user_id].set_state(state)
    
    def cleanup_expired_states(self):
        """Очистка устаревших состояний пользователей"""
        current_time = time.time()
        expired_users = [
            user_id for user_id, user in self.user_states.items() 
            if user.is_expired(3600)
        ]
        for user_id in expired_users:
            del self.user_states[user_id]
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired user states")
    
    def is_user_allowed(self, user_id: int, peer_id: int) -> bool:
        """Проверка разрешения пользователя на публикацию"""
        try:
            user_info = session.users.get(user_ids=user_id)[0]
            return user_id not in self.limit and not user_info['is_closed']
        except Exception as e:
            logger.error(f"Error checking user allowance: {e}")
            return False
    
    def update_limits(self):
        """Обновление лимитов пользователей"""
        self.limit = {user_id: count-1 for user_id, count in self.limit.items() if count > 1}
    
    def send_message(self, peer_id: int, message: str, **kwargs):
        """Отправка сообщения"""
        try:
            params = {
                'peer_id': peer_id,
                'message': message,
                'random_id': 0,
                'expire_ttl': 300,
                'keyboard': self.keyboard.get_keyboard() if hasattr(self, 'keyboard') else None
            }
            params.update(kwargs)
            vk.messages.send(**params)
            logger.info(f"Message sent to {peer_id}")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    def delete_message(self, peer_id: int, message_id: int) -> bool:
        """Удаление сообщения"""
        try:
            vk.messages.delete(
                conversation_message_ids=message_id,
                peer_id=peer_id,
                delete_for_all=1
            )
            logger.info(f"Message {message_id} deleted from {peer_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False

# ==================== КЛАСС LIKE (ЛАЙКИ 10|10) ====================

class like(BaseBot):
    def __init__(self):
        super().__init__()
        # Своя БД для лайков 10|10
        self.db = BotDatabase('likes10.db', 'links')
        self.mess1 = 'пожалуйста, ЛАЙК на обязательные ссылки 𝓑𝓤𝞟:'
        self.mess2 = 'мы проставляем лайки по 10 последним ссылкам чата'
        self.mess3 = 'вы пропустили посты'
        self.path = 'vipsforlikes.txt'
        self.path3 = 'Ludil.txt'
        
        # Создание клавиатуры
        self.keyboard = VkKeyboard(one_time=False)
        self.keyboard.add_button("❤️ПРАВИЛА ЧАТА❤️", VkKeyboardColor.PRIMARY)
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('КОММЕНТАРИИ 3|3', 'https://vk.me/join/AZQ1dyv6QACC8C5Bv/yK7mou')
        self.keyboard.add_openlink_button('ПОДПИСКА 5|5', 'https://vk.me/join/AJQ1d3LBaClcmgZHeyQB5x_m')
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 20|20', 'https://vk.me/join/AZQ1dwaqQwwXhPUnUwQ6Y50Z')
        self.keyboard.add_line()
        self.keyboard.add_button("✨УСЛУГА VIP✨", VkKeyboardColor.NEGATIVE)
        self.keyboard.add_line()
        self.keyboard.add_button("🚀ТУРБО-VIP🚀", VkKeyboardColor.POSITIVE)
    
    def is_liked(self, link: str, user_id: int) -> bool:
        """Проверка лайка на пост"""
        try:
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            owner_id = int(link[link.index('wall')+4:].split('_')[0])
            result = session.likes.isLiked(
                user_id=user_id,
                item_id=post_id,
                type='post',
                owner_id=owner_id
            )
            return result['liked']
        except Exception as e:
            logger.error(f"Error checking like: {e}")
            return True
    
    def check(self, link: str) -> bool:
        """Проверка существования поста"""
        try:
            owner_id = int(link[link.index('wall')+4:link.find('_', link.index('wall')+4)])
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            session.likes.getList(
                owner_id=owner_id,
                item_id=post_id,
                type='post'
            )
            return True
        except Exception as e:
            logger.error(f"Error checking post existence: {e}")
            return False
    
    def handle_link_automata(self, user: User, message: str, y: int, namesurname: str, peer_id: int) -> Optional[str]:
        """Обработка ссылки через конечный автомат"""
        user_id = user.user_id
        
        if not self.is_user_allowed(user_id, peer_id):
            message_map = {
                n3: ' ещё НЕ прошло 3 чужих ссылок.', 
                n1: ' ещё НЕ прошло 10 чужих ссылок.', 
                n4: ' ещё НЕ прошло 20 чужих ссылок.'
            }
            message_text = message_map.get(peer_id, ' ещё НЕ прошло 5 чужих ссылок.')
            self.delete_message(n1, y)
            return f'⚠ {namesurname}{message_text} Дождитесь.'

        # Чтение VIP ссылок
        vip_data = {}
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as wl:
                    vip_content = wl.read()
                    vip_data = safe_eval(vip_content)
        except Exception as e:
            logger.error(f"Error reading VIP data: {e}")

        # Обработка VIP ссылок
        vip_links = self.sort1(vip_data, y, user_id, namesurname)
        if vip_links:
            return None
        
        if user.state == UserState.START:
            self.set_user_state(user_id, UserState.PROCESSING_LINKS)
            self.sort2(y, user_id, namesurname)
            return None
            
        elif user.state == UserState.CHECKING_COMPLETION:
            remaining_links = self.sort3(self.Ax.get(user_id, []), y, user_id, namesurname)
            if not remaining_links:
                self.set_user_state(user_id, UserState.START)
                self.limit[user_id] = lim.get(peer_id, 10)
                self.update_limits()
                
                # Добавляем ссылку в свою БД
                if self.db.add_link(message):
                    logger.info(f"Link added to likes10 by {namesurname}: {message}")
                else:
                    logger.error(f"Failed to add link to likes10: {message}")
                
                return namesurname + banner_text
        return None

    def cond(self, x: str, y: int, q: int, namesurname: str):
        """Основной метод обработки сообщений"""
        # Обработка команд
        if 'УСЛУГА VIP' in x:
            self.delete_message(n1, y)
            self.send_message(n1, 
                '✨УСЛУГА VIP✨\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯Неделя - 350 рублей\n\n'
                '🎯Месяц - 1100 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky', 
                expire_ttl=24*60*60
            )
            return
        
        elif 'ТУРБО-VIP' in x:
            self.delete_message(n1, y)
            self.send_message(n1,
                '🚀ТУРБО-VIP🚀 200+ лайков в день\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯День - 400 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky',
                expire_ttl=24*60*60
            )
            return

        self.cleanup_expired_states()

        # Обработка ссылок через автомат
        if self.cond2(x):
            user = self.user_states.get(q, User(q))
            response = self.handle_link_automata(user, x, y, namesurname, n1)
            if response:
                self.send_message(n1, response)
            return

        # Обработка VIP команд
        if len(x.split()) == 2 and x.split()[0].lower() == 'з' and self.cond2(x.split()[1]) and filer(str(q), self.path3):
            self.delete_message(n1, y)
            if q in admins or q not in self.viptime or time.time() - self.viptime.get(q, 0) > 7200:
                try:
                    vip_data = {}
                    if os.path.exists(self.path):
                        with open(self.path, 'r', encoding='utf-8') as f:
                            vip_content = f.read()
                            vip_data = safe_eval(vip_content)
                    
                    vip_data[str(q)] = x.split()[1]
                    self.viptime[q] = time.time()
                    
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n1, namesurname + ', ваша ссылка успешно добавлена!')
                    else:
                        self.send_message(n1, 'Ошибка при сохранении VIP ссылки')
                        
                except Exception as e:
                    logger.error(f"Error adding VIP link: {e}")
                    self.send_message(n1, 'Ошибка при добавлении VIP ссылки')
            else:
                self.send_message(n1, namesurname + ', Ещё не прошло 2 часа!')

        elif len(x.split()) == 1 and x.split()[0].lower() == 'у' and filer(str(q), self.path):
            self.delete_message(n1, y)
            try:
                vip_data = {}
                if os.path.exists(self.path):
                    with open(self.path, 'r', encoding='utf-8') as f:
                        vip_content = f.read()
                        vip_data = safe_eval(vip_content)
                
                if str(q) in vip_data:
                    del vip_data[str(q)]
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n1, namesurname + ', ваша ссылка успешно удалена!')
                    else:
                        self.send_message(n1, 'Ошибка при удалении VIP ссылки')
                else:
                    self.send_message(n1, 'VIP ссылка не найдена')
                    
            except Exception as e:
                logger.error(f"Error removing VIP link: {e}")
                self.send_message(n1, 'Ошибка при удалении VIP ссылки')

        elif 'ПРАВИЛА ЧАТА' in x:
            self.delete_message(n1, y)
            self.send_message(n1,
                'Вы в ❤️ЛАЙК-ЧАТЕ❤️ \n\n'
                'Здесь мы друг другу, ставим лайки на посты.\n'
                'Участие в ленте чата - БЕСПЛАТНОЕ.\n\n'
                'Работаем 10 через 10 + отработка ВИП.\n'
                'Взамен мы просим, поставить Лайки на обязательные посты и посты-ВИП.\n\n'
                '👇🏻👇🏻👇\n\n'
                '❗️ПРАВИЛА❗️\n\n'
                'В чате работает БОТ и отвечает за все процессы\n\n'
                'Разрешается публиковать только ссылку на ПОСТ, ссылки со вложениями удаляются.\n\n'
                '✅Публиковать свою ссылку можно один раз через 10 чужих ссылок\n\n'
                '❗Запрещается размещать свои ссылки на приватные аккаунты'
            )

        elif 'ТЕЛЕГРАМ' in x:
            self.delete_message(n1, y)
            self.send_message(n1, 'Взаимные вступления на каналы 3|3 \n👇\n https://ok.me/88CH1')

        elif not self.check(x) and validators.url(x):
            self.delete_message(n1, y)
            self.send_message(n1, '⚠ ' + namesurname + ', запрещено публиковать ссылку на несуществующий пост!')

        else:
            if q not in admins:
                self.delete_message(n1, y)
                self.send_message(n1, '⚠ ' + namesurname + ', разрешается публиковать только ссылку на пост.')

    def sorting(self, items: List[str], mes: str, y: int, namesurname: str):
        """Отправка списка постов для обработки"""
        if items:
            self.delete_message(n1, y)
            items_text = ''.join(f'{i}. {post}\n' for i, post in enumerate(items, 1))
            self.send_message(n1, 
                f'{namesurname},\n{mes}\n\n{items_text}\n\n'
                f'⌛ На выполнение: 6 мин после выполнения публикуйте ссылку ПОВТОРНО\n\n'
                f'=======================\n\n'
                f'🎯По услуге 𝓑𝓤𝞟, или хотите запустить бота Вконтакте или Телеграм пишите админу: https://vk.com/dianamaysky'
            )
        elif mes == self.mess2:
            self.delete_message(n1, y)
            self.send_message(n1, f'{namesurname}, вы прошли все ссылки. Размещайте свою ссылку повторно.')

    def sort1(self, vip_data: Dict[str, Any], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка VIP ссылок"""
        string = list(vip_data.values())
        self.vipslovar[q] = [
            i for i in string 
            if not self.is_liked(i, q)
        ]
        self.sorting(self.vipslovar[q], self.mess1, y, namesurname)
        return self.vipslovar[q]

    def sort2(self, y: int, q: int, namesurname: str) -> List[str]:
        """Получение обычных ссылок из БД"""
        try:
            results = self.db.get_recent_links(20)  # Берем больше, чтобы отфильтровать
            # Фильтруем в коде Python
            self.Ax[q] = []
            for row in results:
                link = row[0]
                if not self.is_liked(link, q) and self.check(link):
                    self.Ax[q].append(link)
                    if len(self.Ax[q]) >= 10:  # Ограничиваем 10 ссылками
                        break
        except Exception as e:
            logger.error(f"Error in sort2: {e}")
            self.Ax[q] = []
        
        self.sorting(self.Ax[q], self.mess2, y, namesurname)
        self.set_user_state(q, UserState.CHECKING_COMPLETION)
        return self.Ax[q]

    def sort3(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Проверка оставшихся постов"""
        self.posts[q] = [
            i for i in string 
            if not self.is_liked(i, q)
        ]
        self.sorting(self.posts[q], self.mess3, y, namesurname)
        return self.posts[q]

    def cond2(self, x: str) -> bool:
        """Проверка валидности URL для лайков"""
        return validators.url(x) and ('vk.com' in x  or 'vk.ru' in x) and 'wall' in x

# ==================== КЛАСС FOL (ПОДПИСКИ) ====================

class fol(BaseBot):
    def __init__(self):
        super().__init__()
        # Своя БД для подписок
        self.db = BotDatabase('followers.db', 'groups')
        self.path = 'vipsforpodpiska.txt'
        self.mess1 = 'пожалуйста, подписка на ссылки 𝓑𝓤𝞟'
        self.mess2 = 'пожалуйста, подпишитесь на группы'
        self.mess3 = 'вы пропустили группы'

        self.keyboard = VkKeyboard(one_time=False)
        self.keyboard.add_button("❤️ПРАВИЛА ЧАТА❤️", VkKeyboardColor.PRIMARY)
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 10|10', 'https://vk.me/join/u2oEZSUs8sfLeMy79aqTDzta/IaGSc0Ihb0=')
        self.keyboard.add_openlink_button('КОММЕНТАРИИ 3|3', 'https://vk.me/join/AZQ1dyv6QACC8C5Bv/yK7mou')
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 20|20', 'https://vk.me/join/AZQ1dwaqQwwXhPUnUwQ6Y50Z')
        self.keyboard.add_line() 
        self.keyboard.add_button("✨УСЛУГА VIP✨", VkKeyboardColor.NEGATIVE)
    
    def is_followed(self, link: str, user_id: int) -> bool:
        """Проверка подписки на группу"""
        try:
            if '@club' in link:
                group_id = link[link.find('@club')+5:]
            else:
                group_id = link[link.find('vk.com/')+7:]
            return session.groups.isMember(user_id=user_id, group_id=group_id)
        except Exception as e:
            logger.error(f"Error checking follow: {e}")
            return True

    def check(self, link: str) -> bool:
        """Проверка валидности группы"""
        try:
            group_id = link[link.find('vk.com/')+7:]
            session.groups.getMembers(group_id=group_id)
            return True
        except Exception as e:
            logger.error(f"Error checking group: {e}")
            return False

    def handle_link_automata(self, user: User, message: str, y: int, namesurname: str, peer_id: int) -> Optional[str]:
        """Обработка ссылки на группу"""
        user_id = user.user_id
        
        if user_id in self.limit:
            self.delete_message(n2, y)
            return f'⚠ {namesurname}, ещё НЕ прошло 5 чужих ссылок. Дождитесь.'

        if not self.check(message):
            self.delete_message(n2, y)
            return f'⚠ {namesurname}, запрещено публиковать ссылку на приватную группу!'

        # Чтение VIP ссылок
        vip_links = []
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as wl:
                    vip_content = wl.read()
                    vip_links = vip_content.split() if vip_content else []
        except Exception as e:
            logger.error(f"Error reading VIP groups: {e}")

        # Обработка VIP ссылок
        vip_result = self.sort1(vip_links, y, user_id, namesurname)
        if vip_result:
            return None

        # Обработка обычных ссылок через БД
        try:
            results = self.db.get_recent_links(10)  # Берем больше для фильтрации
            A = []
            for row in results:
                link = row[0]
                if not self.is_followed(link, user_id) and self.check(link):
                    A.append(link)
                    if len(A) >= 5:  # Ограничиваем 5 группами
                        break
        except Exception as e:
            logger.error(f"Error querying followers: {e}")
            A = []

        if user.state == UserState.START:
            self.set_user_state(user_id, UserState.PROCESSING_LINKS)
            self.sort2(A, y, user_id, namesurname)
            return None
            
        elif user.state == UserState.CHECKING_COMPLETION:
            remaining_links = self.sort3(self.Ax.get(user_id, []), y, user_id, namesurname)
            if not remaining_links:
                self.set_user_state(user_id, UserState.START)
                self.limit[user_id] = lim.get(peer_id, 5)
                self.update_limits()
                
                # Добавляем ссылку в свою БД
                if self.db.add_link(message):
                    logger.info(f"Group added to followers by {namesurname}: {message}")
                else:
                    logger.error(f"Failed to add group: {message}")
                
                return namesurname + banner_text
        
        return None

    def cond(self, x: str, y: int, q: int, namesurname: str):
        """Обработка сообщений для подписок"""
        if 'УСЛУГА VIP' in x:
            self.delete_message(n2, y)
            self.send_message(n2,
                '✨УСЛУГА VIP✨\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯Неделя - 400 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky',
                expire_ttl=24*60*60
            )
            return

        self.cleanup_expired_states()

        if self.cond2(x):
            user = self.user_states.get(q, User(q))
            response = self.handle_link_automata(user, x, y, namesurname, n2)
            if response:
                self.send_message(n2, response)
            return

        # Обработка других команд
        if x == '':
            self.delete_message(n2, y)
            self.send_message(n2, '⚠ ' + namesurname + ', запрещено публиковать ссылки со вложениями.')

        elif (session.users.get(user_ids=q)[0]['is_closed'] or not self.check(x)) and validators.url(x):
            self.delete_message(n2, y)
            self.send_message(n2, '⚠ ' + namesurname + ', запрещено публиковать ссылку на личную страницу, приватную группу и группу c закрытым количеством подписчиков.')

        elif 'ПРАВИЛА ЧАТА' in x:
            self.delete_message(n2, y)
            self.send_message(n2,
                'Вы в чате 🚀ВЗАИМНЫЕ ВСТУПЛЕНИЯ 5|5🚀\n\n'
                'Здесь мы вступаем друг другу в группы.\n\n'
                'Участие в ленте чата БЕСПЛАТНОЕ\n\n'
                'Работаем 5 через 5 + отработка 𝓑𝓤𝞟.\n\n'
                '👇🏻👇🏻👇\n\n'
                '❗️ПРАВИЛА❗️\n\n'
                '✅ Разрешается публиковать только ссылку на ГРУППУ\n'
                '✅ Подписывайтесь на 5 групп выше вашей ссылки\n'
                '❗ Запрещается отписываться от групп'
            )

        elif 'ТЕЛЕГРАМ' in x:
            self.delete_message(n2, y)
            self.send_message(n2, 'Взаимные вступления на каналы 3|3 \n👇\n https://ok.me/88CH1')

        else:
            if q not in admins:
                self.delete_message(n2, y)
                self.send_message(n2, f'⚠ {namesurname}, разрешается размещать только ссылку на ГРУППУ! Исправьтесь!')

    def sorting(self, items: List[str], mes: str, y: int, namesurname: str):
        """Отправка списка групп для подписки"""
        if items:
            self.delete_message(n2, y)
            items_text = ''.join(f'{i}. {link}\n' for i, link in enumerate(items, 1))
            self.send_message(n2, 
                f'{namesurname},\n{mes}\n\n{items_text}\n\n'
                f'⌛ На выполнение: 6 мин после выполнения публикуйте ссылку ПОВТОРНО\n\n'
                f'=======================\n\n'
                f'🎯По услуге 𝓑𝓤𝞟, или хотите запустить бота Вконтакте или Телеграм пишите админу: https://vk.com/dianamaysky'
            )
        elif mes == self.mess2:
            self.delete_message(n2, y)
            self.send_message(n2, f'{namesurname}, вы прошли все ссылки. Размещайте свою ссылку повторно.')

    def sort1(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка VIP групп"""
        self.vipslovar[q] = [
            i for i in string 
            if not self.is_followed(i, q)
        ]
        self.sorting(self.vipslovar[q], self.mess1, y, namesurname)
        return self.vipslovar[q]
    
    def sort2(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка обычных групп"""
        self.Ax[q] = list(islice(
            ('@club' + str(session.groups.getById(group_id=i[i.find('vk.com/')+7:])[0]['id']) 
             for i in string if self.check(i) and not self.is_followed(i, q)),
            5
        ))
        self.sorting(self.Ax[q], self.mess2, y, namesurname)
        self.set_user_state(q, UserState.CHECKING_COMPLETION)
        return self.Ax[q]

    def sort3(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Проверка оставшихся групп"""
        self.posts[q] = [
            i for i in string 
            if not self.is_followed(i, q)
        ]
        self.sorting(self.posts[q], self.mess3, y, namesurname)
        return self.posts[q]

    def cond2(self, x: str) -> bool:
        """Проверка валидности URL для групп"""
        return validators.url(x) and 'vk.com' in x and 'wall' not in x and self.check(x)

# ==================== КЛАСС COM (КОММЕНТАРИИ) ====================

class com(BaseBot):
    def __init__(self):
        super().__init__()
        # Своя БД для комментариев
        self.db = BotDatabase('comments.db', 'posts')
        self.path = 'vipsforcomments.txt'
        self.path3 = 'Ludic.txt'
        self.mess1 = 'напишите комментарии на посты-𝓑𝓤𝞟. НЕ МЕНЕЕ 5 слов, не считая эмодзи, разделяя слова пробелом'
        self.mess2 = 'напишите комментарии на обязательные посты. НЕ МЕНЕЕ 5 слов, не считая эмодзи, разделяя слова пробелом.'
        self.mess3 = 'вы пропустили посты, НЕ МЕНЕЕ 5 слов, не считая эмодзи, разделяя слова пробелом.'

        self.keyboard = VkKeyboard(one_time=False)
        self.keyboard.add_button("❤️ПРАВИЛА ЧАТА❤️", VkKeyboardColor.PRIMARY)
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 10|10', 'https://vk.me/join/u2oEZSUs8sfLeMy79aqTDzta/IaGSc0Ihb0=')
        self.keyboard.add_openlink_button('ПОДПИСКА 5|5', 'https://vk.me/join/AJQ1d3LBaClcmgZHeyQB5x_m')
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 20|20', 'https://vk.me/join/AZQ1dwaqQwwXhPUnUwQ6Y50Z')
        self.keyboard.add_line()
        self.keyboard.add_button("✨УСЛУГА VIP✨", VkKeyboardColor.NEGATIVE)
    
    def has_valid_comment(self, link: str, user_id: int) -> bool:
        """Проверка наличия валидного комментария"""
        try:
            owner_id = int(link[link.index('wall')+4:link.find('_', link.index('wall')+4)])
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            
            comments = session.wall.getComments(
                owner_id=owner_id,
                post_id=post_id,
                count=100
            )['items']
            
            for comment in comments:
                if str(user_id) in str(comment.get('from_id', '')):
                    comment_text = comment.get('text', '').lower()
                    words = [word for word in comment_text.split() if set(word) & alp != set()]
                    if len(words) > 4:
                        return True
            return False
        except Exception as e:
            logger.error(f"Error checking comment: {e}")
            return True

    def check(self, link: str) -> bool:
        """Проверка доступности комментариев"""
        try:
            owner_id = int(link[link.index('wall')+4:link.find('_', link.index('wall')+4)])
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            session.wall.getComments(
                owner_id=owner_id,
                post_id=post_id,
                count=1
            )
            return True
        except Exception as e:
            logger.error(f"Error checking commentability: {e}")
            return False

    def handle_link_automata(self, user: User, message: str, y: int, namesurname: str, peer_id: int) -> Optional[str]:
        """Обработка ссылки для комментариев"""
        user_id = user.user_id
        
        if user_id in self.limit:
            self.delete_message(n3, y)
            return f'⚠ {namesurname}, ещё НЕ прошло 3 чужих ссылок. Дождитесь.'

        if not self.check(message):
            self.delete_message(n3, y)
            return f'⚠ {namesurname}, запрещено публиковать ссылки закрытые для комментариев!'

        # Чтение VIP ссылок
        vip_data = {}
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as wl:
                    vip_content = wl.read()
                    vip_data = safe_eval(vip_content)
        except Exception as e:
            logger.error(f"Error reading VIP comments: {e}")

        # Обработка VIP ссылок
        vip_links = self.sort1(vip_data, y, user_id, namesurname)
        if vip_links:
            return None

        # Обработка обычных ссылок через БД
        try:
            results = self.db.get_recent_links(10)  # Берем больше для фильтрации
            A = []
            for row in results:
                link = row[0]
                if not self.has_valid_comment(link, user_id) and self.check(link):
                    A.append(link)
                    if len(A) >= 3:  # Ограничиваем 3 постами
                        break
        except Exception as e:
            logger.error(f"Error querying comments: {e}")
            A = []

        if user.state == UserState.START:
            self.set_user_state(user_id, UserState.PROCESSING_LINKS)
            self.sort2(A, y, user_id, namesurname)
            return None
            
        elif user.state == UserState.CHECKING_COMPLETION:
            remaining_links = self.sort3(self.Ax.get(user_id, []), y, user_id, namesurname)
            if not remaining_links:
                self.set_user_state(user_id, UserState.START)
                self.limit[user_id] = lim.get(peer_id, 3)
                self.update_limits()
                
                # Добавляем ссылку в свою БД
                if self.db.add_link(message):
                    logger.info(f"Post added to comments by {namesurname}: {message}")
                else:
                    logger.error(f"Failed to add post: {message}")
                
                return namesurname + banner_text
        
        return None

    def cond(self, x: str, y: int, q: int, namesurname: str):
        """Обработка сообщений для комментариев"""
        if 'УСЛУГА VIP' in x:
            self.delete_message(n3, y)
            self.send_message(n3,
                '✨УСЛУГА VIP✨\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯День - 250 рублей\n\n'
                '🎯Неделя - 450 рублей\n\n'
                '🎯Месяц - 1300 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky',
                expire_ttl=24*60*60
            )
            return

        self.cleanup_expired_states()

        if self.cond2(x):
            user = self.user_states.get(q, User(q))
            response = self.handle_link_automata(user, x, y, namesurname, n3)
            if response:
                self.send_message(n3, response)
            return

        # Обработка VIP команд для комментариев
        if len(x.split()) == 2 and x.split()[0].lower() == 'з' and self.cond2(x.split()[1]) and filer(str(q), self.path3):
            self.delete_message(n3, y)
            if q in admins or q not in self.viptime or time.time() - self.viptime.get(q, 0) > 7200:
                try:
                    vip_data = {}
                    if os.path.exists(self.path):
                        with open(self.path, 'r', encoding='utf-8') as f:
                            vip_content = f.read()
                            vip_data = safe_eval(vip_content)
                    
                    vip_data[str(q)] = x.split()[1]
                    self.viptime[q] = time.time()
                    
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n3, namesurname + ', ваша ссылка успешно добавлена!')
                    else:
                        self.send_message(n3, 'Ошибка при сохранении VIP ссылки')
                        
                except Exception as e:
                    logger.error(f"Error adding VIP comment link: {e}")
                    self.send_message(n3, 'Ошибка при добавлении VIP ссылки')
            else:
                self.send_message(n3, namesurname + ', Ещё не прошло 2 часа!')

        elif len(x.split()) == 1 and x.split()[0].lower() == 'у' and filer(str(q), self.path):
            self.delete_message(n3, y)
            try:
                vip_data = {}
                if os.path.exists(self.path):
                    with open(self.path, 'r', encoding='utf-8') as f:
                        vip_content = f.read()
                        vip_data = safe_eval(vip_content)
                
                if str(q) in vip_data:
                    del vip_data[str(q)]
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n3, namesurname + ', ваша ссылка успешно удалена!')
                    else:
                        self.send_message(n3, 'Ошибка при удалении VIP ссылки')
                else:
                    self.send_message(n3, 'VIP ссылка не найдена')
                    
            except Exception as e:
                logger.error(f"Error removing VIP comment link: {e}")
                self.send_message(n3, 'Ошибка при удалении VIP ссылки')

        elif 'ПРАВИЛА ЧАТА' in x:
            self.delete_message(n3, y)
            self.send_message(n3,
                'Вы в чате 🚀КОММЕНТАРИЕВ 3|3🚀\n\n'
                'Здесь мы пишем комментарии на посты друг друга.\n\n'
                'Участие в ленте чата БЕСПЛАТНОЕ\n\n'
                'Работаем 3 через 3 + отработка 𝓑𝓤𝞟.\n\n'
                '👇🏻👇🏻👇\n\n'
                '❗️ПРАВИЛА❗️\n\n'
                '✅ Комментарий должен содержать НЕ МЕНЕЕ 5 СЛОВ\n'
                '✅ Разрешается публиковать только ссылку на ПОСТ\n'
                '✅ Сначала комментируем VIP посты, затем обычные\n'
                '✅ Комментарии должны быть содержательными\n'
                '❗ Запрещаются спам и оскорбительные комментарии'
            )

        elif 'ТЕЛЕГРАМ' in x:
            self.delete_message(n3, y)
            self.send_message(n3, 'Взаимные вступления на каналы 3|3 \n👇\n https://ok.me/88CH1')

        elif not self.check(x) and self.cond2(x):
            self.delete_message(n3, y)
            self.send_message(n3, '⚠ ' + namesurname + ', разрешается публиковать только ссылки незакрытые для комментариев.')

        else:
            if q not in admins:
                self.delete_message(n3, y)
                self.send_message(n3, '⚠ ' + namesurname + ', разрешается публиковать только ссылку на пост.')

    def sorting(self, items: List[str], mes: str, y: int, namesurname: str):
        """Отправка списка постов для комментариев"""
        if items:
            self.delete_message(n3, y)
            items_text = ''.join(f'{i}. {post}\n' for i, post in enumerate(items, 1))
            self.send_message(n3, 
                f'{namesurname},\n{mes}\n\n{items_text}\n\n'
                f'⌛ На выполнение: 7 мин после выполнения публикуйте ссылку ПОВТОРНО\n\n'
                f'=======================\n\n'
                f'🎯По услуге 𝓑𝓤𝞟, или хотите запустить бота Вконтакте или Телеграм пишите админу: https://vk.com/dianamaysky'
            )
        elif mes == self.mess2:
            self.delete_message(n3, y)
            self.send_message(n3, f'{namesurname}, вы прошли все ссылки. Размещайте свою ссылку повторно.')

    def sort1(self, vip_data: Dict[str, Any], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка VIP ссылок для комментариев"""
        string = list(vip_data.values())
        self.vipslovar[q] = []
        
        for i in string:
            try:
                if len(self.vipslovar[q]) >= 3:  # Ограничение на количество постов
                    break
                    
                if not self.has_valid_comment(i, q):
                    self.vipslovar[q].append(i)
                    
            except Exception as e:
                logger.error(f"Error checking comments for post {i}: {e}")
                continue
        
        self.sorting(self.vipslovar[q], self.mess1, y, namesurname)
        return self.vipslovar[q]

    def sort2(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка обычных ссылок для комментариев"""
        self.Ax[q] = []
        
        for i in string:
            try:
                if len(self.Ax[q]) >= 3:  # Ограничение на количество постов
                    break
                    
                if not self.has_valid_comment(i, q):
                    self.Ax[q].append(i)
                    
            except Exception as e:
                logger.error(f"Error checking comments for post {i}: {e}")
                continue
        
        if self.Ax[q]:
            self.delete_message(n3, y)
            posts_text = ''.join(f'{i}. {post}\n' for i, post in enumerate(self.Ax[q], 1))
            self.send_message(n3,
                f'{namesurname},\n{self.mess2}\n\n{posts_text}\n\n'
                f'⌛ На выполнение: 7 мин\n\n'
                f'=======================\n\n'
                f'🎯По услуге 𝓑𝓤𝞟, или хотите запустить в своём чате такого же БОТА пишите админу: https://vk.com/dianamaysky'
            )
        
        self.set_user_state(q, UserState.CHECKING_COMPLETION)
        return self.Ax[q]

    def sort3(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Проверка оставшихся постов для комментариев"""
        self.posts[q] = [
            i for i in string 
            if not self.has_valid_comment(i, q)
        ]
        self.sorting(self.posts[q], self.mess3, y, namesurname)
        return self.posts[q]

    def cond2(self, x: str) -> bool:
        """Проверка валидности URL для комментариев"""
        return validators.url(x) and ('vk.com' in x or 'vk.ru' in x) and 'wall' in x and self.check(x)

# ==================== КЛАСС LIKE15 (ЛАЙКИ 20|20) ====================

class like15(BaseBot):
    def __init__(self):
        super().__init__()
        # Своя БД для лайков 20|20
        self.db = BotDatabase('likes20.db', 'links')
        self.mess1 = 'пожалуйста, ЛАЙК на обязательные ссылки 𝓑𝓤𝞟:'
        self.mess2 = 'мы проставляем лайки по 20 последним ссылкам чата'
        self.mess3 = 'вы пропустили посты'
        self.path = 'vipsforlikes15.txt'
        self.path3 = 'Ludil15.txt'

        self.keyboard = VkKeyboard(one_time=False)
        self.keyboard.add_button("❤️ПРАВИЛА ЧАТА❤️", VkKeyboardColor.PRIMARY)
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('КОММЕНТАРИИ 3|3', 'https://vk.me/join/AZQ1dyv6QACC8C5Bv/yK7mou')
        self.keyboard.add_openlink_button('ПОДПИСКА 5|5', 'https://vk.me/join/AJQ1d3LBaClcmgZHeyQB5x_m')
        self.keyboard.add_line()
        self.keyboard.add_openlink_button('ЛАЙКИ 10|10', 'https://vk.me/join/u2oEZSUs8sfLeMy79aqTDzta/IaGSc0Ihb0=')
        self.keyboard.add_line()
        self.keyboard.add_button("✨УСЛУГА VIP✨", VkKeyboardColor.NEGATIVE)
        self.keyboard.add_line()
        self.keyboard.add_button("🚀ТУРБО-VIP🚀", VkKeyboardColor.POSITIVE)
    
    def is_liked(self, link: str, user_id: int) -> bool:
        """Проверка лайка на пост"""
        try:
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            owner_id = int(link[link.index('wall')+4:].split('_')[0])
            result = session.likes.isLiked(
                user_id=user_id,
                item_id=post_id,
                type='post',
                owner_id=owner_id
            )
            return result['liked']
        except Exception as e:
            logger.error(f"Error checking like in like15: {e}")
            return True
    
    def check(self, link: str) -> bool:
        """Проверка существования поста"""
        try:
            owner_id = int(link[link.index('wall')+4:link.find('_', link.index('wall')+4)])
            post_id = int(re.findall(r'\d+', link[link.find('wall'):])[1])
            session.likes.getList(
                owner_id=owner_id,
                item_id=post_id,
                type='post'
            )
            return True
        except Exception as e:
            logger.error(f"Error checking post existence in like15: {e}")
            return False
    
    def handle_link_automata(self, user: User, message: str, y: int, namesurname: str, peer_id: int) -> Optional[str]:
        """Обработка ссылки через конечный автомат для 20|20"""
        user_id = user.user_id
        
        if not self.is_user_allowed(user_id, peer_id):
            message_map = {
                n3: ' ещё НЕ прошло 3 чужих ссылок.', 
                n1: ' ещё НЕ прошло 10 чужих ссылок.', 
                n4: ' ещё НЕ прошло 20 чужих ссылок.'
            }
            message_text = message_map.get(peer_id, ' ещё НЕ прошло 5 чужих ссылок.')
            self.delete_message(n4, y)
            return f'⚠ {namesurname}{message_text} Дождитесь.'

        # Чтение VIP ссылок
        vip_data = {}
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as wl:
                    vip_content = wl.read()
                    vip_data = safe_eval(vip_content)
        except Exception as e:
            logger.error(f"Error reading VIP data in like15: {e}")

        # Обработка VIP ссылок
        vip_links = self.sort1(vip_data, y, user_id, namesurname)
        if vip_links:
            return None
        
        if user.state == UserState.START:
            self.set_user_state(user_id, UserState.PROCESSING_LINKS)
            self.sort2(y, user_id, namesurname)
            return None
            
        elif user.state == UserState.CHECKING_COMPLETION:
            remaining_links = self.sort3(self.Ax.get(user_id, []), y, user_id, namesurname)
            if not remaining_links:
                self.set_user_state(user_id, UserState.START)
                self.limit[user_id] = lim.get(peer_id, 20)
                self.update_limits()
                
                # Добавляем ссылку в свою БД
                if self.db.add_link(message):
                    logger.info(f"Link added to likes20 by {namesurname}: {message}")
                else:
                    logger.error(f"Failed to add link to likes20: {message}")
                
                return namesurname + banner_text
        return None

    def cond(self, x: str, y: int, q: int, namesurname: str):
        """Основной метод обработки сообщений для 20|20"""
        # Обработка команд
        if 'УСЛУГА VIP' in x:
            self.delete_message(n4, y)
            self.send_message(n4,
                '✨УСЛУГА VIP✨\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯Неделя - 350 рублей\n\n'
                '🎯Месяц - 1100 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky',
                expire_ttl=24*60*60
            )
            return
        
        elif 'ТУРБО-VIP' in x:
            self.delete_message(n4, y)
            self.send_message(n4,
                '🚀ТУРБО-VIP🚀 200+ лайков в день\n\n'
                '🎯Ссылка закрепляется в чате\n\n'
                '🎯Взамен никого проходить не надо\n\n'
                '🎯Ссылку можно менять\n\n'
                '🎯День - 400 рублей\n\n'
                '🎯По всем вопросам обращайтесь к админу\n👇\n https://vk.com/dianamaysky',
                expire_ttl=24*60*60
            )
            return

        self.cleanup_expired_states()

        # Обработка ссылок через автомат
        if self.cond2(x):
            user = self.user_states.get(q, User(q))
            response = self.handle_link_automata(user, x, y, namesurname, n4)
            if response:
                self.send_message(n4, response)
            return

        # Обработка VIP команд
        if len(x.split()) == 2 and x.split()[0].lower() == 'з' and self.cond2(x.split()[1]) and filer(str(q), self.path3):
            self.delete_message(n4, y)
            if q in admins or q not in self.viptime or time.time() - self.viptime.get(q, 0) > 7200:
                try:
                    vip_data = {}
                    if os.path.exists(self.path):
                        with open(self.path, 'r', encoding='utf-8') as f:
                            vip_content = f.read()
                            vip_data = safe_eval(vip_content)
                    
                    vip_data[str(q)] = x.split()[1]
                    self.viptime[q] = time.time()
                    
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n4, namesurname + ', ваша ссылка успешно добавлена!')
                    else:
                        self.send_message(n4, 'Ошибка при сохранении VIP ссылки')
                        
                except Exception as e:
                    logger.error(f"Error adding VIP link in like15: {e}")
                    self.send_message(n4, 'Ошибка при добавлении VIP ссылки')
            else:
                self.send_message(n4, namesurname + ', Ещё не прошло 2 часа!')

        elif len(x.split()) == 1 and x.split()[0].lower() == 'у' and filer(str(q), self.path):
            self.delete_message(n4, y)
            try:
                vip_data = {}
                if os.path.exists(self.path):
                    with open(self.path, 'r', encoding='utf-8') as f:
                        vip_content = f.read()
                        vip_data = safe_eval(vip_content)
                
                if str(q) in vip_data:
                    del vip_data[str(q)]
                    if save_vip_data(self.path, vip_data):
                        self.send_message(n4, namesurname + ', ваша ссылка успешно удалена!')
                    else:
                        self.send_message(n4, 'Ошибка при удалении VIP ссылки')
                else:
                    self.send_message(n4, 'VIP ссылка не найдена')
                    
            except Exception as e:
                logger.error(f"Error removing VIP link in like15: {e}")
                self.send_message(n4, 'Ошибка при удалении VIP ссылки')

        elif 'ПРАВИЛА ЧАТА' in x:
            self.delete_message(n4, y)
            self.send_message(n4,
                'Вы в ❤️ЛАЙК-ЧАТЕ 20|20❤️ \n\n'
                'Здесь мы друг другу ставим лайки на посты.\n'
                'Участие в ленте чата - БЕСПЛАТНОЕ.\n\n'
                'Работаем 20 через 20 + отработка ВИП.\n\n'
                '👇🏻👇🏻👇\n\n'
                '❗️ПРАВИЛА❗️\n\n'
                'Разрешается публиковать только ссылку на ПОСТ.\n\n'
                '✅ Публиковать свою ссылку можно один раз через 20 чужих ссылок\n\n'
                '✅ Ставьте лайки на 20 постов выше вашей ссылки\n\n'
                '❗ Запрещается размещать ссылки на приватные аккаунты\n\n'
                '❗ Запрещается публиковать несуществующие посты\n\n'
                '✅ После выполнения лайков размещайте ссылку ПОВТОРНО'
            )

        elif not self.check(x) and validators.url(x):
            self.delete_message(n4, y)
            self.send_message(n4, '⚠ ' + namesurname + ', запрещено публиковать ссылку на несуществующий пост!')

        else:
            if q not in admins:
                self.delete_message(n4, y)
                self.send_message(n4, '⚠ ' + namesurname + ', разрешается публиковать только ссылку на пост.')

    def sorting(self, items: List[str], mes: str, y: int, namesurname: str):
        """Отправка списка постов для обработки"""
        if items:
            self.delete_message(n4, y)
            items_text = ''.join(f'{i}. {post}\n' for i, post in enumerate(items, 1))
            self.send_message(n4,
                f'{namesurname},\n{mes}\n\n{items_text}\n\n'
                f'⌛ На выполнение: 6 мин после выполнения публикуйте ссылку ПОВТОРНО\n\n'
                f'=======================\n\n'
                f'🎯По услуге 𝓑𝓤𝞟, или хотите запустить бота Вконтакте или Телеграм пишите админу: https://vk.com/dianamaysky'
            )
        elif mes == self.mess2:
            self.delete_message(n4, y)
            self.send_message(n4, f'{namesurname}, вы прошли все ссылки. Размещайте свою ссылку повторно.')

    def sort1(self, vip_data: Dict[str, Any], y: int, q: int, namesurname: str) -> List[str]:
        """Обработка VIP ссылок"""
        string = list(vip_data.values())
        self.vipslovar[q] = [
            i for i in string 
            if not self.is_liked(i, q)
        ]
        self.sorting(self.vipslovar[q], self.mess1, y, namesurname)
        return self.vipslovar[q]

    def sort2(self, y: int, q: int, namesurname: str) -> List[str]:
        """Получение обычных ссылок из БД"""
        try:
            results = self.db.get_recent_links(30)  # Берем больше, чтобы отфильтровать
            # Фильтруем в коде Python
            self.Ax[q] = []
            for row in results:
                link = row[0]
                if not self.is_liked(link, q) and self.check(link):
                    self.Ax[q].append(link)
                    if len(self.Ax[q]) >= 20:  # Ограничиваем 20 ссылками
                        break
        except Exception as e:
            logger.error(f"Error in sort2 in like15: {e}")
            self.Ax[q] = []
        
        self.sorting(self.Ax[q], self.mess2, y, namesurname)
        self.set_user_state(q, UserState.CHECKING_COMPLETION)
        return self.Ax[q]

    def sort3(self, string: List[str], y: int, q: int, namesurname: str) -> List[str]:
        """Проверка оставшихся постов"""
        self.posts[q] = [
            i for i in string 
            if not self.is_liked(i, q)
        ]
        self.sorting(self.posts[q], self.mess3, y, namesurname)
        return self.posts[q]

    def cond2(self, x: str) -> bool:
        """Проверка валидности URL для лайков"""
        return validators.url(x) and ('vk.com' in x or 'vk.ru' in x) and 'wall' in x

# ==================== ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ====================

# Создание экземпляров всех ботов
like_bot = like()
fol_bot = fol()
com_bot = com()
like15_bot = like15()

# Словарь для быстрого доступа к ботам по peer_id
ql = {
    n1: like_bot,    # Лайки 10|10
    n2: fol_bot,     # Подписки 5|5  
    n3: com_bot,     # Комментарии 3|3
    n4: like15_bot   # Лайки 20|20
}

# Глобальные переменные для VK API
vk = None
session = None
longpoll = None

if __name__ == '__main__':
    try:
        logger.info("Starting VK Bot...")
        
        # Инициализация VK API
        nomer = ''
        vk_session = vk_api.VkApi(token=nomer)
        vk = vk_session.get_api()
        
        session2 = vk_api.VkApi(
            token=''
        )
        session = session2.get_api()
        
        longpoll = VkBotLongPoll(vk_session, '212869892')
        
        logger.info("VK Bot initialized successfully")
        logger.info(f"Monitoring peer_ids: {list(ql.keys())}")
        
        # Запуск главного цикла
        while True:
            try:
                main()
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)
                
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error during initialization: {e}")
    finally:
        # Закрываем все БД при завершении
        for bot_name, bot in ql.items():
            if hasattr(bot, 'db'):
                bot.db.close()
                logger.info(f"Closed database for {bot_name}")
        logger.info("Bot shutdown complete")
