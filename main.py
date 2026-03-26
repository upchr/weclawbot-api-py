#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeClawBot-API Python版本
基于微信ClawBot (iLink) 的个人微信消息推送 API 服务

关键实现基于对 @tencent-weixin/openclaw-weixin 插件的逆向学习：
- CDN 上传：AES-128-ECB 加密
- 图片/文件发送：正确的 aes_key 格式和 encrypt_query_param
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid
import base64
import hashlib
import random
from pathlib import Path
from typing import Optional, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from io import BytesIO

import qrcode
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# 默认配置
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_PORT = 26322
CONFIG_PATH = Path("./config/auth.json")

# 媒体类型常量
MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_FILE = 3


class UserConfig:
    """用户配置"""
    def __init__(self, data: dict = None):
        data = data or {}
        self.bot_token: str = data.get("bot_token", "")
        self.bot_id: str = data.get("bot_id", "")
        self.get_updates_buf: str = data.get("get_updates_buf", "")
        self.ilink_user_id: str = data.get("ilink_user_id", "")
        self.context_token: str = data.get("context_token", "")
        self.api_token: str = data.get("api_token", "")
        self.base_url: str = data.get("base_url", DEFAULT_BASE_URL)
        self.cdn_base_url: str = data.get("cdn_base_url", DEFAULT_CDN_BASE_URL)
        # 续期提醒相关
        self.last_message_time: float = data.get("last_message_time", 0)
        self.renewal_notified: bool = data.get("renewal_notified", False)  # 是否已发送续期提醒

    def to_dict(self) -> dict:
        return {
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "get_updates_buf": self.get_updates_buf,
            "ilink_user_id": self.ilink_user_id,
            "context_token": self.context_token,
            "api_token": self.api_token,
            "base_url": self.base_url,
            "cdn_base_url": self.cdn_base_url,
            "last_message_time": self.last_message_time,
            "renewal_notified": self.renewal_notified,
        }


class AppConfig:
    """应用配置"""
    def __init__(self):
        self.bots: Dict[str, UserConfig] = {}
        self.lock = threading.Lock()
        self.active_user: str = ""

    def load(self):
        """加载配置"""
        self.lock.acquire()
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    bots = data.get("bots", {})
                    for bot_id, bot_data in bots.items():
                        self.bots[bot_id] = UserConfig(bot_data)
        except Exception as e:
            print(f"加载配置失败: {e}")
        finally:
            self.lock.release()

    def save(self):
        """保存配置"""
        self.lock.acquire()
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"bots": {bid: bot.to_dict() for bid, bot in self.bots.items()}}
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")
        finally:
            self.lock.release()


# 全局配置
cfg = AppConfig()


def generate_token(n: int = 16) -> str:
    """生成随机token"""
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip('=')


def random_wechat_uin() -> str:
    """生成随机微信UIN"""
    val = random.randint(0, 2**32 - 1)
    return base64.b64encode(str(val).encode()).decode()


def common_headers(token: str = "") -> dict:
    """通用请求头"""
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": random_wechat_uin(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class AESCipher:
    """AES-128-ECB 加密工具"""
    
    @staticmethod
    def generate_key() -> bytes:
        """生成随机 AES 密钥 (16字节)"""
        return os.urandom(16)
    
    @staticmethod
    def encrypt(plaintext: bytes, key: bytes) -> bytes:
        """AES-128-ECB 加密 (PKCS7 padding)"""
        cipher = AES.new(key, AES.MODE_ECB)
        padded = pad(plaintext, AES.block_size)
        return cipher.encrypt(padded)
    
    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes) -> bytes:
        """AES-128-ECB 解密"""
        cipher = AES.new(key, AES.MODE_ECB)
        padded = cipher.decrypt(ciphertext)
        return unpad(padded, AES.block_size)
    
    @staticmethod
    def key_to_hex(key: bytes) -> str:
        """密钥转 hex 字符串"""
        return key.hex()
    
    @staticmethod
    def key_to_base64(key: bytes) -> str:
        """
        微信特殊格式：把 hex 字符串当 ASCII 编码后再 base64
        不是直接 base64 编码原始字节！
        """
        hex_str = key.hex()
        return base64.b64encode(hex_str.encode('ascii')).decode()


