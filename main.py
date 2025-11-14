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
    "机器人定时撤回所有自己消息的插件",
    "1.0.0",
    "https://github.com/furry520-source/astrbot_plugin_furry_chehui",
)
class SelfRecallPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.conf = config
        self.recall_tasks = []
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
            logger.info(f"🔧 配置撤回时间: {recall_time}秒 - 准备撤回机器人消息")

            client = event.bot
            
            # 获取消息ID
            message_id = self._try_get_message_id(event)
            
            if message_id and message_id != 0:
                task = asyncio.create_task(self._recall_msg(client, message_id))
                task.add_done_callback(self._remove_task)
                self.recall_tasks.append(task)
                logger.info(f"✅ 已安排消息在 {recall_time} 秒后撤回，消息ID: {message_id}")
            else:
                logger.error("❌ 无法获取有效的消息ID，撤回任务已放弃")
            
        except Exception as e:
            logger.error(f"撤回处理失败: {e}")

    def _try_get_message_id(self, event: AstrMessageEvent) -> int:
        """尝试获取消息ID - 移除无效的哈希生成回退"""
        try:
            # 方法1: 尝试从事件属性获取
            if hasattr(event, 'message_id') and event.message_id:
                message_id = int(event.message_id)
                logger.info(f"从 event.message_id 获取消息ID: {message_id}")
                return message_id
                
            # 方法2: 对于AiocqhttpMessageEvent，尝试从原始事件获取
            if isinstance(event, AiocqhttpMessageEvent):
                # 尝试从原始事件获取
                if hasattr(event, '_raw_event') and event._raw_event:
                    raw_event = event._raw_event
                    if hasattr(raw_event, 'message_id') and raw_event.message_id:
                        message_id = int(raw_event.message_id)
                        logger.info(f"从 _raw_event.message_id 获取消息ID: {message_id}")
                        return message_id
                    # 尝试从原始数据字典获取
                    if hasattr(raw_event, 'get') and callable(raw_event.get):
                        message_id = int(raw_event.get('message_id', 0))
                        if message_id:
                            logger.info(f"从 _raw_event.get('message_id') 获取消息ID: {message_id}")
                            return message_id
                
                # 方法3: 尝试访问可能的消息ID方法
                if hasattr(event, 'get_message_id') and callable(event.get_message_id):
                    message_id = int(event.get_message_id())
                    if message_id:
                        logger.info(f"从 get_message_id() 获取消息ID: {message_id}")
                        return message_id
                    
            # 如果所有方法都失败，返回0表示无法获取有效消息ID
            logger.warning("所有消息ID获取方法都失败了")
            return 0
            
        except (ValueError, TypeError) as e:
            logger.error(f"消息ID格式转换失败: {e}")
            return 0
        except Exception as e:
            logger.error(f"获取消息ID过程中发生未知错误: {e}")
            return 0

    # 测试命令 - 验证所有消息撤回
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