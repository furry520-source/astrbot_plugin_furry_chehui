import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


@register(
    "astrbot_plugin_furry_chehui",
    "芝士雪豹", 
    "机器人定时撤回自己消息的插件",
    "1.0.0",
    "https://github.com/furry520-source/astrbot_plugin_furry_chehui",
)
class SelfRecallPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.conf = config
        self.recall_tasks = set()
        logger.info(f"自动撤回插件已加载，撤回时间: {self.conf['recall_time']}秒")

    def _remove_task(self, task: asyncio.Task):
        """移除已完成的任务"""
        self.recall_tasks.discard(task)

    async def _recall_msg(self, client, message_id: int):
        """撤回消息 - 参考其他插件的写法"""
        recall_time = self.conf["recall_time"]
        logger.info(f"⏰ 等待 {recall_time} 秒后撤回消息 {message_id}")
        
        await asyncio.sleep(recall_time)
        try:
            if message_id and message_id != 0:
                await client.delete_msg(message_id=message_id)
                logger.info(f"✅ 已自动撤回消息: {message_id}")
        except Exception as e:
            logger.error(f"撤回消息失败: {e}")

    def _should_enable_recall(self, event: AstrMessageEvent) -> bool:
        """判断是否应该启用撤回"""
        # 私聊检查
        if not event.get_group_id():
            return self.conf.get("enable_private_recall", True)
        
        # 群聊检查白名单
        group_id = event.get_group_id()
        group_whitelist = self.conf.get("group_whitelist", [])
        if group_whitelist and str(group_id) not in group_whitelist:
            return False
            
        return self.conf.get("enable_group_recall", True)

    @filter.on_decorating_result(priority=999)
    async def intercept_and_recall(self, event: AstrMessageEvent):
        """拦截消息并安排撤回 - 参考其他插件的模式"""
        try:
            # 检查是否启用撤回
            if not self._should_enable_recall(event):
                return
                
            # 只处理QQ平台
            if not isinstance(event, AiocqhttpMessageEvent):
                return

            # 获取配置中的撤回时间
            recall_time = self.conf["recall_time"]
            logger.info(f"🎯 拦截到机器人消息，{recall_time}秒后撤回")

            # 获取原始消息链
            result = event.get_result()
            if not result or not result.chain:
                logger.warning("消息链为空，跳过处理")
                return

            # 保存原始消息链
            original_chain = result.chain.copy()
            
            # 清空原消息链，阻止框架自动发送
            result.chain.clear()
            
            # 使用 event.send() 发送消息并获取发送结果
            send_result = None
            if group_id := event.get_group_id():
                # 使用 event.send() 而不是直接调用 client
                from astrbot.core.message.message_event_result import MessageChain
                message_chain = MessageChain(chain=original_chain)
                send_result = await event.send(message_chain)
            elif user_id := event.get_sender_id():
                from astrbot.core.message.message_event_result import MessageChain
                message_chain = MessageChain(chain=original_chain)
                send_result = await event.send(message_chain)

            # 从发送结果中获取消息ID
            if send_result and hasattr(send_result, 'message_id'):
                message_id = send_result.message_id
                logger.info(f"📤 发送成功，获取到消息ID: {message_id}")
                
                # 启动撤回任务
                task = asyncio.create_task(self._recall_msg(event.bot, int(message_id)))
                task.add_done_callback(self._remove_task)
                self.recall_tasks.add(task)
                logger.info(f"✅ 已安排消息在 {recall_time} 秒后撤回")
            else:
                logger.error("❌ 发送消息失败，无法获取消息ID")
                # 备选方案：直接使用 event.send 但不获取消息ID
                from astrbot.core.message.message_event_result import MessageChain
                message_chain = MessageChain(chain=original_chain)
                await event.send(message_chain)
                logger.warning("使用备选方案发送消息，但无法撤回")
            
        except Exception as e:
            logger.error(f"消息拦截处理失败: {e}")

    # 备选方案：使用消息历史记录获取消息ID
    async def _get_recent_bot_messages(self, event: AiocqhttpMessageEvent, count: int = 5):
        """获取最近的机器人消息 - 参考其他插件的模式"""
        try:
            payloads = {
                "group_id": int(event.get_group_id()),
                "count": count,
            }
            result = await event.bot.api.call_action("get_group_msg_history", **payloads)
            messages = result.get("messages", [])
            
            # 过滤出机器人发送的消息
            bot_messages = [
                msg for msg in messages 
                if str(msg.get("sender", {}).get("user_id", "")) == event.get_self_id()
            ]
            
            return bot_messages
        except Exception as e:
            logger.error(f"获取消息历史失败: {e}")
            return []

    # 测试命令
    @filter.command("test_recall")
    async def test_recall_command(self, event: AstrMessageEvent):
        """测试撤回功能"""
        recall_time = self.conf["recall_time"]
        yield event.plain_result(f"🧪 测试消息，{recall_time}秒后此消息将会撤回...")

    @filter.command("recall_config")
    async def recall_config_command(self, event: AstrMessageEvent):
        """查看当前配置"""
        config_info = "📋 当前撤回配置:\n"
        config_info += f"撤回时间: {self.conf['recall_time']}秒\n"
        config_info += f"私聊启用: {self.conf.get('enable_private_recall', True)}\n"
        config_info += f"群聊启用: {self.conf.get('enable_group_recall', True)}\n"
        
        group_whitelist = self.conf.get("group_whitelist", [])
        if group_whitelist:
            config_info += f"白名单群: {len(group_whitelist)}个\n"
        else:
            config_info += "白名单群: 所有群聊\n"
            
        yield event.plain_result(config_info)

    async def terminate(self):
        """插件卸载时取消所有撤回任务"""
        for task in self.recall_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.recall_tasks, return_exceptions=True)
        self.recall_tasks.clear()
        logger.info("自动撤回插件已卸载")