def aes_ecb_padded_size(plaintext_size: int) -> int:
    """计算 AES-128-ECB 加密后的大小（PKCS7 padding）"""
    return ((plaintext_size + 16) // 16) * 16


def upload_file_to_cdn(user: UserConfig, file_data: bytes, media_type: int = MEDIA_TYPE_IMAGE, 
                       filename: str = "file") -> Optional[dict]:
    """
    完整的文件上传流程
    
    Args:
        user: 用户配置
        file_data: 原始文件数据
        media_type: 媒体类型 (IMAGE=1, VIDEO=2, FILE=3)
        filename: 文件名
    
    Returns:
        {
            "aeskey": "hex字符串",
            "aes_key": "base64编码",
            "encrypt_query_param": "...",
            "filesize": 加密后大小,
            "rawsize": 原始大小
        }
    """
    # 1. 计算文件信息
    rawsize = len(file_data)
    rawfilemd5 = hashlib.md5(file_data).hexdigest()
    filesize = aes_ecb_padded_size(rawsize)
    
    # 2. 生成 AES 密钥
    aeskey = AESCipher.generate_key()
    aeskey_hex = AESCipher.key_to_hex(aeskey)
    aeskey_base64 = AESCipher.key_to_base64(aeskey)
    
    # 3. 生成文件标识
    filekey = os.urandom(16).hex()
    
    # 4. 获取上传 URL
    req_data = {
        "filekey": filekey,
        "media_type": media_type,
        "to_user_id": user.ilink_user_id,
        "rawsize": rawsize,           # 数字
        "rawfilemd5": rawfilemd5,     # MD5 字符串
        "filesize": filesize,         # 数字
        "thumb_rawsize": 0,
        "thumb_rawfilemd5": "",
        "thumb_filesize": 0,
        "no_need_thumb": True,        # 布尔值
        "aeskey": aeskey_hex,
        "base_info": {"channel_version": "1.0.3"}
    }
    
    try:
        resp = requests.post(
            f"{user.base_url}/ilink/bot/getuploadurl",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=15
        )
        
        data = resp.json()
        
        # 检查错误（ret 不为 0 且存在）
        if data.get("ret") is not None and data.get("ret") != 0:
            print(f"获取上传URL失败: {data}")
            return None
        
        upload_param = data.get("upload_param", "")
        cdn_url = data.get("cdn_url", user.cdn_base_url)
        
        if not upload_param:
            print("响应中没有 upload_param")
            return None
        
    except Exception as e:
        print(f"获取上传URL异常: {e}")
        return None
    
    # 5. AES-128-ECB 加密
    ciphertext = AESCipher.encrypt(file_data, aeskey)
    
    # 6. 上传到 CDN
    # 注意：使用 encrypted_query_param 参数名，不是 upload_param
    cdn_full_url = f"{cdn_url}/upload?encrypted_query_param={upload_param}&filekey={filekey}"
    
    try:
        resp = requests.post(
            cdn_full_url,
            data=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30
        )
        
        if resp.status_code != 200:
            err_msg = resp.headers.get("x-error-message", resp.text)
            print(f"CDN 上传失败: {resp.status_code} - {err_msg}")
            return None
        
        # 7. 获取下载参数 - 必须用 x-encrypted-query-param！
        download_param = resp.headers.get("x-encrypted-query-param")
        if not download_param:
            print("CDN 响应缺少 x-encrypted-query-param")
            return None
        
        print(f"{filename}: CDN 上传成功")
        
    except Exception as e:
        print(f"CDN 上传异常: {e}")
        return None
    
    return {
        "aeskey": aeskey_hex,
        "aes_key": aeskey_base64,
        "encrypt_query_param": download_param,
        "filesize": len(ciphertext),
        "rawsize": rawsize
    }


def send_text_message(user: UserConfig, to: str, text: str, context_token: str = "") -> bool:
    """发送文本消息"""
    req_data = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"weclawbot:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "message_type": 2,  # BOT
            "message_state": 2,  # FINISH
            "context_token": context_token or user.context_token,
            "item_list": [
                {
                    "type": 1,  # TEXT
                    "text_item": {"text": text}
                }
            ]
        },
        "base_info": {"channel_version": "1.0.3"}
    }

    try:
        resp = requests.post(
            f"{user.base_url}/ilink/bot/sendmessage",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=15
        )
        data = resp.json()
        if data.get("ret") is None or data.get("ret") == 0:
            if data.get("errcode", 0) == 0:
                return True
        print(f"发送失败: {data}")
        return False
    except Exception as e:
        print(f"发送消息异常: {e}")
        return False


