import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
import re
from database import Database
from keyboards import *

class MutualPRBot:
    def __init__(self):
        # Берём токен и ID из переменных окружения
        self.token = os.environ.get('VK_TOKEN')
        self.group_id = int(os.environ.get('VK_GROUP_ID', 0))
        
        # Проверка наличия токена
        if not self.token:
            raise ValueError("❌ Ошибка: переменная окружения VK_TOKEN не установлена!")
        if not self.group_id:
            raise ValueError("❌ Ошибка: переменная окружения VK_GROUP_ID не установлена!")
        
        self.vk_session = vk_api.VkApi(token=self.token)
        self.longpoll = VkBotLongPoll(self.vk_session, self.group_id)
        self.vk = self.vk_session.get_api()
        self.db = Database()
        
        # Временные данные для создания заданий
        self.temp_tasks = {}
    
    def send_message(self, user_id, message, keyboard=None):
        """Отправка сообщения"""
        try:
            self.vk.messages.send(
                user_id=user_id,
                message=message,
                random_id=get_random_id(),
                keyboard=keyboard.get_keyboard() if keyboard else None
            )
        except Exception as e:
            print(f"Ошибка отправки: {e}")
    
    def extract_post_info(self, link):
        """Извлечение информации из ссылки ВК"""
        post_pattern = r'(?:vk\.com|vk\.ru)/wall(-?\d+)_(\d+)'
        match = re.search(post_pattern, link)
        if match:
            return ('post', match.group(1), match.group(2))
        
        group_pattern = r'(?:vk\.com|vk\.ru)/club(\d+)'
        match = re.search(group_pattern, link)
        if match:
            return ('group', match.group(1), None)
        
        return None
    
    def create_task_step(self, user_id, message):
        """Пошаговое создание задания"""
        if user_id not in self.temp_tasks:
            return False
        
        step = self.temp_tasks[user_id]['step']
        
        if step == 'waiting_type':
            task_type_map = {
                '🔄 репост': 'repost',
                '❤️ лайк': 'like',
                '📢 подписка': 'subscribe',
                '💬 комментарий': 'comment'
            }
            
            if message in task_type_map:
                self.temp_tasks[user_id]['type'] = task_type_map[message]
                self.temp_tasks[user_id]['step'] = 'waiting_link'
                self.send_message(
                    user_id,
                    "📎 Отправьте ссылку на пост или сообщество:\n\n"
                    "Примеры:\n"
                    "• https://vk.com/wall-237194046_90\n"
                    "• https://vk.com/club237194046\n\n"
                    "Для отмены напишите 'отмена'"
                )
            else:
                self.send_message(
                    user_id,
                    "❌ Пожалуйста, выберите тип задания из кнопок ниже:",
                    get_task_type_keyboard()
                )
            return True
        
        elif step == 'waiting_link':
            if message == 'отмена':
                del self.temp_tasks[user_id]
                self.send_message(
                    user_id,
                    "❌ Создание задания отменено",
                    get_main_keyboard()
                )
                return True
            
            link_info = self.extract_post_info(message)
            if not link_info:
                self.send_message(
                    user_id,
                    "❌ Неверная ссылка! Отправьте ссылку вида:\n"
                    "https://vk.com/wall-123456_789 или https://vk.com/club123456"
                )
                return True
            
            self.temp_tasks[user_id]['link'] = message
            self.temp_tasks[user_id]['step'] = 'waiting_limit'
            self.send_message(
                user_id,
                "🔢 Введите желаемое количество (лимит):\n"
                "Например: 10, 50, 100\n\n"
                "Минимум: 1, Максимум: 1000"
            )
            return True
        
        elif step == 'waiting_limit':
            try:
                limit = int(message)
                if limit < 1 or limit > 1000:
                    raise ValueError
                
                task_id = self.db.create_task(
                    user_id,
                    self.temp_tasks[user_id]['type'],
                    self.temp_tasks[user_id]['link'],
                    limit
                )
                
                del self.temp_tasks[user_id]
                
                self.send_message(
                    user_id,
                    f"✅ Задание #{task_id} успешно создано!\n\n"
                    f"Лимит: {limit}\n\n"
                    f"Когда другие пользователи выполнят ваше задание, "
                    f"вы будете получать баллы!",
                    get_main_keyboard()
                )
            except ValueError:
                self.send_message(
                    user_id,
                    "❌ Введите целое число от 1 до 1000"
                )
            return True
        
        return False
    
    def show_tasks(self, user_id):
        """Показать задания пользователя"""
        tasks = self.db.get_user_tasks(user_id)
        
        if not tasks:
            self.send_message(
                user_id,
                "📭 У вас пока нет активных заданий.\n\n"
                "Нажмите '➕ Создать задание', чтобы начать!",
                get_main_keyboard()
            )
            return
        
        message = "📋 **Ваши активные задания:**\n\n"
        type_emoji = {
            'repost': '🔄',
            'like': '❤️',
            'subscribe': '📢',
            'comment': '💬'
        }
        
        for task in tasks:
            task_id, _, task_type, link, limit_count, completed, active, _ = task
            emoji = type_emoji.get(task_type, '📎')
            message += f"{emoji} **Задание #{task_id}**\n"
            message += f"Ссылка: {link}\n"
            message += f"Выполнено: {completed}/{limit_count}\n\n"
        
        message += "\nЧтобы удалить задание, напишите: удалить [номер]"
        self.send_message(user_id, message)
    
    def find_tasks(self, user_id):
        """Найти задания для выполнения"""
        tasks = self.db.get_all_active_tasks(exclude_user_id=user_id)
        
        if not tasks:
            self.send_message(
                user_id,
                "🔍 Активных заданий пока нет!\n\n"
                "Создайте своё задание, чтобы другие начали выполнять, "
                "а вы получали баллы!",
                get_main_keyboard()
            )
            return
        
        task = tasks[0]
        task_id, owner_id, task_type, link, limit_count, completed, _, _ = task
        
        if self.db.has_completed_task(task_id, user_id):
            for t in tasks[1:]:
                if not self.db.has_completed_task(t[0], user_id):
                    task = t
                    break
            else:
                self.send_message(
                    user_id,
                    "✅ Вы уже выполнили все доступные задания!\n\n"
                    "Новые появятся позже.",
                    get_main_keyboard()
                )
                return
        
        task_id = task[0]
        task_type = task[2]
        link = task[3]
        
        type_instructions = {
            'repost': 'сделать репост этой записи на свою стену',
            'like': 'поставить лайк',
            'subscribe': 'подписаться на сообщество',
            'comment': 'написать комментарий (не менее 5 слов)'
        }
        
        instruction = type_instructions.get(task_type, 'выполнить действие')
        
        message = (
            f"🎯 **Новое задание!**\n\n"
            f"Тип: {task_type}\n"
            f"Ссылка: {link}\n\n"
            f"📝 Что нужно сделать:\n"
            f"{instruction}\n\n"
            f"✅ После выполнения напишите 'готово'\n"
            f"❌ Или 'пропустить' чтобы взять другое задание"
        )
        
        self.temp_tasks[f"exec_{user_id}"] = {'task_id': task_id}
        self.send_message(user_id, message)
    
    def verify_completion(self, user_id, task_id):
        """Проверка выполнения задания"""
        tasks = self.db.get_user_tasks(task_id, active_only=False)
        task = None
        for t in tasks:
            if t[0] == task_id:
                task = t
                break
        
        if not task:
            return False
        
        _, owner_id, task_type, link, limit_count, completed, _, _ = task
        
        self.db.add_balance(user_id, 1)
        is_completed = self.db.increment_task_completed(task_id)
        self.db.add_completion(task_id, user_id)
        self.db.add_balance(owner_id, 1)
        
        return True
    
    def show_profile(self, user_id):
        """Показать профиль пользователя"""
        self.db.register_user(user_id)
        balance = self.db.get_user_balance(user_id)
        tasks = self.db.get_user_tasks(user_id)
        
        self.db.cursor.execute(
            "SELECT vip_expires FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.db.cursor.fetchone()
        vip_expires = result[0] if result else 0
        
        vip_status = "✅ Активен" if vip_expires > 0 else "❌ Не активен"
        
        message = (
            f"👤 **Ваш профиль**\n\n"
            f"💎 Баллов: {balance}\n"
            f"📊 Активных заданий: {len(tasks)}\n"
            f"⭐ VIP статус: {vip_status}\n\n"
            f"💡 Как заработать баллы:\n"
            f"• Выполняйте задания других пользователей (+1 балл)\n"
            f"• За ваши задания также начисляются баллы (+1 за выполнение)"
        )
        
        self.send_message(user_id, message, get_main_keyboard())
    
    def handle_message(self, event):
        """Обработка сообщений"""
        user_id = event.obj['message']['from_id']
        message = event.obj['message']['text'].lower()
        original_message = event.obj['message']['text']
        
        self.db.register_user(user_id)
        
        if user_id in self.temp_tasks and self.temp_tasks[user_id].get('step'):
            if self.create_task_step(user_id, original_message):
                return
        
        if f"exec_{user_id}" in self.temp_tasks:
            if message == 'готово':
                task_id = self.temp_tasks[f"exec_{user_id}"]['task_id']
                if self.verify_completion(user_id, task_id):
                    self.send_message(
                        user_id,
                        "✅ Отлично! Задание выполнено.\n"
                        "Вы получили +1 балл!\n\n"
                        "Хотите выполнить ещё? Нажмите '🔍 Найти задания'",
                        get_main_keyboard()
                    )
                else:
                    self.send_message(
                        user_id,
                        "❌ Не удалось проверить выполнение. Попробуйте позже.",
                        get_main_keyboard()
                    )
                del self.temp_tasks[f"exec_{user_id}"]
                return
            elif message == 'пропустить':
                del self.temp_tasks[f"exec_{user_id}"]
                self.find_tasks(user_id)
                return
        
        if message == 'меню' or message == 'начать' or message == 'start':
            self.send_message(
                user_id,
                "🤖 **Добро пожаловать в бота взаимного пиара!**\n\n"
                "Я помогаю набирать репосты, лайки, подписчиков и комментарии.\n\n"
                "📌 **Как это работает:**\n"
                "1. Вы создаёте задание\n"
                "2. Другие пользователи выполняют его\n"
                "3. Вы получаете баллы за каждое выполнение\n\n"
                "Выберите действие в меню ниже:",
                get_main_keyboard()
            )
        
        elif 'мои задания' in message or message == '📋 мои задания':
            self.show_tasks(user_id)
        
        elif 'создать задание' in message or message == '➕ создать задание':
            self.temp_tasks[user_id] = {'step': 'waiting_type'}
            self.send_message(
                user_id,
                "📝 **Создание нового задания**\n\n"
                "Выберите тип задания:",
                get_task_type_keyboard()
            )
        
        elif 'найти задания' in message or '🔍 найти задания' in message:
            self.find_tasks(user_id)
        
        elif 'мой аккаунт' in message or '👤 мой аккаунт' in message:
            self.show_profile(user_id)
        
        elif 'купить vip' in message or '⭐ купить vip' in message:
            self.send_message(
                user_id,
                "⭐ **VIP статус**\n\n"
                "⚙️ Функция в разработке. Скоро будет доступна!",
                get_main_keyboard()
            )
        
        elif 'помощь' in message or '❓ помощь' in message:
            self.send_message(
                user_id,
                "❓ **Помощь**\n\n"
                "📋 **Команды:**\n"
                "• Меню - Главное меню\n"
                "• Мои задания - Просмотр заданий\n"
                "• Создать задание - Новое задание\n"
                "• Найти задания - Выполнить чужие задания\n"
                "• Мой аккаунт - Баланс и статистика\n\n"
                "По всем вопросам: @admin",
                get_main_keyboard()
            )
        
        elif message.startswith('удалить'):
            try:
                parts = message.split()
                if len(parts) == 2:
                    task_num = int(parts[1])
                    tasks = self.db.get_user_tasks(user_id)
                    for task in tasks:
                        if task[0] == task_num:
                            self.db.delete_task(task_num, user_id)
                            self.send_message(
                                user_id,
                                f"✅ Задание #{task_num} удалено!",
                                get_main_keyboard()
                            )
                            return
                    self.send_message(
                        user_id,
                        f"❌ Задание #{task_num} не найдено",
                        get_main_keyboard()
                    )
            except:
                self.send_message(
                    user_id,
                    "❌ Используйте формат: удалить [номер]\n"
                    "Пример: удалить 5",
                    get_main_keyboard()
                )
        
        else:
            self.send_message(
                user_id,
                "❓ Неизвестная команда\n\n"
                "Напишите 'Меню' для просмотра доступных действий",
                get_main_keyboard()
            )
    
    def run(self):
        """Запуск бота"""
        print("🤖 Бот запущен!")
        print(f"👥 ID сообщества: {self.group_id}")
        print("⏳ Ожидание сообщений...\n")
        
        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    self.handle_message(event)
                except Exception as e:
                    print(f"❌ Ошибка: {e}")
                    import traceback
                    traceback.print_exc()

if __name__ == '__main__':
    bot = MutualPRBot()
    bot.run()
