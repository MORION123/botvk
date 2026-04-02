import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('VK_TOKEN')
GROUP_ID = 237271112

if not TOKEN:
    logger.error("Нет токена!")
    exit(1)

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

logger.info("Бот запущен. Ожидание сообщений...")

for event in longpoll.listen():
    if event.type == VkBotEventType.MESSAGE_NEW:
        msg = event.obj.message
        peer_id = msg['peer_id']
        text = msg.get('text', '')
        logger.info(f"Сообщение из {peer_id}: {text}")
        
        # Отвечаем на любое сообщение в беседах 2000000003 и 2000000206
        if peer_id in [2000000003, 2000000206]:
            vk.messages.send(
                peer_id=peer_id,
                message=f"Бот получил: {text[:100]}",
                random_id=0
            )
            logger.info("Ответ отправлен")