def send_image_message(user: UserConfig, to: str, upload_info: dict, 
                       context_token: str = "") -> bool:
    """发送图片消息"""
    req_data = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"weclawbot:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "message_type": 2,  # BOT
            "message_state": 2,  # FINISH
            "context_token": context_token or user.context_token,
            "item_list": [
                {
                    "type": 2,  # IMAGE
                    "image_item": {
                        "aeskey": upload_info["aeskey"],
                        "media": {
                            "encrypt_query_param": upload_info["encrypt_query_param"],
                            "aes_key": upload_info["aes_key"]
                        },
                        "mid_size": upload_info["filesize"]
                    }
                }
            ]
        },
        "base_info": {"channel_version": "1.0.3"}
    }

    try:
        resp = requests.post(
            f"{user.base_url}/ilink/bot/sendmessage",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=15
        )
        data = resp.json()
        if data.get("ret") is None or data.get("ret") == 0:
            if data.get("errcode", 0) == 0:
                return True
        print(f"发送图片失败: {data}")
        return False
    except Exception as e:
        print(f"发送图片异常: {e}")
        return False


def send_file_message(user: UserConfig, to: str, upload_info: dict, 
                      filename: str, context_token: str = "") -> bool:
    """发送文件消息"""
    req_data = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"weclawbot:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "message_type": 2,  # BOT
            "message_state": 2,  # FINISH
            "context_token": context_token or user.context_token,
            "item_list": [
                {
                    "type": 4,  # FILE
                    "file_item": {
                        "media": {
                            "encrypt_query_param": upload_info["encrypt_query_param"],
                            "aes_key": upload_info["aes_key"]
                        },
                        "file_name": filename,
                        "len": str(upload_info["rawsize"])
                    }
                }
            ]
        },
        "base_info": {"channel_version": "1.0.3"}
    }

    try:
        resp = requests.post(
            f"{user.base_url}/ilink/bot/sendmessage",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=15
        )
        data = resp.json()
        if data.get("ret") is None or data.get("ret") == 0:
            if data.get("errcode", 0) == 0:
                return True
        print(f"发送文件失败: {data}")
        return False
    except Exception as e:
        print(f"发送文件异常: {e}")
        return False


def send_video_message(user: UserConfig, to: str, upload_info: dict, 
                       context_token: str = "") -> bool:
    """发送视频消息"""
    req_data = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"weclawbot:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "message_type": 2,  # BOT
            "message_state": 2,  # FINISH
            "context_token": context_token or user.context_token,
            "item_list": [
                {
                    "type": 5,  # VIDEO (注意：根据 types.ts，VIDEO=5)
                    "video_item": {
                        "media": {
                            "encrypt_query_param": upload_info["encrypt_query_param"],
                            "aes_key": upload_info["aes_key"]
                        },
                        "video_size": upload_info["filesize"]
                    }
                }
            ]
        },
        "base_info": {"channel_version": "1.0.3"}
    }

    try:
        resp = requests.post(
            f"{user.base_url}/ilink/bot/sendmessage",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=15
        )
        data = resp.json()
        if data.get("ret") is None or data.get("ret") == 0:
            if data.get("errcode", 0) == 0:
                return True
        print(f"发送视频失败: {data}")
        return False
    except Exception as e:
        print(f"发送视频异常: {e}")
        return False


def send_typing(user: UserConfig, status: int = 1) -> bool:
    """发送输入状态 (1=正在输入, 2=停止)"""
    try:
        # 先获取 typing_ticket
        config_req = {
            "ilink_user_id": user.ilink_user_id,
            "context_token": user.context_token,
            "base_info": {"channel_version": "1.0.3"}
        }
        resp = requests.post(
            f"{user.base_url}/ilink/bot/getconfig",
            json=config_req,
            headers=common_headers(user.bot_token),
            timeout=10
        )
        data = resp.json()
        typing_ticket = data.get("typing_ticket", "")
        if not typing_ticket:
            return False

        # 发送 typing 状态
        typing_req = {
            "ilink_user_id": user.ilink_user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": {"channel_version": "1.0.3"}
        }
        resp = requests.post(
            f"{user.base_url}/ilink/bot/sendtyping",
            json=typing_req,
            headers=common_headers(user.bot_token),
            timeout=10
        )
        return resp.json().get("ret") == 0
    except Exception as e:
        print(f"发送输入状态异常: {e}")
        return False


