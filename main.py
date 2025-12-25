from astrbot.api.message_components import *
from astrbot.api.message_components import File
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.all import *

import httpx
import json
import asyncio
import os
import time

import jmcomic
# 导入此模块，需要先安装（pip install jmcomic -i https://pypi.org/project -U）

@register("JMdownloader", "FateTrial", "一个下载JM本子的插件,修复了不能下载仅登录查看的本子请自行配置cookies", "1.0.6")
class JMPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.downloading = set() # 存储正在下载的ID
        
    # 将同步下载任务包装成异步函数
    async def download_comic_async(self, album_id, option):
        if album_id in self.downloading:
            return False, "该本子正在下载中，请稍后再试"
            
        self.downloading.add(album_id)
        try:
            # 将同步下载操作放到线程池中执行，避免阻塞事件循环
            await asyncio.to_thread(jmcomic.download_album, album_id, option)
            return True, None
        except Exception as e:
            return False, f"下载出错: {str(e)}"
        finally:
            self.downloading.discard(album_id)

    # 获取详情的辅助函数（同步）
    def get_album_detail(self, album_id, option):
        # 使用 option.build_jm_client() 自动构建客户端
        client = option.build_jm_client()
        return client.get_album_detail(album_id)

    # 格式化本子信息的辅助函数
    def format_info(self, album):
        # 处理标签，将列表转换为逗号分隔的字符串
        tags_list = getattr(album, 'tags', [])
        tags_str = ", ".join(tags_list) if tags_list else "无"
        
        # 获取页数
        total_pages = getattr(album, 'page_count', 0)
        if total_pages == 0 and hasattr(album, 'episode_list'):
             total_pages = sum([len(ep) for ep in album])

        # 美化排版
        info_msg = (
            f"📖 标题: {album.title}\n"
            f"🆔 ID: {album.album_id}\n"
            f"✍️ 作者: {album.author}\n"
            f"📚 章节: {len(album)}\n"
            f"📄 页数: {total_pages}\n"
            f"🏷️ 关键词: {tags_str}"
        )
        return info_msg

    # 指令：单独获取本子详情
    @filter.command("jm")
    async def jm_info(self, event: AstrMessageEvent):
        path = os.path.abspath(os.path.dirname(__file__))
        messages = event.get_messages()
        if not messages:
            yield event.plain_result("请输入本子ID")
            return
            
        message_text = messages[0].text
        parts = message_text.split()
        if len(parts) < 2:
            yield event.plain_result("请输入本子ID")
            return
            
        jm_id = parts[1]
        
        yield event.plain_result(f"正在查询本子 {jm_id} 信息...")
        
        try:
            # 创建配置
            option = jmcomic.create_option_by_file(path + "/option.yml")
            # 异步获取详情
            album = await asyncio.to_thread(self.get_album_detail, jm_id, option)
            
            # 使用统一格式化函数
            info_msg = self.format_info(album)
            
            yield event.plain_result(info_msg)
            
        except Exception as e:
            yield event.plain_result(f"获取信息失败: {str(e)}\n请检查ID是否正确或Cookies是否过期。")

    # 指令：下载本子
    @filter.command("jm下载")
    async def JMid(self, event: AstrMessageEvent):
        path = os.path.abspath(os.path.dirname(__file__))
        messages = event.get_messages()
        if not messages:
            yield event.plain_result("请输入要下载的本子ID,如果有多页，请输入第一页的ID")
            return
        # 获取原始消息文本
        message_text = messages[0].text  
        parts = message_text.split()  
        if len(parts) < 2:  
            yield event.plain_result("请输入要下载的本子ID,如果有多页，请输入第一页的ID")
            return
            
        tokens = parts[1]  
        pdf_path = f"{path}/pdf/{tokens}.pdf"
        
        # 检查文件是否已存在
        if os.path.exists(pdf_path):
            yield event.plain_result(f"本子 {tokens} 已存在，直接发送")
            yield event.chain_result(
                [File(name=f"{tokens}.pdf", file=pdf_path)]
            )
            return
            
        # 1. 初始化配置并获取本子信息
        option = None
        try:
            option = jmcomic.create_option_by_file(path + "/option.yml")
            
            # 在下载前先获取详情
            album = await asyncio.to_thread(self.get_album_detail, tokens, option)
            
            # 使用统一格式化函数 + 下载提示
            info_msg = self.format_info(album)
            final_msg = f"{info_msg}\n\n⬇️ 正在开始下载，请稍候..."
            
            yield event.plain_result(final_msg)
            
        except Exception as e:
            yield event.plain_result(f"获取本子信息失败 ({str(e)})，尝试直接下载...")
        
        # 2. 开始下载
        if option is None:
            try:
                option = jmcomic.create_option_by_file(path + "/option.yml")
            except Exception as e:
                yield event.plain_result(f"配置加载失败: {str(e)}")
                return

        success, error_msg = await self.download_comic_async(tokens, option)
        
        if not success:
            yield event.plain_result(error_msg)
            return
            
        # 3. 检查文件并发送
        if os.path.exists(pdf_path):
            yield event.plain_result(f"✅ 本子 {tokens} 下载完成")
            yield event.chain_result(
                [File(name=f"{tokens}.pdf", file=pdf_path)]
            )
        else:
            yield event.plain_result(f"⚠️ 下载完成，但未找到生成的PDF文件，请检查下载路径")

    @filter.command("jm_help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = """JM下载插件指令说明：
        
/jm [ID] - 获取本子详细信息
/jm下载 [ID] - 下载JM漫画 (如果有多页，请输入第一页的ID)
/jm_help - 显示本帮助信息

Powered by FateTrial
"""
        yield event.plain_result(help_text)