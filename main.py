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
        self.recall_tasks = []
        self.sent_messages = {}  # 存储已发送的消息
        logger.info(f"自动撤回插件已加载，撤回时间: {self.conf['recall_time']}秒")

    def _remove_task(self, task: asyncio.Task):
        """移除已完成的任务"""
        try:
            self.recall_tasks.remove(task)
        except ValueError:
            pass

    async def _recall_msg(self, client, message_id: int):
        """撤回消息"""
        recall_time = self.conf["recall_time"]
        logger.info(f"等待 {recall_time} 秒后撤回消息 {message_id}")
        
        await asyncio.sleep(recall_time)
        try:
            if message_id:
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

    @filter.after_message_sent()
    async def on_all_messages_sent(self, event: AstrMessageEvent):
        """监听所有消息发送后的事件 - 包括LLM和其他插件的消息"""
        try:
            # 检查是否启用撤回
            if not self._should_enable_recall(event):
                return
                
            # 只处理QQ平台
            if not isinstance(event, AiocqhttpMessageEvent):
                return

            # 获取配置中的撤回时间
            recall_time = self.conf["recall_time"]
            logger.info(f"🔧 配置撤回时间: {recall_time}秒 - 准备撤回所有机器人消息")

            client = event.bot
            
            # 关键：我们需要获取最后一条机器人发送的消息ID
            # 由于after_message_sent触发时消息已经发送，我们需要其他方式获取消息ID
            
            # 方法1: 尝试从事件中获取消息ID
            message_id = self._try_get_message_id(event)
            
            if message_id:
                task = asyncio.create_task(self._recall_msg(client, message_id))
                task.add_done_callback(self._remove_task)
                self.recall_tasks.append(task)
                logger.info(f"✅ 已安排所有消息在 {recall_time} 秒后撤回，消息ID: {message_id}")
            else:
                logger.warning("无法获取消息ID，撤回失败")
            
        except Exception as e:
            logger.error(f"撤回处理失败: {e}")

    def _try_get_message_id(self, event: AstrMessageEvent) -> int:
        """尝试获取消息ID"""
        try:
            # 方法1: 尝试从事件属性获取
            if hasattr(event, 'message_id') and event.message_id:
                return int(event.message_id)
                
            # 方法2: 对于AiocqhttpMessageEvent，尝试其他方式
            if isinstance(event, AiocqhttpMessageEvent):
                # 尝试从原始事件获取
                if hasattr(event, '_raw_event') and hasattr(event._raw_event, 'message_id'):
                    return int(event._raw_event.message_id)
                    
            # 方法3: 使用时间戳生成（最后的手段）
            # 注意：这种方法可能不可靠
            fake_id = hash(f"recall_{event.unified_msg_origin}_{event.timestamp}")
            logger.warning(f"使用生成的消息ID: {fake_id}，可能无法正确撤回")
            return fake_id
            
        except Exception as e:
            logger.error(f"获取消息ID失败: {e}")
            return 0

    # 备选方案：使用on_decorating_result + 重新发送消息
    @filter.on_decorating_result(priority=1)  # 使用较低优先级，不干扰其他插件
    async def on_decorating_all_messages(self, event: AstrMessageEvent):
        """装饰所有消息（包括LLM和其他插件）"""
        try:
            # 检查是否启用撤回
            if not self._should_enable_recall(event):
                return
                
            if not isinstance(event, AiocqhttpMessageEvent):
                return

            recall_time = self.conf["recall_time"]
            logger.info(f"🎯 拦截所有消息，{recall_time}秒后撤回")

            # 获取原始消息链
            original_chain = event.get_result().chain.copy()
            
            # 清空原消息链，阻止自动发送
            event.get_result().chain.clear()
            
            # 重新发送消息并安排撤回
            await self._resend_and_recall(event, original_chain, recall_time)
            
        except Exception as e:
            logger.error(f"消息装饰处理失败: {e}")

    async def _resend_and_recall(self, event: AstrMessageEvent, chain: list, recall_time: int):
        """重新发送消息并安排撤回"""
        try:
            # 转换为OneBot消息格式
            obmsg = await event._parse_onebot_json(MessageChain(chain=chain))
            client = event.bot

            # 发送消息并获取消息ID
            send_result = None
            if group_id := event.get_group_id():
                send_result = await client.send_group_msg(
                    group_id=int(group_id), message=obmsg
                )
            elif user_id := event.get_sender_id():
                send_result = await client.send_private_msg(
                    user_id=int(user_id), message=obmsg
                )

            # 启动撤回任务
            if send_result and (message_id := send_result.get("message_id")):
                task = asyncio.create_task(self._recall_msg(client, int(message_id)))
                task.add_done_callback(self._remove_task)
                self.recall_tasks.append(task)
                logger.info(f"✅ 已重新发送并安排 {recall_time} 秒后撤回，消息ID: {message_id}")
            else:
                logger.error("重新发送消息失败，无法获取消息ID")
                
        except Exception as e:
            logger.error(f"重新发送消息失败: {e}")

    # 测试命令 - 验证所有消息撤回
    @filter.command("test_all_recall")
    async def test_all_recall_command(self, event: AstrMessageEvent):
        """测试所有消息撤回功能"""
        recall_time = self.conf["recall_time"]
        yield event.plain_result(f"🧪 测试所有消息撤回，{recall_time}秒后此消息将会撤回...")

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
            task.cancel()
        await asyncio.gather(*self.recall_tasks, return_exceptions=True)
        self.recall_tasks.clear()
        logger.info("自动撤回插件已卸载")