# 飞书通知配置（可选）
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")

def send_feishu_notification(title: str, content: str) -> bool:
    """发送飞书通知"""
    if not FEISHU_WEBHOOK_URL:
        return False
    
    try:
        resp = requests.post(
            FEISHU_WEBHOOK_URL,
            json={
                "msg_type": "text",
                "content": {"text": f"{title}\n\n{content}"}
            },
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"发送飞书通知失败: {e}")
        return False


def renewal_reminder_checker():
    """
    续期提醒检查器（后台线程）
    每小时检查一次，如果超过 20 小时未收到消息，通过微信发送续期提醒
    """
    RENEWAL_HOURS = 20  # 20 小时后提醒
    
    print("[续期提醒] 后台检查线程已启动")
    
    while True:
        try:
            time.sleep(3600)  # 每小时检查一次
            
            current_time = time.time()
            
            for bot_id, user in list(cfg.bots.items()):
                if not user.last_message_time or not user.ilink_user_id:
                    continue
                
                hours_since_last_msg = (current_time - user.last_message_time) / 3600
                
                # 超过 20 小时且未发送过提醒
                if hours_since_last_msg >= RENEWAL_HOURS and not user.renewal_notified:
                    print(f"\n{'='*60}")
                    print(f"[续期提醒] Bot: {bot_id}")
                    print(f"  距离上次消息: {hours_since_last_msg:.1f} 小时")
                    print(f"  发送微信续期提醒...")
                    print(f"{'='*60}\n")
                    
                    # 通过微信发送续期提醒消息
                    reminder_text = (
                        "⚠️ 微信机器人续期提醒\n\n"
                        f"距离上次消息: {hours_since_last_msg:.1f} 小时\n"
                        "微信机器人将在 4 小时后过期。\n\n"
                        "请回复任意消息续期，保持服务可用。"
                    )
                    
                    if send_text_message(user, user.ilink_user_id, reminder_text, user.context_token):
                        print(f"[续期提醒] 已发送到微信: {user.ilink_user_id}")
                    else:
                        print(f"[续期提醒] 发送失败，可能已过期")
                    
                    # 发送飞书通知（可选）
                    if FEISHU_WEBHOOK_URL:
                        send_feishu_notification(
                            "⚠️ 微信机器人续期提醒",
                            f"Bot: {bot_id}\n"
                            f"距离上次消息: {hours_since_last_msg:.1f} 小时\n"
                            f"微信用户: {user.ilink_user_id}"
                        )
                    
                    # 标记已提醒
                    cfg.lock.acquire()
                    user.renewal_notified = True
                    cfg.lock.release()
                    cfg.save()
                    
        except Exception as e:
            print(f"[续期提醒] 检查异常: {e}")
            time.sleep(60)


