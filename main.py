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
                        logger.info(f"已自动撤回消息: {message_id}")
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

    def _check_permission(self, event: AstrMessageEvent) -> bool:
        """检查权限"""
        if not self.config.get("admin_only", True):
            return True
            
        # 检查是否是管理员
        return event.is_admin()

    def _is_private_chat(self, event: AstrMessageEvent) -> bool:
        """判断是否是私聊"""
        return not event.get_group_id()

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

    def _get_default_recall_time(self, event: AstrMessageEvent) -> int:
        """获取默认撤回时间"""
        if self._is_private_chat(event):
            return self.config.get("private_recall_time", 20)
        else:
            return self.config.get("group_recall_time", 30)

    @filter.command("recall")
    async def set_recall_time(self, event: AstrMessageEvent, time: int = None):
        """设置消息撤回时间"""
        if not self._check_permission(event):
            yield event.plain_result("权限不足，只有管理员可以设置撤回时间")
            return
            
        if not self._should_enable_recall(event):
            if self._is_private_chat(event):
                yield event.plain_result("私聊撤回功能未启用")
            else:
                yield event.plain_result("本群未启用撤回功能")
            return
        
        if time is None:
            # 显示当前设置
            default_time = self._get_default_recall_time(event)
            chat_type = "私聊" if self._is_private_chat(event) else "群聊"
            yield event.plain_result(f"{chat_type}默认撤回时间: {default_time}秒\n使用 /recall [时间] 设置临时撤回时间")
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
        
        yield event.plain_result(f"已设置{time}秒后撤回下一条消息，请发送要撤回的消息")

    @filter.command("recall_status")
    async def recall_status_command(self, event: AstrMessageEvent):
        """查看撤回状态"""
        if not self._check_permission(event):
            yield event.plain_result("权限不足")
            return
            
        group_id = event.get_group_id()
        is_private = self._is_private_chat(event)
        
        # 基本状态
        private_enabled = self.config.get("enable_private_recall", True)
        private_time = self.config.get("private_recall_time", 20)
        group_enabled = self.config.get("enable_group_recall", True)
        group_time = self.config.get("group_recall_time", 30)
        
        status_msg = f"私聊撤回: {'✅已启用' if private_enabled else '❌已禁用'} ({private_time}秒)\n"
        status_msg += f"群聊撤回: {'✅已启用' if group_enabled else '❌已禁用'} ({group_time}秒)\n"
        
        # 群聊白名单信息
        if group_enabled:
            group_whitelist = self.config.get("group_whitelist", [])
            if group_whitelist:
                status_msg += f"白名单群聊: {len(group_whitelist)}个\n"
            else:
                status_msg += "白名单群聊: 所有群聊\n"
        
        # 当前会话信息
        if is_private:
            status_msg += f"当前会话: 私聊 (默认{private_time}秒后撤回)"
        else:
            status_msg += f"当前会话: 群聊{group_id} (默认{group_time}秒后撤回)"
            
            # 检查是否在白名单中
            if group_enabled and group_whitelist and str(group_id) not in group_whitelist:
                status_msg += " ❌不在白名单中"
        
        # 临时设置信息
        session_key = event.unified_msg_origin
        if session_key in self.pending_recall:
            status_msg += f"\n下次消息撤回: {self.pending_recall[session_key]}秒后"
            
        yield event.plain_result(status_msg)

    @filter.command("recall_on")
    async def recall_on_command(self, event: AstrMessageEvent):
        """启用当前群组的撤回功能（仅限白名单群聊）"""
        if self._is_private_chat(event):
            yield event.plain_result("此命令仅在群聊中可用")
            return
            
        if not self._check_permission(event):
            yield event.plain_result("权限不足")
            return
            
        group_id = event.get_group_id()
        group_whitelist = self.config.get("group_whitelist", [])
        
        if str(group_id) in group_whitelist:
            yield event.plain_result("本群已在白名单中")
            return
            
        # 添加到白名单
        new_whitelist = group_whitelist + [str(group_id)]
        self.config.set("group_whitelist", new_whitelist)
        self.config.save_config()
        
        yield event.plain_result("✅ 已启用本群撤回功能")

    @filter.command("recall_off")
    async def recall_off_command(self, event: AstrMessageEvent):
        """禁用当前群组的撤回功能（从白名单移除）"""
        if self._is_private_chat(event):
            yield event.plain_result("此命令仅在群聊中可用")
            return
            
        if not self._check_permission(event):
            yield event.plain_result("权限不足")
            return
            
        group_id = event.get_group_id()
        group_whitelist = self.config.get("group_whitelist", [])
        
        if str(group_id) not in group_whitelist:
            yield event.plain_result("本群不在白名单中")
            return
            
        # 从白名单移除
        new_whitelist = [gid for gid in group_whitelist if gid != str(group_id)]
        self.config.set("group_whitelist", new_whitelist)
        self.config.save_config()
        
        yield event.plain_result("❌ 已禁用本群撤回功能")

    @filter.after_message_sent()
    async def on_message_sent(self, event: AstrMessageEvent):
        """消息发送后处理撤回逻辑"""
        try:
            # 检查是否启用撤回
            if not self._should_enable_recall(event):
                return
                
            # 获取会话key
            session_key = event.unified_msg_origin
            is_private = self._is_private_chat(event)
            
            # 确定撤回时间
            recall_time = None
            
            # 1. 检查是否有临时设置的撤回时间
            if session_key in self.pending_recall:
                recall_time = self.pending_recall[session_key]
                # 使用后清除临时设置
                del self.pending_recall[session_key]
            
            # 2. 使用默认撤回时间
            else:
                recall_time = self._get_default_recall_time(event)
            
            if recall_time and recall_time > 0:
                # 获取消息ID并启动撤回任务
                message_id = self._get_message_id_from_event(event)
                
                if message_id:
                    platform_type = event.get_platform_name()
                    task = asyncio.create_task(
                        self._recall_message(platform_type, session_key, message_id, recall_time)
                    )
                    task.add_done_callback(self._remove_task)
                    self.recall_tasks.append(task)
                    
                    chat_type = "私聊" if is_private else "群聊"
                    logger.info(f"{chat_type}消息已安排{recall_time}秒后撤回，消息ID: {message_id}")
                
        except Exception as e:
            logger.error(f"消息撤回处理失败: {e}")

    def _get_message_id_from_event(self, event: AstrMessageEvent) -> int:
        """从事件中获取消息ID（需要根据具体平台实现）"""
        # 这里是一个示例实现，实际需要根据平台API调整
        try:
            # 对于QQ平台
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                    AiocqhttpMessageEvent,
                )
                if isinstance(event, AiocqhttpMessageEvent):
                    # 这里需要根据实际API获取消息ID
                    return hash(event.unified_msg_origin + str(event.timestamp))
        except Exception as e:
            logger.error(f"获取消息ID失败: {e}")
        
        return hash(event.unified_msg_origin + str(event.timestamp))

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