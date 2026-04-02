import os
import re
import time
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
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
        
        # Временные данные
        self.temp_tasks = {}      # Для создания заданий
        self.waiting_proof = {}   # Для ожидания ссылки на доказательство
        
        # ID администратора
        admin_id_raw = os.environ.get('ADMIN_ID', '0')
        try:
            self.admin_id = int(admin_id_raw)
        except ValueError:
            print(f"⚠️ ADMIN_ID должен быть числом, получено: {admin_id_raw}")
            self.admin_id = 0
    
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
        
        # ШАГ 1: Выбор типа задания
        if step == 'waiting_type':
            # Сравниваем с учётом эмодзи (message уже в нижнем регистре)
            if message == '🔄 репост':
                task_type = 'repost'
            elif message == '❤️ лайк':
                task_type = 'like'
            elif message == '📢 подписка':
                task_type = 'subscribe'
            elif message == '💬 комментарий':
                task_type = 'comment'
            else:
                self.send_message(
                    user_id,
                    "❌ Пожалуйста, выберите тип задания из кнопок ниже:",
                    get_task_type_keyboard()
                )
                return True
            
            self.temp_tasks[user_id]['type'] = task_type
            self.temp_tasks[user_id]['step'] = 'waiting_link'
            self.send_message(
                user_id,
                "📎 **Отправьте ссылку на пост или сообщество**\n\n"
                "На что нужно поставить лайк/репост/подписку?\n\n"
                "📌 Примеры:\n"
                "• https://vk.com/wall-237194046_90 (пост)\n"
                "• https://vk.com/club237194046 (сообщество)\n\n"
                "❌ Или напишите 'отмена' для выхода"
            )
            return True
        
        # ШАГ 2: Ожидание ссылки
        elif step == 'waiting_link':
            if message == 'отмена':
                del self.temp_tasks[user_id]
                self.send_message(
                    user_id,
                    "❌ Создание задания отменено",
                    get_main_keyboard()
                )
                return True
            
            if 'vk.com' not in message and 'vk.ru' not in message:
                self.send_message(
                    user_id,
                    "❌ **Неверная ссылка!**\n\n"
                    "Ссылка должна быть с сайта ВКонтакте (vk.com или vk.ru)\n\n"
                    "📌 Примеры:\n"
                    "• https://vk.com/wall-237194046_90\n"
                    "• https://vk.com/club237194046\n\n"
                    "Попробуйте ещё раз или напишите 'отмена'"
                )
                return True
            
            self.temp_tasks[user_id]['link'] = message
            self.temp_tasks[user_id]['step'] = 'waiting_limit'
            self.send_message(
                user_id,
                "🔢 **Введите желаемое количество выполнений** (лимит)\n\n"
                "Сколько раз нужно выполнить это задание?\n\n"
                "📌 Примеры: 10, 50, 100\n"
                "🔹 Минимум: 1\n"
                "🔹 Максимум: 1000\n\n"
                "❌ Или напишите 'отмена'"
            )
            return True
        
        # ШАГ 3: Ожидание лимита
        elif step == 'waiting_limit':
            if message == 'отмена':
                del self.temp_tasks[user_id]
                self.send_message(
                    user_id,
                    "❌ Создание задания отменено",
                    get_main_keyboard()
                )
                return True
            
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
                
                if task_id:
                    self.send_message(
                        user_id,
                        f"✅ **Задание #{task_id} успешно создано!**\n\n"
                        f"📌 Тип: {self.temp_tasks[user_id]['type']}\n"
                        f"📎 Ссылка: {self.temp_tasks[user_id]['link']}\n"
                        f"🔢 Лимит: {limit}\n\n"
                        f"📢 Теперь другие пользователи могут выполнять ваше задание!\n"
                        f"💰 За каждое выполнение вы будете получать баллы.",
                        get_main_keyboard()
                    )
                else:
                    self.send_message(
                        user_id,
                        "❌ Ошибка при создании задания. Попробуйте позже.",
                        get_main_keyboard()
                    )
                
                del self.temp_tasks[user_id]
                
            except ValueError:
                self.send_message(
                    user_id,
                    "❌ **Ошибка!**\n\n"
                    "Введите целое число от 1 до 1000.\n\n"
                    "📌 Примеры: 10, 50, 100\n\n"
                    "Попробуйте ещё раз или напишите 'отмена'"
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
            message += f"📎 Ссылка: {link}\n"
            message += f"✅ Выполнено: {completed}/{limit_count}\n\n"
        
        message += "\nЧтобы удалить задание, напишите: удалить [номер]"
        self.send_message(user_id, message, get_back_keyboard())
    
    def find_tasks(self, user_id):
        """Найти задания для выполнения"""
        tasks = self.db.get_all_active_tasks(exclude_user_id=user_id)
        
        if not tasks:
            self.send_message(
                user_id,
                "🔍 **Активных заданий пока нет!**\n\n"
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
            f"📌 Тип: {task_type}\n"
            f"📎 Ссылка: {link}\n\n"
            f"📝 **Что нужно сделать:**\n"
            f"{instruction}\n\n"
            f"✅ **После выполнения напишите 'готово'**\n"
            f"❌ Или **'пропустить'** чтобы взять другое задание"
        )
        
        self.temp_tasks[f"exec_{user_id}"] = {'task_id': task_id}
        self.send_message(user_id, message)
    
    def ask_for_proof(self, user_id, task_id):
        """Запросить у пользователя ссылку на доказательство"""
        task = self.db.get_task_by_id(task_id)
        if not task:
            return False
        
        task_id, owner_id, task_type, link, limit_count, completed, _, _ = task
        
        type_messages = {
            'repost': '📎 **Отправьте ссылку на ваш репост**\n\nПример: https://vk.com/wall123456_789',
            'like': '❤️ **Отправьте ссылку на запись, где вы поставили лайк**\n\nПример: https://vk.com/wall123456_789',
            'subscribe': '📢 **Отправьте ссылку на сообщество, на которое подписались**\n\nПример: https://vk.com/club123456',
            'comment': '💬 **Отправьте ссылку на ваш комментарий**\n\nПример: https://vk.com/wall123456_789?reply=123'
        }
        
        self.waiting_proof[user_id] = {'task_id': task_id}
        self.send_message(
            user_id,
            f"🔍 **Подтверждение выполнения задания #{task_id}**\n\n"
            f"{type_messages.get(task_type, 'Отправьте ссылку на выполненное действие:')}\n\n"
            f"❌ Или напишите 'отмена' чтобы отменить",
            get_back_keyboard()
        )
        return True
    
    def verify_completion_with_proof(self, user_id, proof_link):
        """Проверить выполнение задания по ссылке доказательства"""
        if user_id not in self.waiting_proof:
            return False
        
        task_id = self.waiting_proof[user_id]['task_id']
        task = self.db.get_task_by_id(task_id)
        
        if not task:
            del self.waiting_proof[user_id]
            return False
        
        task_id, owner_id, task_type, task_link, limit_count, completed, _, _ = task
        
        if self.db.has_completed_task(task_id, user_id):
            self.send_message(
                user_id,
                "❌ Вы уже выполняли это задание ранее!",
                get_main_keyboard()
            )
            del self.waiting_proof[user_id]
            return False
        
        if 'vk.com' not in proof_link and 'vk.ru' not in proof_link:
            self.send_message(
                user_id,
                "❌ Пожалуйста, отправьте корректную ссылку ВКонтакте\n\n"
                "Пример: https://vk.com/wall123456_789\n\n"
                "Попробуйте ещё раз или напишите 'отмена'",
                get_back_keyboard()
            )
            return False
        
        print(f"📝 Доказательство от {user_id} для задания #{task_id}: {proof_link}")
        
        is_vip = self.db.check_vip(user_id)
        bonus = 2 if is_vip else 1
        
        self.db.add_balance(user_id, bonus)
        is_completed = self.db.increment_task_completed(task_id)
        self.db.add_completion(task_id, user_id)
        
        author_vip = self.db.check_vip(owner_id)
        author_bonus = 2 if author_vip else 1
        self.db.add_balance(owner_id, author_bonus)
        
        try:
            self.send_message(
                owner_id,
                f"✅ **Ваше задание #{task_id} выполнил пользователь!**\n\n"
                f"📎 Ссылка на задание: {task_link}\n"
                f"📝 Доказательство: {proof_link}\n\n"
                f"💰 Вы получили +{author_bonus} баллов!"
            )
        except:
            pass
        
        vip_text = " (VIP: баллы удвоены!)" if is_vip else ""
        self.send_message(
            user_id,
            f"✅ **Задание #{task_id} успешно выполнено!**{vip_text}\n\n"
            f"💰 Вы получили +{bonus} балл(ов)!\n"
            f"📝 Ваше доказательство сохранено\n\n"
            f"Хотите выполнить ещё? Нажмите '🔍 Найти задания'",
            get_main_keyboard()
        )
        
        if is_completed:
            self.send_message(
                owner_id,
                f"🎉 **Поздравляем! Ваше задание #{task_id} полностью выполнено!**\n\n"
                f"✅ Всего выполнено: {limit_count}/{limit_count}"
            )
        
        del self.waiting_proof[user_id]
        return True
    
    def show_profile(self, user_id):
        """Показать профиль пользователя"""
        self.db.register_user(user_id)
        balance = self.db.get_user_balance(user_id)
        tasks = self.db.get_user_tasks(user_id)
        stats = self.db.get_task_stats(user_id)
        
        is_vip = self.db.check_vip(user_id)
        vip_status = "✅ Активен" if is_vip else "❌ Не активен"
        
        message = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: {user_id}\n"
            f"💎 Баллов: {balance}\n"
            f"⭐ VIP статус: {vip_status}\n\n"
            f"📊 **Статистика:**\n"
            f"• Активных заданий: {stats['active_tasks']}\n"
            f"• Выполненных заданий: {stats['completed_tasks']}\n"
            f"• Выполнений ваших заданий: {stats['total_completions']}\n\n"
            f"💡 **Как заработать баллы:**\n"
            f"• Выполняйте задания других (+1 балл)\n"
            f"• За ваши задания тоже начисляются баллы (+1)\n"
            f"• VIP удваивает баллы!\n\n"
            f"💰 100 баллов = 1 рубль"
        )
        
        self.send_message(user_id, message, get_main_keyboard())
    
    def show_top(self, user_id):
        """Показать топ пользователей"""
        top_users = self.db.get_top_users(10)
        
        if not top_users:
            self.send_message(
                user_id,
                "🏆 Топ пользователей пока пуст. Будьте первым!",
                get_main_keyboard()
            )
            return
        
        message = "🏆 **Топ пользователей по баллам** 🏆\n\n"
        
        for i, (uid, balance) in enumerate(top_users, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "📌"
            message += f"{medal} {i}. [id{uid}|Пользователь] — {balance} баллов\n"
        
        self.send_message(user_id, message, get_main_keyboard())
    
    def show_withdrawal_menu(self, user_id):
        """Показать меню вывода баллов"""
        balance = self.db.get_user_balance(user_id)
        
        message = (
            f"💰 **Вывод баллов**\n\n"
            f"💎 Ваш баланс: {balance} баллов\n"
            f"💱 Курс: 100 баллов = 1 рубль\n"
            f"⚠️ Минимальная сумма: 500 баллов (5 рублей)\n\n"
            f"Выберите сумму для вывода:"
        )
        
        self.send_message(user_id, message, get_withdrawal_keyboard())
    
    def process_withdrawal(self, user_id, amount):
        """Обработка заявки на вывод"""
        balance = self.db.get_user_balance(user_id)
        
        if amount < 500:
            self.send_message(
                user_id,
                f"❌ Минимальная сумма вывода — 500 баллов.\n"
                f"💰 Ваш баланс: {balance} баллов",
                get_main_keyboard()
            )
            return
        
        if balance < amount:
            self.send_message(
                user_id,
                f"❌ Недостаточно баллов!\n"
                f"💰 Ваш баланс: {balance}\n"
                f"📝 Запрошено: {amount}",
                get_main_keyboard()
            )
            return
        
        if self.db.remove_balance(user_id, amount):
            request_id = self.db.create_withdrawal_request(user_id, amount)
            
            self.send_message(
                user_id,
                f"✅ **Заявка #{request_id} создана!**\n\n"
                f"💰 Сумма: {amount} баллов ({amount // 100} руб.)\n\n"
                f"⏳ Ожидайте одобрения администратора.",
                get_main_keyboard()
            )
            
            if self.admin_id:
                self.send_message(
                    self.admin_id,
                    f"💰 **Новая заявка на вывод!**\n\n"
                    f"👤 Пользователь: [id{user_id}|ссылка]\n"
                    f"💎 Сумма: {amount} баллов ({amount // 100} руб.)\n"
                    f"🆔 Заявка #{request_id}\n\n"
                    f"✅ Для одобрения: одобрить {request_id}\n"
                    f"❌ Для отклонения: отклонить {request_id}"
                )
        else:
            self.send_message(
                user_id,
                "❌ Ошибка при создании заявки. Попробуйте позже.",
                get_main_keyboard()
            )
    
    def handle_admin_commands(self, user_id, message):
        """Обработка админ-команд"""
        if user_id != self.admin_id:
            return False
        
        if message.startswith('одобрить '):
            try:
                request_id = int(message.split()[1])
                requests = self.db.get_withdrawal_requests('pending')
                for req in requests:
                    if req[0] == request_id:
                        self.db.update_withdrawal_status(request_id, 'approved')
                        self.send_message(user_id, f"✅ Заявка #{request_id} одобрена!")
                        self.send_message(
                            req[1],
                            f"✅ **Ваша заявка #{request_id} одобрена!**\n\n"
                            f"💰 Сумма: {req[2]} баллов ({req[2] // 100} руб.)\n\n"
                            f"Свяжитесь с администратором для получения выплаты: [id{self.admin_id}|админ]"
                        )
                        return True
                self.send_message(user_id, f"❌ Заявка #{request_id} не найдена")
            except:
                self.send_message(user_id, "❌ Используйте: одобрить [номер]")
            return True
        
        if message.startswith('отклонить '):
            try:
                request_id = int(message.split()[1])
                requests = self.db.get_withdrawal_requests('pending')
                for req in requests:
                    if req[0] == request_id:
                        self.db.update_withdrawal_status(request_id, 'rejected')
                        self.db.add_balance(req[1], req[2])
                        self.send_message(user_id, f"❌ Заявка #{request_id} отклонена.")
                        self.send_message(
                            req[1],
                            f"❌ **Ваша заявка #{request_id} отклонена**\n\n"
                            f"Баллы возвращены на счёт."
                        )
                        return True
                self.send_message(user_id, f"❌ Заявка #{request_id} не найдена")
            except:
                self.send_message(user_id, "❌ Используйте: отклонить [номер]")
            return True
        
        if message == 'статистика':
            total_users = self.db.get_total_users_count()
            total_completions = self.db.get_total_completions_count()
            active_tasks = self.db.get_active_tasks_count()
            
            self.db.cursor.execute("SELECT SUM(balance) FROM users")
            total_balance = self.db.cursor.fetchone()[0] or 0
            
            msg = (
                f"📊 **Статистика бота**\n\n"
                f"👥 Пользователей: {total_users}\n"
                f"📋 Активных заданий: {active_tasks}\n"
                f"✅ Выполнено заданий: {total_completions}\n"
                f"💎 Баллов в системе: {total_balance}\n"
            )
            self.send_message(user_id, msg)
            return True
        
        return False
    
    def handle_message(self, event):
        """Обработка сообщений"""
        user_id = event.obj['message']['from_id']
        message = event.obj['message']['text'].lower()
        original_message = event.obj['message']['text']
        
        self.db.register_user(user_id)
        
        # Админ-команды
        if self.handle_admin_commands(user_id, original_message):
            return
        
        # Ожидание доказательства
        if user_id in self.waiting_proof:
            if message == 'отмена':
                del self.waiting_proof[user_id]
                self.send_message(user_id, "❌ Подтверждение выполнения отменено", get_main_keyboard())
                return
            self.verify_completion_with_proof(user_id, original_message)
            return
        
        # СОЗДАНИЕ ЗАДАНИЯ (пошаговое)
        if user_id in self.temp_tasks and self.temp_tasks[user_id].get('step'):
            if self.create_task_step(user_id, original_message):
                return
        
        # Выполнение задания (после "готово")
        if f"exec_{user_id}" in self.temp_tasks:
            if message == 'готово':
                task_id = self.temp_tasks[f"exec_{user_id}"]['task_id']
                del self.temp_tasks[f"exec_{user_id}"]
                self.ask_for_proof(user_id, task_id)
                return
            elif message == 'пропустить':
                del self.temp_tasks[f"exec_{user_id}"]
                self.find_tasks(user_id)
                return
        
        # ОСНОВНЫЕ КОМАНДЫ
        if message == 'меню' or message == 'начать' or message == 'start':
            self.send_message(
                user_id,
                "🤖 **Добро пожаловать в бота взаимного пиара!**\n\n"
                "Я помогаю набирать репосты, лайки, подписчиков и комментарии.\n\n"
                "📌 **Как это работает:**\n"
                "1️⃣ Вы создаёте задание\n"
                "2️⃣ Другие пользователи выполняют его\n"
                "3️⃣ Вы получаете баллы за каждое выполнение\n"
                "4️⃣ Баллы можно вывести на карту!\n\n"
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
        
        elif 'топ пользователей' in message or '🏆 топ пользователей' in message:
            self.show_top(user_id)
        
        elif 'вывод баллов' in message or '💰 вывод баллов' in message:
            self.show_withdrawal_menu(user_id)
        
        elif 'купить vip' in message or '⭐ купить vip' in message:
            balance = self.db.get_user_balance(user_id)
            if self.db.check_vip(user_id):
                self.send_message(user_id, "⭐ У вас уже активен VIP статус!", get_main_keyboard())
                return
            
            if balance >= 100:
                self.db.remove_balance(user_id, 100)
                self.db.add_vip(user_id, 30)
                self.send_message(
                    user_id,
                    f"⭐ **VIP статус активирован на 30 дней!**\n\n"
                    f"💰 Остаток на балансе: {self.db.get_user_balance(user_id)} баллов",
                    get_main_keyboard()
                )
            else:
                self.send_message(
                    user_id,
                    f"❌ Недостаточно баллов! Нужно 100, у вас {balance}",
                    get_main_keyboard()
                )
        
        elif 'помощь' in message or '❓ помощь' in message:
            self.send_message(
                user_id,
                "❓ **Помощь**\n\n"
                "📋 **Команды:**\n"
                "• Меню — Главное меню\n"
                "• Мои задания — Просмотр заданий\n"
                "• Создать задание — Новое задание\n"
                "• Найти задания — Выполнить чужие задания\n"
                "• Мой аккаунт — Баланс и статистика\n"
                "• Купить VIP — Премиум статус (100 баллов/30 дней)\n"
                "• Вывод баллов — Заказать вывод на карту\n"
                "• Топ пользователей — Рейтинг\n\n"
                "💡 100 баллов = 1 рубль",
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
                            self.send_message(user_id, f"✅ Задание #{task_num} удалено!", get_main_keyboard())
                            return
                    self.send_message(user_id, f"❌ Задание #{task_num} не найдено", get_main_keyboard())
            except:
                self.send_message(user_id, "❌ Используйте: удалить [номер]", get_main_keyboard())
        
        elif message in ['50', '100', '250', '500', '1000']:
            self.process_withdrawal(user_id, int(message))
        
        else:
            self.send_message(
                user_id,
                "❓ Неизвестная команда\n\nНапишите 'Меню'",
                get_main_keyboard()
            )
    
    def run(self):
        """Запуск бота"""
        print("=" * 50)
        print("🤖 VK Mutual PR Bot")
        print("=" * 50)
        print(f"👥 ID сообщества: {self.group_id}")
        print(f"👑 Админ ID: {self.admin_id if self.admin_id else 'не указан'}")
        print("⏳ Ожидание сообщений...")
        print("=" * 50)
        
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