def monitor_weixin(user: UserConfig):
    """监听微信消息 (长轮询)"""
    print(f"[Bot: {user.bot_id}] 开始监听消息...")
    timeout = 35

    while True:
        try:
            req_data = {
                "get_updates_buf": user.get_updates_buf,
                "base_info": {"channel_version": "1.0.3"}
            }

            resp = requests.post(
                f"{user.base_url}/ilink/bot/getupdates",
                json=req_data,
                headers=common_headers(user.bot_token),
                timeout=timeout
            )

            data = resp.json()

            # 检查错误
            if data.get("ret") is not None and data.get("ret") != 0:
                errcode = data.get("errcode", data.get("ret"))
                print(f"[Bot: {user.bot_id}] 监听异常: errcode={errcode}, errmsg={data.get('errmsg', '')}")
                
                # 会话过期
                if errcode in [40001, 40014, 42001]:
                    print(f"[Bot: {user.bot_id}] 会话已过期，请重新登录")
                
                time.sleep(2)
                continue

            # 更新 timeout
            if data.get("longpolling_timeout_ms"):
                timeout = data["longpolling_timeout_ms"] / 1000 + 10

            # 更新游标 (断点续传)
            if data.get("get_updates_buf"):
                cfg.lock.acquire()
                user.get_updates_buf = data["get_updates_buf"]
                cfg.lock.release()
                cfg.save()

            # 处理消息
            msgs = data.get("msgs", [])
            if msgs:
                print(f"[Bot: {user.bot_id}] 收到 {len(msgs)} 条消息")
                # 更新最后收到消息的时间
                cfg.lock.acquire()
                user.last_message_time = time.time()
                user.renewal_notified = False  # 收到消息后重置提醒状态
                cfg.lock.release()
            
            for msg in msgs:
                from_user = msg.get("from_user_id", "")
                context_token = msg.get("context_token", "")
                
                if from_user:
                    # 始终更新 ilink_user_id
                    cfg.lock.acquire()
                    user.ilink_user_id = from_user
                    # 只有当 context_token 存在时才更新
                    if context_token:
                        user.context_token = context_token
                        print(f"[Bot: {user.bot_id}] 上下文已更新: ilink_user_id={from_user}")
                    cfg.lock.release()
                    cfg.save()

                    # 打印消息
                    for item in msg.get("item_list", []):
                        msg_type = item.get("type", 0)
                        if msg_type == 1:
                            text = item.get("text_item", {}).get("text", "")
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: {text}")
                        elif msg_type == 2:
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: <图片>")
                        elif msg_type == 5:
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: <视频>")
                        elif msg_type == 4:
                            file_name = item.get("file_item", {}).get("file_name", "")
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: <文件: {file_name}>")
                        else:
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: <类型 {msg_type}>")

        except requests.exceptions.Timeout:
            # 长轮询超时是正常的
            pass
        except Exception as e:
            print(f"[Bot: {user.bot_id}] 监听异常: {e}")
            time.sleep(2)


def do_qr_login() -> Optional[UserConfig]:
    """扫码登录"""
    print("\n开始扫码登录...")

    while True:
        try:
            # 获取二维码
            resp = requests.get(
                f"{DEFAULT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3",
                timeout=10
            )
            qr_data = resp.json()
            qr_code = qr_data.get("qrcode", "")
            qr_img = qr_data.get("qrcode_img_content", "")

            if not qr_code:
                print("获取二维码失败")
                return None

            # 打印二维码
            print("\n" + "=" * 50)
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_img or qr_code)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
            print("=" * 50)
            print(f"或访问: {qr_img}")
            print("请用微信扫码登录")

            # 轮询状态
            while True:
                status_resp = requests.get(
                    f"{DEFAULT_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qr_code}",
                    headers={
                        **common_headers(),
                        "iLink-App-ClientVersion": "1"
                    },
                    timeout=35
                )
                status_data = status_resp.json()
                status = status_data.get("status", "")

                if status == "wait":
                    pass
                elif status == "scaned":
                    print("已扫码，请在手机确认...")
                elif status == "expired":
                    print("二维码已过期，重新获取...")
                    break
                elif status == "confirmed":
                    print(f"登录成功! BotID: {status_data.get('ilink_bot_id')}")

                    # 创建用户配置
                    user = UserConfig({
                        "bot_token": status_data.get("bot_token", ""),
                        "bot_id": status_data.get("ilink_bot_id", ""),
                        "ilink_user_id": status_data.get("ilink_user_id", ""),
                        "api_token": generate_token(16),
                        "base_url": DEFAULT_BASE_URL,
                        "cdn_base_url": DEFAULT_CDN_BASE_URL,
                    })

                    # 保存配置
                    cfg.lock.acquire()
                    cfg.bots[user.bot_id] = user
                    if len(cfg.bots) == 1:
                        cfg.active_user = user.bot_id
                    cfg.lock.release()
                    cfg.save()

                    # 启动监听
                    threading.Thread(target=monitor_weixin, args=(user,), daemon=True).start()

                    return user

                time.sleep(1)

        except Exception as e:
            print(f"扫码登录异常: {e}")
            time.sleep(2)


