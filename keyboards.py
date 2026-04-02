from vk_api.keyboard import VkKeyboard, VkKeyboardColor

def get_main_keyboard():
    """Главная клавиатура"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📋 Мои задания', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('➕ Создать задание', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('👤 Мой аккаунт', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('🔍 Найти задания', color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button('⭐ Купить VIP', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('💰 Вывод баллов', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('🏆 Топ пользователей', color=VkKeyboardColor.SECONDARY)
    keyboard.add_button('❓ Помощь', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_task_type_keyboard():
    """Клавиатура выбора типа задания"""
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('🔄 Репост', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('❤️ Лайк', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📢 Подписка', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('💬 Комментарий', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('⬅ Отмена', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_confirmation_keyboard():
    """Клавиатура подтверждения"""
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('✅ Подтвердить', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('❌ Отменить', color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_back_keyboard():
    """Клавиатура с кнопкой назад"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('⬅ Назад в меню', color=VkKeyboardColor.PRIMARY)
    return keyboard

def get_admin_keyboard():
    """Админская клавиатура"""
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button('📊 Статистика', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('💳 Заявки на вывод', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('📢 Рассылка', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('⬅ Назад', color=VkKeyboardColor.SECONDARY)
    return keyboard

def get_withdrawal_keyboard():
    """Клавиатура вывода баллов"""
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button('50 💎', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('100 💎', color=VkKeyboardColor.PRIMARY)
    keyboard.add_button('250 💎', color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button('500 💎', color=VkKeyboardColor.POSITIVE)
    keyboard.add_button('1000 💎', color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button('⬅ Назад', color=VkKeyboardColor.NEGATIVE)
    return keyboard
