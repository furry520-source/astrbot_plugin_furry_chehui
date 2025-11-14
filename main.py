import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@register(
    "astrbot_plugin_self_recall",
    "YourName", 
    "机器人定时撤回自己消息的插件",
    "1.0.0",
    "https://github.com/yourname/astrbot_plugin_self_recall",
)
class SelfRecallPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.recall_tasks = []
        self.pending_recall = {}  # 临时存储等待撤回的消息

    def _remove_task(self, task: asyncio.Task):
        """移除已完成的任务"""
        try:
            self.recall_tasks.remove(task)
        except ValueError:
            pass

    async def _recall_message(self, platform_type: str, unified_msg_origin: str, message_id: int, recall_time: int):
        """撤回消息的核心方法"""
        try:
            # 等待指定时间
            await asyncio.sleep(recall_time)
            
            if platform_type == "aiocqhttp":
                # QQ平台撤回逻辑
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_adapter import AiocqhttpAdapter
                platform = self.context.get_platform("aiocqhttp")
                if platform and isinstance(platform, AiocqhttpAdapter):
                    try:
                        await platform.get_client().delete_msg(message_id=message_id)
                        logger.info(f"✅ 已自动撤回消息: {message_id}")
                    except Exception as e:
                        logger.error(f"撤回消息失败: {e}")
            else:
                logger.info(f"平台 {platform_type} 到达撤回时间，消息ID: {message_id}")
                
        except Exception as e:
            logger.error(f"撤回任务执行失败: {e}")
        finally:
            # 清理临时存储
            if unified_msg_origin in self.pending_recall:
                del self.pending_recall[unified_msg_origin]
            # 任务完成后从列表中移除
            self._remove_task(asyncio.current_task())

    def _is_private_chat(self, event: AstrMessageEvent) -> bool:
        """判断是否是私聊"""
        return not event.get_group_id()

    def _is_bot_admin_in_group(self, event: AstrMessageEvent) -> bool:
        """判断机器人在群内是否是管理员"""
        try:
            # 对于QQ平台，检查机器人是否是群管理员
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                    AiocqhttpMessageEvent,
                )
                if isinstance(event, AiocqhttpMessageEvent):
                    # 这里需要根据实际平台API获取机器人身份
                    # 简化实现：假设机器人有撤回权限就是管理员
                    return True
            return False
        except Exception:
            return False

    def _should_enable_recall(self, event: AstrMessageEvent) -> bool:
        """判断是否应该启用撤回"""
        if self._is_private_chat(event):
            # 私聊：检查私聊开关
            return self.config.get("enable_private_recall", True)
        else:
            # 群聊：检查群聊开关和白名单
            group_id = event.get_group_id()
            if not self.config.get("enable_group_recall", True):
                return False
                
            group_whitelist = self.config.get("group_whitelist", [])
            if group_whitelist and str(group_id) not in group_whitelist:
                return False
                
            return True

    def _get_recall_time_for_bot(self, event: AstrMessageEvent) -> int:
        """根据机器人身份获取撤回时间"""
        if self._is_private_chat(event):
            return self.config.get("private_recall_time", 20)
        else:
            if self._is_bot_admin_in_group(event):
                # 机器人是管理员，使用管理员撤回时间
                return self.config.get("admin_recall_time", 60)
            else:
                # 机器人是普通成员，使用成员撤回时间
                return self.config.get("member_recall_time", 30)

    @filter.command("recall")
    async def set_recall_time(self, event: AstrMessageEvent, time: int = None):
        """设置临时撤回时间"""
        if not self._should_enable_recall(event):
            if self._is_private_chat(event):
                yield event.plain_result("私聊撤回功能未启用")
            else:
                yield event.plain_result("本群未启用撤回功能")
            return
        
        if time is None:
            # 显示当前设置
            default_time = self._get_recall_time_for_bot(event)
            bot_role = "管理员" if not self._is_private_chat(event) and self._is_bot_admin_in_group(event) else "成员"
            
            chat_type = "私聊" if self._is_private_chat(event) else "群聊"
            status_msg = f"{chat_type}默认撤回时间: {default_time}秒\n"
            status_msg += f"机器人身份: {bot_role}\n"
            status_msg += "使用 /recall [时间] 设置临时撤回时间"
            
            yield event.plain_result(status_msg)
            return
        
        if time <= 0:
            yield event.plain_result("撤回时间必须大于0秒")
            return
            
        max_time = self.config.get("max_recall_time", 600)
        if time > max_time:
            yield event.plain_result(f"撤回时间不能超过{max_time}秒")
            return
        
        # 存储到临时配置中
        session_key = event.unified_msg_origin
        self.pending_recall[session_key] = time
        
        yield event.plain_result(f"✅ 已设置{time}秒后撤回下一条消息")

    @filter.command("recall_status")
    async def recall_status_command(self, event: AstrMessageEvent):
        """查看撤回状态"""
        if not self._should_enable_recall(event):
            if self._is_private_chat(event):
                yield event.plain_result("私聊撤回功能未启用")
            else:
                yield event.plain_result("本群未启用撤回功能")
            return
            
        group_id = event.get_group_id()
        is_private = self._is_private_chat(event)
        is_bot_admin = not is_private and self._is_bot_admin_in_group(event)
        
        # 基本状态
        private_enabled = self.config.get("enable_private_recall", True)
        private_time = self.config.get("private_recall_time", 20)
        group_enabled = self.config.get("enable_group_recall", True)
        admin_time = self.config.get("admin_recall_time", 60)
        member_time = self.config.get("member_recall_time", 30)
        
        status_msg = f"🤖 机器人身份: {'管理员' if is_bot_admin else '成员'}\n"
        status_msg += f"💬 私聊撤回: {'✅已启用' if private_enabled else '❌已禁用'} ({private_time}秒)\n"
        status_msg += f"👥 群聊撤回: {'✅已启用' if group_enabled else '❌已禁用'}\n"
        
        if not is_private:
            status_msg += f"⚡ 管理员撤回: {admin_time}秒\n"
            status_msg += f"👤 成员撤回: {member_time}秒\n"
        
        # 群聊白名单信息
        if group_enabled and not is_private:
            group_whitelist = self.config.get("group_whitelist", [])
            if group_whitelist:
                status_msg += f"📋 白名单群聊: {len(group_whitelist)}个\n"
                if str(group_id) in group_whitelist:
                    status_msg += f"✅ 本群在白名单中\n"
                else:
                    status_msg += f"❌ 本群不在白名单中\n"
            else:
                status_msg += "📋 白名单群聊: 所有群聊\n"
        
        # 当前会话信息
        current_time = self._get_recall_time_for_bot(event)
        if is_private:
            status_msg += f"📍 当前会话: 私聊 (默认{current_time}秒后撤回)"
        else:
            status_msg += f"📍 当前会话: 群聊 {group_id} (默认{current_time}秒后撤回)"
            
        # 临时设置信息
        session_key = event.unified_msg_origin
        if session_key in self.pending_recall:
            status_msg += f"\n🎯 下次消息撤回: {self.pending_recall[session_key]}秒后"
            
        yield event.plain_result(status_msg)

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent):
        """消息发送后处理撤回逻辑 - 普通消息"""
        await self._handle_message_recall(event, "普通消息")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        """LLM响应完成后处理撤回逻辑"""
        # LLM响应完成后也会触发消息发送，我们在这里也处理撤回
        logger.info("检测到LLM响应完成，准备处理撤回")
        # 注意：这里不能直接处理，因为消息可能还没有真正发送

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """消息装饰阶段处理撤回逻辑 - 包括LLM消息"""
        # 这个钩子在消息发送前触发，适用于所有类型的消息
        logger.info("检测到消息装饰阶段，准备处理撤回")

    async def _handle_message_recall(self, event: AstrMessageEvent, message_type: str):
        """统一处理消息撤回"""
        try:
            # 检查是否启用撤回
            if not self._should_enable_recall(event):
                return
                
            # 获取会话key
            session_key = event.unified_msg_origin
            is_private = self._is_private_chat(event)
            is_bot_admin = not is_private and self._is_bot_admin_in_group(event)
            
            # 确定撤回时间
            recall_time = None
            
            # 1. 检查是否有临时设置的撤回时间
            if session_key in self.pending_recall:
                recall_time = self.pending_recall[session_key]
                # 使用后清除临时设置
                del self.pending_recall[session_key]
                logger.info(f"使用临时设置的撤回时间: {recall_time}秒")
            
            # 2. 使用默认撤回时间（根据机器人身份）
            else:
                recall_time = self._get_recall_time_for_bot(event)
                logger.info(f"使用默认撤回时间: {recall_time}秒")
            
            if recall_time and recall_time > 0:
                # 获取消息ID并启动撤回任务
                message_id = await self._get_real_message_id(event)
                
                if message_id:
                    platform_type = event.get_platform_name()
                    task = asyncio.create_task(
                        self._recall_message(platform_type, session_key, message_id, recall_time)
                    )
                    task.add_done_callback(self._remove_task)
                    self.recall_tasks.append(task)
                    
                    bot_role = "管理员" if is_bot_admin else "成员"
                    chat_type = "私聊" if is_private else "群聊"
                    logger.info(f"🤖{bot_role} {message_type}{chat_type}消息已安排{recall_time}秒后撤回，消息ID: {message_id}")
                else:
                    logger.warning(f"无法获取{message_type}消息ID，撤回失败")
                
        except Exception as e:
            logger.error(f"{message_type}消息撤回处理失败: {e}")

    async def _get_real_message_id(self, event: AstrMessageEvent) -> int:
        """获取真实的消息ID"""
        try:
            # 对于QQ平台
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                    AiocqhttpMessageEvent,
                )
                if isinstance(event, AiocqhttpMessageEvent):
                    # 尝试从事件中获取消息ID
                    # 注意：LLM消息可能需要特殊处理
                    
                    # 方法1：尝试从原始消息中获取
                    if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'message_id'):
                        return int(event.message_obj.message_id)
                    
                    # 方法2：尝试从事件属性中获取
                    if hasattr(event, 'message_id'):
                        return int(event.message_id)
                    
                    # 方法3：使用时间戳生成临时ID（最后的手段）
                    logger.warning("使用时间戳生成临时消息ID，可能无法正确撤回")
                    return hash(f"{event.unified_msg_origin}_{event.timestamp}")
                    
        except Exception as e:
            logger.error(f"获取真实消息ID失败: {e}")
        
        # 如果所有方法都失败，返回0表示无法撤回
        return 0

    # 添加一个测试命令来验证撤回功能
    @filter.command("test_recall")
    async def test_recall_command(self, event: AstrMessageEvent, time: int = 10):
        """测试撤回功能"""
        if time <= 0 or time > 600:
            yield event.plain_result("测试时间必须在1-600秒之间")
            return
            
        # 设置临时撤回时间
        session_key = event.unified_msg_origin
        self.pending_recall[session_key] = time
        
        yield event.plain_result(f"🧪 测试消息，{time}秒后将会撤回...")
        logger.info(f"测试消息已发送，将在{time}秒后撤回")

    async def terminate(self):
        """插件卸载时取消所有撤回任务"""
        for task in self.recall_tasks:
            if not task.done():
                task.cancel()
                
        if self.recall_tasks:
            await asyncio.gather(*self.recall_tasks, return_exceptions=True)
            self.recall_tasks.clear()
            
        self.pending_recall.clear()
        logger.info("自动撤回插件已卸载")