class APIHandler(BaseHTTPRequestHandler):
    """HTTP API 处理器"""

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[API] {args[0]}")

    def send_json(self, code: int, data: dict):
        """发送JSON响应"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def get_param(self, key: str, default: str = "") -> str:
        """获取请求参数"""
        if hasattr(self, '_json_body') and key in self._json_body:
            return str(self._json_body[key])
        return self.query_params.get(key, [default])[0]

    def parse_request_body(self):
        """解析请求体"""
        self._json_body = {}
        self.query_params = parse_qs(urlparse(self.path).query)

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            content_type = self.headers.get("Content-Type", "")

            if "application/json" in content_type:
                try:
                    self._json_body = json.loads(body)
                except:
                    pass
            elif "application/x-www-form-urlencoded" in content_type:
                form_data = parse_qs(body.decode())
                for k, v in form_data.items():
                    self._json_body[k] = v[0] if v else ""

    def do_OPTIONS(self):
        """CORS 预检"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        self.parse_request_body()
        self.handle_request()

    def do_POST(self):
        self.parse_request_body()
        self.handle_request()

    def handle_request(self):
        """处理请求"""
        path = self.path.split("?")[0]

        # 解析路径 /bots/{bot_id}/{action}
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "bots":
            self.send_json(404, {"code": 404, "error": "Not Found"})
            return

        bot_id = parts[1]
        action = parts[2]

        # 验证 token
        token = ""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = self.get_param("token")

        cfg.lock.acquire()
        user = cfg.bots.get(bot_id)
        cfg.lock.release()

        if not user:
            self.send_json(404, {"code": 404, "error": "Bot not found"})
            return

        if user.api_token != token or not token:
            self.send_json(401, {"code": 401, "error": "Unauthorized"})
            return

        # 处理不同 action
        if action == "messages":
            self._handle_messages(user)
        elif action == "images":
            self._handle_images(user)
        elif action == "files":
            self._handle_files(user)
        elif action == "videos":
            self._handle_videos(user)
        elif action == "upload":
            self._handle_upload(user)
        elif action == "typing":
            self._handle_typing(user)
        else:
            self.send_json(404, {"code": 404, "error": "Unknown action"})

    def _handle_messages(self, user: UserConfig):
        """处理文本消息"""
        text = self.get_param("text")
        to = self.get_param("to", user.ilink_user_id)
        
        if not text:
            self.send_json(400, {"code": 400, "error": "Missing text"})
            return

        if not to:
            self.send_json(400, {"code": 400, "error": "Missing to (recipient) and no context"})
            return

        if send_text_message(user, to, text, user.context_token):
            self.send_json(200, {"code": 200, "message": "OK"})
        else:
            self.send_json(500, {"code": 500, "error": "Send failed"})

    def _handle_images(self, user: UserConfig):
        """处理图片消息"""
        image_url = self.get_param("image_url")
        image_base64 = self.get_param("image_base64")
        to = self.get_param("to", user.ilink_user_id)
        
        if not image_url and not image_base64:
            self.send_json(400, {"code": 400, "error": "Missing image_url or image_base64"})
            return

        if not to:
            self.send_json(400, {"code": 400, "error": "Missing to (recipient)"})
            return

        try:
            # 获取图片数据
            if image_url:
                print(f"下载图片: {image_url[:80]}...")
                resp = requests.get(image_url, timeout=30)
                if resp.status_code != 200:
                    self.send_json(400, {"code": 400, "error": f"Failed to download image: {resp.status_code}"})
                    return
                image_data = resp.content
            else:
                image_data = base64.b64decode(image_base64)

            # 上传到 CDN
            upload_info = upload_file_to_cdn(user, image_data, media_type=MEDIA_TYPE_IMAGE, filename="image.jpg")
            if not upload_info:
                self.send_json(500, {"code": 500, "error": "CDN upload failed"})
                return

            # 发送图片消息
            if send_image_message(user, to, upload_info, user.context_token):
                self.send_json(200, {"code": 200, "message": "OK"})
            else:
                self.send_json(500, {"code": 500, "error": "Send image failed"})

        except Exception as e:
            self.send_json(500, {"code": 500, "error": str(e)})

    def _handle_files(self, user: UserConfig):
        """处理文件消息"""
        file_url = self.get_param("file_url")
        file_base64 = self.get_param("file_base64")
        filename = self.get_param("filename", "file")
        to = self.get_param("to", user.ilink_user_id)
        
        if not file_url and not file_base64:
            self.send_json(400, {"code": 400, "error": "Missing file_url or file_base64"})
            return

        if not to:
            self.send_json(400, {"code": 400, "error": "Missing to (recipient)"})
            return

        try:
            # 获取文件数据
            if file_url:
                print(f"下载文件: {file_url[:80]}...")
                resp = requests.get(file_url, timeout=60)
                if resp.status_code != 200:
                    self.send_json(400, {"code": 400, "error": f"Failed to download file: {resp.status_code}"})
                    return
                file_data = resp.content
            else:
                file_data = base64.b64decode(file_base64)

            # 上传到 CDN
            upload_info = upload_file_to_cdn(user, file_data, media_type=MEDIA_TYPE_FILE, filename=filename)
            if not upload_info:
                self.send_json(500, {"code": 500, "error": "CDN upload failed"})
                return

            # 发送文件消息
            if send_file_message(user, to, upload_info, filename, user.context_token):
                self.send_json(200, {"code": 200, "message": "OK"})
            else:
                self.send_json(500, {"code": 500, "error": "Send file failed"})

        except Exception as e:
            self.send_json(500, {"code": 500, "error": str(e)})

    def _handle_videos(self, user: UserConfig):
        """处理视频消息"""
        video_url = self.get_param("video_url")
        video_base64 = self.get_param("video_base64")
        to = self.get_param("to", user.ilink_user_id)
        
        if not video_url and not video_base64:
            self.send_json(400, {"code": 400, "error": "Missing video_url or video_base64"})
            return

        if not to:
            self.send_json(400, {"code": 400, "error": "Missing to (recipient)"})
            return

        try:
            # 获取视频数据
            if video_url:
                print(f"下载视频: {video_url[:80]}...")
                resp = requests.get(video_url, timeout=120)
                if resp.status_code != 200:
                    self.send_json(400, {"code": 400, "error": f"Failed to download video: {resp.status_code}"})
                    return
                video_data = resp.content
            else:
                video_data = base64.b64decode(video_base64)

            # 上传到 CDN
            upload_info = upload_file_to_cdn(user, video_data, media_type=MEDIA_TYPE_VIDEO, filename="video.mp4")
            if not upload_info:
                self.send_json(500, {"code": 500, "error": "CDN upload failed"})
                return

            # 发送视频消息
            if send_video_message(user, to, upload_info, user.context_token):
                self.send_json(200, {"code": 200, "message": "OK"})
            else:
                self.send_json(500, {"code": 500, "error": "Send video failed"})

        except Exception as e:
            self.send_json(500, {"code": 500, "error": str(e)})

    def _handle_upload(self, user: UserConfig):
        """仅上传文件到 CDN"""
        file_base64 = self.get_param("file_base64")
        media_type = int(self.get_param("media_type", "1"))  # 默认图片
        filename = self.get_param("filename", "file")
        
        if not file_base64:
            self.send_json(400, {"code": 400, "error": "Missing file_base64"})
            return

        try:
            file_data = base64.b64decode(file_base64)
            upload_info = upload_file_to_cdn(user, file_data, media_type=media_type, filename=filename)
            if upload_info:
                self.send_json(200, {
                    "code": 200,
                    "message": "OK",
                    "aeskey": upload_info["aeskey"],
                    "aes_key": upload_info["aes_key"],
                    "encrypt_query_param": upload_info["encrypt_query_param"],
                    "filesize": upload_info["filesize"],
                    "rawsize": upload_info["rawsize"]
                })
            else:
                self.send_json(500, {"code": 500, "error": "Upload failed"})
        except Exception as e:
            self.send_json(400, {"code": 400, "error": str(e)})

    def _handle_typing(self, user: UserConfig):
        """处理输入状态"""
        status_str = self.get_param("status", "1")
        try:
            status = int(status_str)
        except:
            status = 1
        
        if send_typing(user, status):
            self.send_json(200, {"code": 200, "message": "OK"})
        else:
            self.send_json(500, {"code": 500, "error": "Send typing failed"})


