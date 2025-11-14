import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


@register(
    "astrbot_plugin_furry_chehui",
    "芝士雪豹", 
    "机器人定时撤回所有自己消息的插件",
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
        """撤回消息"""
        recall_time = self.conf["recall_time"]
        logger.info(f"⏰ 等待 {recall_time} 秒后撤回消息 {message_id}")
        
        await asyncio.sleep(recall_time)
        try:
            if message_id and message_id != 0:
                await client.delete_msg(message_id=message_id)
                logger.info(f"✅ 已自动撤回消息: {message_id}")
            else:
                logger.warning("消息ID无效，跳过撤回")
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
    async def intercept_all_bot_messages(self, event: AstrMessageEvent):
        """拦截所有机器人消息，重新发送并安排撤回"""
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
            
            # 重新发送消息并安排撤回
            await self._resend_and_schedule_recall(event, original_chain, recall_time)
            
        except Exception as e:
            logger.error(f"消息拦截处理失败: {e}")

    async def _resend_and_schedule_recall(self, event: AstrMessageEvent, chain: list, recall_time: int):
        """重新发送消息并安排撤回任务"""
        try:
            client = event.bot

            # 转换为OneBot消息格式
            obmsg = await event._parse_onebot_json(MessageChain(chain=chain))
            
            # 发送消息并获取真实的消息ID
            send_result = None
            if group_id := event.get_group_id():
                send_result = await client.send_group_msg(
                    group_id=int(group_id), 
                    message=obmsg
                )
                logger.info(f"📤 已发送群消息到群 {group_id}")
            elif user_id := event.get_sender_id():
                send_result = await client.send_private_msg(
                    user_id=int(user_id),
                    message=obmsg
                )
                logger.info(f"📤 已发送私聊消息给用户 {user_id}")

            # 启动撤回任务
            if send_result and (message_id := send_result.get("message_id")):
                task = asyncio.create_task(self._recall_msg(client, int(message_id)))
                task.add_done_callback(self._remove_task)
                self.recall_tasks.add(task)
                logger.info(f"✅ 已安排消息在 {recall_time} 秒后撤回，消息ID: {message_id}")
            else:
                logger.error("❌ 重新发送消息失败，无法获取消息ID")
                if send_result:
                    logger.error(f"发送结果: {send_result}")
                
        except Exception as e:
            logger.error(f"重新发送消息失败: {e}")

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