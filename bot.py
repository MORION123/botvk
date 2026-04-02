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
        
        # Временные данные для создания заданий
        self.temp_tasks = {}
        
        # ID администратора (можно указать свой)
        self.admin_id = int(os.environ.get('ADMIN_ID', 0))
    
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
            print(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
    
    def extract_post_info(self, link):
        """Извлечение информации из ссылки ВК"""
        # Для постов: vk.com/wall-237194046_90
        post_pattern = r'(?:vk\.com|vk\.ru)/wall(-?\d+)_(\d+)'
        match = re.search(post_pattern, link)
        if match:
            return ('post', match.group(1), match.group(2))
        
        # Для групп: vk.com/club123456
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
                
                if task_id:
                    self.send_message(
                        user_id,
                        f"✅ Задание #{task_id} успешно создано!\n\n"
                        f"Тип: {self.temp_tasks[user_id]['type']}\n"
                        f"Лимит: {limit}\n\n"
                        f"Когда другие пользователи выполнят ваше задание, "
                        f"вы будете получать баллы!\n\n"
                        f"💡 Совет: разместите ссылку на бота в вашем сообществе, "
                        f"чтобы подписчики могли выполнять задания!",
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
        
        message += "\nЧтобы удалить задание, напишите: удалить [номер]\n"
        message += "Пример: удалить 5"
        
        self.send_message(user_id, message, get_back_keyboard())
    
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
        
        # Берём первое задание
        task = tasks[0]
        task_id, owner_id, task_type, link, limit_count, completed, _, _ = task
        
        # Проверяем, не выполнял ли уже пользователь это задание
        if self.db.has_completed_task(task_id, user_id):
            # Ищем следующее
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
            f"📎 Ссылка: {link}\n"
            f"📝 Что нужно сделать:\n"
            f"{instruction}\n\n"
            f"✅ После выполнения напишите **'готово'**\n"
            f"❌ Или **'пропустить'** чтобы взять другое задание"
        )
        
        # Сохраняем текущее задание для пользователя
        self.temp_tasks[f"exec_{user_id}"] = {'task_id': task_id}
        
        self.send_message(user_id, message)
    
    def verify_completion(self, user_id, task_id):
        """Проверка выполнения задания"""
        # Получаем информацию о задании
        task = self.db.get_task_by_id(task_id)
        
        if not task:
            return False
        
        task_id, owner_id, task_type, link, limit_count, completed, _, _ = task
        
        # Проверяем, не выполнял ли уже пользователь это задание
        if self.db.has_completed_task(task_id, user_id):
            self.send_message(
                user_id,
                "❌ Вы уже выполняли это задание ранее!",
                get_main_keyboard()
            )
            return False
        
        # Проверка VIP для удвоенных баллов
        is_vip = self.db.check_vip(user_id)
        bonus = 2 if is_vip else 1
        
        # Начисляем баллы выполнившему
        self.db.add_balance(user_id, bonus)
        
        # Увеличиваем счётчик задания
        is_completed = self.db.increment_task_completed(task_id)
        
        # Записываем выполнение
        self.db.add_completion(task_id, user_id)
        
        # Начисляем баллы автору задания (тоже с учётом VIP)
        author_vip = self.db.check_vip(owner_id)
        author_bonus = 2 if author_vip else 1
        self.db.add_balance(owner_id, author_bonus)
        
        # Уведомляем автора (асинхронно, не блокируем)
        try:
            self.send_message(
                owner_id,
                f"✅ Ваше задание #{task_id} выполнил пользователь!\n"
                f"Вы получили +{author_bonus} баллов!"
            )
        except:
            pass
        
        # Сообщаем выполнившему
        vip_text = " (VIP: баллы удвоены!)" if is_vip else ""
        self.send_message(
            user_id,
            f"✅ Отлично! Задание выполнено.{vip_text}\n"
            f"Вы получили +{bonus} балл(ов)!\n\n"
            f"Хотите выполнить ещё? Нажмите '🔍 Найти задания'",
            get_main_keyboard()
        )
        
        # Если задание полностью выполнено, уведомляем автора
        if is_completed:
            self.send_message(
                owner_id,
                f"🎉 Поздравляем! Ваше задание #{task_id} полностью выполнено!\n"
                f"Всего выполнено: {limit_count}/{limit_count}"
            )
        
        return True
    
    def show_profile(self, user_id):
        """Показать профиль пользователя"""
        self.db.register_user(user_id)
        balance = self.db.get_user_balance(user_id)
        tasks = self.db.get_user_tasks(user_id)
        stats = self.db.get_task_stats(user_id)
        
        is_vip = self.db.check_vip(user_id)
        vip_status = "✅ Активен" if is_vip else "❌ Не активен"
        
        # Получаем дату регистрации
        self.db.cursor.execute(
            "SELECT registered_at FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.db.cursor.fetchone()
        reg_date = result[0][:10] if result else "неизвестно"
        
        message = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: {user_id}\n"
            f"📅 Регистрация: {reg_date}\n"
            f"💎 Баллов: {balance}\n"
            f"⭐ VIP статус: {vip_status}\n\n"
            f"📊 **Статистика заданий:**\n"
            f"• Активных заданий: {stats['active_tasks']}\n"
            f"• Выполненных заданий: {stats['completed_tasks']}\n"
            f"• Всего выполнений ваших заданий: {stats['total_completions']}\n\n"
            f"💡 **Как заработать баллы:**\n"
            f"• Выполняйте задания других пользователей (+1 балл)\n"
            f"• За ваши задания также начисляются баллы (+1 за выполнение)\n"
            f"• VIP статус удваивает баллы!\n\n"
            f"💰 **100 баллов = 1 рубль** (вывод от 500 баллов)"
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
            f"Ваш баланс: {balance} баллов\n"
            f"Курс: 100 баллов = 1 рубль\n"
            f"Минимальная сумма вывода: 500 баллов (5 рублей)\n\n"
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
                f"Ваш баланс: {balance} баллов",
                get_main_keyboard()
            )
            return
        
        if balance < amount:
            self.send_message(
                user_id,
                f"❌ Недостаточно баллов!\n"
                f"Ваш баланс: {balance}\n"
                f"Запрошено: {amount}",
                get_main_keyboard()
            )
            return
        
        # Списываем баллы
        if self.db.remove_balance(user_id, amount):
            # Создаём заявку
            request_id = self.db.create_withdrawal_request(user_id, amount)
            
            self.send_message(
                user_id,
                f"✅ Заявка #{request_id} на вывод {amount} баллов создана!\n"
                f"Сумма к выплате: {amount // 100} рублей\n\n"
                f"Ожидайте одобрения администратора.",
                get_main_keyboard()
            )
            
            # Уведомляем админа
            if self.admin_id:
                self.send_message(
                    self.admin_id,
                    f"💰 Новая заявка на вывод!\n\n"
                    f"👤 Пользователь: [id{user_id}|ссылка]\n"
                    f"💎 Сумма: {amount} баллов ({amount // 100} руб.)\n"
                    f"🆔 Заявка #{request_id}\n\n"
                    f"Для одобрения напишите: одобрить {request_id}\n"
                    f"Для отклонения: отклонить {request_id}"
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
        
        # Одобрение заявки
        if message.startswith('одобрить '):
            try:
                request_id = int(message.split()[1])
                requests = self.db.get_withdrawal_requests('pending')
                for req in requests:
                    if req[0] == request_id:
                        self.db.update_withdrawal_status(request_id, 'approved')
                        self.send_message(
                            user_id,
                            f"✅ Заявка #{request_id} одобрена!\n"
                            f"Пользователь уведомлён."
                        )
                        # Уведомляем пользователя
                        self.send_message(
                            req[1],
                            f"✅ Ваша заявка #{request_id} на вывод {req[2]} баллов одобрена!\n"
                            f"Свяжитесь с администратором для получения выплаты."
                        )
                        return True
                self.send_message(user_id, f"❌ Заявка #{request_id} не найдена")
            except:
                self.send_message(user_id, "❌ Используйте: одобрить [номер]")
            return True
        
        # Отклонение заявки
        if message.startswith('отклонить '):
            try:
                request_id = int(message.split()[1])
                requests = self.db.get_withdrawal_requests('pending')
                for req in requests:
                    if req[0] == request_id:
                        self.db.update_withdrawal_status(request_id, 'rejected')
                        # Возвращаем баллы пользователю
                        self.db.add_balance(req[1], req[2])
                        self.send_message(
                            user_id,
                            f"❌ Заявка #{request_id} отклонена.\n"
                            f"Баллы возвращены пользователю."
                        )
                        self.send_message(
                            req[1],
                            f"❌ Ваша заявка #{request_id} на вывод {req[2]} баллов отклонена.\n"
                            f"Баллы возвращены на счёт."
                        )
                        return True
                self.send_message(user_id, f"❌ Заявка #{request_id} не найдена")
            except:
                self.send_message(user_id, "❌ Используйте: отклонить [номер]")
            return True
        
        # Статистика для админа
        if message == 'статистика':
            total_users = self.db.get_total_users_count()
            total_completions = self.db.get_total_completions_count()
            active_tasks = self.db.get_active_tasks_count()
            
            self.db.cursor.execute("SELECT SUM(balance) FROM users")
            total_balance = self.db.cursor.fetchone()[0] or 0
            
            message = (
                f"📊 **Статистика бота**\n\n"
                f"👥 Пользователей: {total_users}\n"
                f"📋 Активных заданий: {active_tasks}\n"
                f"✅ Выполнено заданий: {total_completions}\n"
                f"💎 Баллов в системе: {total_balance}\n"
            )
            self.send_message(user_id, message)
            return True
        
        return False
    
    def handle_message(self, event):
        """Обработка сообщений"""
        user_id = event.obj['message']['from_id']
        message = event.obj['message']['text'].lower()
        original_message = event.obj['message']['text']
        
        # Регистрируем пользователя
        self.db.register_user(user_id)
        
        # Проверка админ-команд
        if self.handle_admin_commands(user_id, original_message):
            return
        
        # Проверка на пошаговое создание задания
        if user_id in self.temp_tasks and self.temp_tasks[user_id].get('step'):
            if self.create_task_step(user_id, original_message):
                return
        
        # Проверка на выполнение задания
        if f"exec_{user_id}" in self.temp_tasks:
            if message == 'готово':
                task_id = self.temp_tasks[f"exec_{user_id}"]['task_id']
                self.verify_completion(user_id, task_id)
                del self.temp_tasks[f"exec_{user_id}"]
                return
            elif message == 'пропустить':
                del self.temp_tasks[f"exec_{user_id}"]
                self.find_tasks(user_id)
                return
        
        # Обработка команд
        if message == 'меню' or message == 'начать' or message == 'start':
            self.send_message(
                user_id,
                "🤖 **Добро пожаловать в бота взаимного пиара!**\n\n"
                "Я помогаю набирать репосты, лайки, подписчиков и комментарии.\n\n"
                "📌 **Как это работает:**\n"
                "1. Вы создаёте задание (репост, лайк и т.д.)\n"
                "2. Другие пользователи выполняют его\n"
                "3. Вы получаете баллы за каждое выполнение\n"
                "4. Баллы можно вывести на карту!\n\n"
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
            is_vip = self.db.check_vip(user_id)
            
            if is_vip:
                self.send_message(
                    user_id,
                    "⭐ У вас уже активен VIP статус!",
                    get_main_keyboard()
                )
                return
            
            if balance >= 100:
                self.db.remove_balance(user_id, 100)
                self.db.add_vip(user_id, 30)
                self.send_message(
                    user_id,
                    "⭐ **Поздравляем!** Вы приобрели VIP статус на 30 дней!\n\n"
                    "Теперь вы получаете **удвоенные баллы** за выполнение заданий!\n"
                    f"Осталось на балансе: {self.db.get_user_balance(user_id)} баллов",
                    get_main_keyboard()
                )
            else:
                self.send_message(
                    user_id,
                    f"❌ Недостаточно баллов для покупки VIP!\n"
                    f"Нужно: 100 баллов\n"
                    f"У вас: {balance} баллов\n\n"
                    f"Выполняйте задания других пользователей, чтобы заработать баллы!",
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
                "💡 **Советы:**\n"
                "• За каждое выполнение вы получаете +1 балл\n"
                "• За выполнение вашего задания тоже +1 балл\n"
                "• VIP статус удваивает баллы!\n"
                "• 100 баллов = 1 рубль\n\n"
                "❓ Вопросы и предложения: @admin",
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
        
        elif 'назад' in message or '⬅ назад' in message:
            self.send_message(
                user_id,
                "Вы вернулись в главное меню",
                get_main_keyboard()
            )
        
        elif message.startswith('50') or message.startswith('100') or message.startswith('250') or message.startswith('500') or message.startswith('1000'):
            # Обработка выбора суммы вывода
            try:
                amount = int(message.split()[0]) if ' ' in message else int(message)
                if amount in [50, 100, 250, 500, 1000]:
                    self.process_withdrawal(user_id, amount)
                else:
                    self.send_message(
                        user_id,
                        "❌ Неверная сумма. Выберите из предложенных: 50, 100, 250, 500, 1000",
                        get_withdrawal_keyboard()
                    )
            except:
                pass
        
        else:
            self.send_message(
                user_id,
                "❓ Неизвестная команда\n\n"
                "Напишите 'Меню' для просмотра доступных действий",
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