def start_api_server(port: int):
    """启动API服务器"""
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"API 服务启动: http://0.0.0.0:{port}")
    server.serve_forever()


def console_loop():
    """控制台交互"""
    print("\n控制台命令:")
    print("  /login       - 扫码添加新账号")
    print("  /bots        - 列出所有已登录账号")
    print("  /bot <序号>  - 切换活跃账号")
    print("  /del <序号>  - 删除指定账号")
    print("  [文本]       - 用当前账号发送消息")
    print("  /quit        - 退出程序\n")

    while True:
        try:
            if cfg.active_user:
                prompt = f"[{cfg.active_user[:20]}...] > "
            else:
                prompt = "[未选择账号] > "

            text = input(prompt).strip()
            if not text:
                continue

            if text == "/quit":
                print("退出...")
                cfg.save()
                os._exit(0)

            elif text == "/login":
                do_qr_login()
                continue

            elif text == "/bots":
                print("\n已登录账号:")
                cfg.lock.acquire()
                bots_list = list(cfg.bots.items())
                for i, (bot_id, user) in enumerate(bots_list, 1):
                    mark = "*" if bot_id == cfg.active_user else " "
                    print(f"  {i}) [{mark}] BotID: {bot_id}")
                    print(f"       APIToken: {user.api_token}")
                cfg.lock.release()

                try:
                    num = input("输入序号选择账号 (回车取消): ").strip()
                    if num:
                        idx = int(num) - 1
                        if 0 <= idx < len(bots_list):
                            cfg.lock.acquire()
                            cfg.active_user = bots_list[idx][0]
                            cfg.lock.release()
                            print(f"已切换到: {cfg.active_user}")
                except:
                    pass
                continue

            elif text.startswith("/bot "):
                try:
                    idx = int(text.split()[1]) - 1
                    cfg.lock.acquire()
                    bots_list = list(cfg.bots.keys())
                    if 0 <= idx < len(bots_list):
                        cfg.active_user = bots_list[idx]
                        print(f"已切换到: {cfg.active_user}")
                    cfg.lock.release()
                except:
                    print("无效的序号")
                continue

            elif text.startswith("/del "):
                try:
                    idx = int(text.split()[1]) - 1
                    cfg.lock.acquire()
                    bots_list = list(cfg.bots.keys())
                    if 0 <= idx < len(bots_list):
                        del cfg.bots[bots_list[idx]]
                        if cfg.active_user == bots_list[idx]:
                            cfg.active_user = ""
                        print(f"已删除: {bots_list[idx]}")
                        cfg.lock.release()
                        cfg.save()
                    else:
                        cfg.lock.release()
                        print("无效的序号")
                except Exception as e:
                    print(f"删除失败: {e}")
                continue

            elif text.startswith("/"):
                print("未知命令，当作文本消息处理...")

            # 发送消息
            cfg.lock.acquire()
            user = cfg.bots.get(cfg.active_user)
            cfg.lock.release()

            if not user:
                print("未选择账号，输入 /bots 选择")
                continue

            if not user.ilink_user_id:
                print("当前账号没有收到过消息，无法确定发送对象")
                print("提示：请先向「微信ClawBot」发送一条消息激活上下文")
                continue

            if send_text_message(user, user.ilink_user_id, text, user.context_token):
                print("发送成功!")
            else:
                print("发送失败")

        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n退出...")
            cfg.save()
            os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="WeClawBot-API Python版本")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="API服务端口")
    args = parser.parse_args()

    print("=" * 60)
    print("WeClawBot-API Python版本 v1.3.0")
    print("基于微信ClawBot (iLink) 的消息推送服务")
    print("=" * 60)

    # 加载配置
    cfg.load()

    if not cfg.bots:
        print("\n未找到已登录账号，开始扫码登录...")
        do_qr_login()
    else:
        print(f"\n已加载 {len(cfg.bots)} 个账号")
        if len(cfg.bots) == 1:
            cfg.active_user = list(cfg.bots.keys())[0]
            print(f"自动选中: {cfg.active_user}")

    # 为缺少 api_token 的账号补充 token
    cfg.lock.acquire()
    for user in cfg.bots.values():
        if not user.api_token:
            user.api_token = generate_token(16)
    cfg.lock.release()
    cfg.save()

    # 启动所有账号的监听
    for user in cfg.bots.values():
        threading.Thread(target=monitor_weixin, args=(user,), daemon=True).start()
    
    # 启动续期提醒检查器
    threading.Thread(target=renewal_reminder_checker, daemon=True).start()

    # 信号处理
    def signal_handler(sig, frame):
        print("\n收到退出信号，保存配置...")
        cfg.save()
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动 API 服务器
    api_thread = threading.Thread(target=start_api_server, args=(args.port,), daemon=True)
    api_thread.start()

    # 控制台交互
    console_loop()

    # 如果控制台退出，保持运行
    print("控制台已关闭，后台运行中...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
