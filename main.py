#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeClawBot-API Python版本
基于微信ClawBot (iLink) 的个人微信消息推送 API 服务
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
import random
from pathlib import Path
from typing import Optional, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import io

import qrcode
import requests

# 默认配置
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_PORT = 26322
CONFIG_PATH = Path("./config/auth.json")


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

    def to_dict(self) -> dict:
        return {
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "get_updates_buf": self.get_updates_buf,
            "ilink_user_id": self.ilink_user_id,
            "context_token": self.context_token,
            "api_token": self.api_token,
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


def send_message(user: UserConfig, to: str, text: str, context_token: str) -> bool:
    """发送消息"""
    req_data = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"openclaw-weixin:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {"text": text}
                }
            ]
        },
        "base_info": {"channel_version": "1.0.2"}
    }

    try:
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/ilink/bot/sendmessage",
            json=req_data,
            headers=common_headers(user.bot_token),
            timeout=10
        )
        data = resp.json()
        if data.get("ret") == 0 and data.get("errcode", 0) == 0:
            return True
        print(f"发送失败: {data}")
        return False
    except Exception as e:
        print(f"发送消息异常: {e}")
        return False


def send_typing(user: UserConfig, status: int = 1) -> bool:
    """发送输入状态"""
    # 先获取typing_ticket
    try:
        config_req = {
            "ilink_user_id": user.ilink_user_id,
            "context_token": user.context_token,
            "base_info": {"channel_version": "1.0.0"}
        }
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/ilink/bot/getconfig",
            json=config_req,
            headers=common_headers(user.bot_token),
            timeout=10
        )
        data = resp.json()
        typing_ticket = data.get("typing_ticket", "")
        if not typing_ticket:
            return False

        # 发送typing状态
        typing_req = {
            "ilink_user_id": user.ilink_user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": {"channel_version": "1.0.0"}
        }
        resp = requests.post(
            f"{DEFAULT_BASE_URL}/ilink/bot/sendtyping",
            json=typing_req,
            headers=common_headers(user.bot_token),
            timeout=10
        )
        return resp.json().get("ret") == 0
    except Exception as e:
        print(f"发送输入状态异常: {e}")
        return False


def monitor_weixin(user: UserConfig):
    """监听微信消息"""
    print(f"[Bot: {user.bot_id}] 开始监听消息...")
    timeout = 35

    while True:
        try:
            req_data = {
                "get_updates_buf": user.get_updates_buf,
                "base_info": {"channel_version": "1.0.0"}
            }

            resp = requests.post(
                f"{DEFAULT_BASE_URL}/ilink/bot/getupdates",
                json=req_data,
                headers=common_headers(user.bot_token),
                timeout=timeout
            )

            data = resp.json()

            if data.get("ret") != 0 or data.get("errcode", 0) != 0:
                time.sleep(2)
                continue

            # 更新timeout
            if data.get("longpolling_timeout_ms"):
                timeout = data["longpolling_timeout_ms"] / 1000 + 10

            # 更新游标
            if data.get("get_updates_buf"):
                cfg.lock.acquire()
                user.get_updates_buf = data["get_updates_buf"]
                cfg.lock.release()
                cfg.save()

            # 处理消息
            for msg in data.get("msgs", []):
                from_user = msg.get("from_user_id", "")
                if from_user:
                    # 更新context
                    if msg.get("context_token"):
                        cfg.lock.acquire()
                        user.context_token = msg["context_token"]
                        cfg.lock.release()
                        cfg.save()

                    # 打印消息
                    for item in msg.get("item_list", []):
                        msg_type = item.get("type", 0)
                        if msg_type == 1:
                            text = item.get("text_item", {}).get("text", "")
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: {text}")
                        else:
                            print(f"\n[Bot: {user.bot_id} | 来自 {from_user}]: <媒体/其他类型 {msg_type}>")

        except Exception as e:
            print(f"[Bot: {user.bot_id}] 监听异常: {e}")
            time.sleep(2)


def do_qr_login() -> Optional[UserConfig]:
    """扫码登录"""
    print("\n开始扫码登录...")

    while True:
        try:
            # 获取二维码
            resp = requests.get(f"{DEFAULT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3", timeout=10)
            qr_data = resp.json()
            qr_code = qr_data.get("qrcode", "")
            qr_img = qr_data.get("qrcode_img_content", "")

            if not qr_code:
                print("获取二维码失败")
                return None

            # 打印二维码
            print("\n" + "=" * 50)
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_img)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
            print("=" * 50)
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
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def get_param(self, key: str) -> str:
        """获取请求参数"""
        # 优先从JSON body获取
        if hasattr(self, '_json_body') and key in self._json_body:
            return str(self._json_body[key])
        # 再从form获取
        return self.query_params.get(key, [""])[0]

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
                from urllib.parse import parse_qs
                form_data = parse_qs(body.decode())
                for k, v in form_data.items():
                    self._json_body[k] = v[0] if v else ""
            elif "multipart/form-data" in content_type:
                # 简单处理multipart
                pass

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

        # 验证token
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

        # 处理不同action
        if action == "messages":
            text = self.get_param("text")
            if not text:
                self.send_json(400, {"code": 400, "error": "Missing text"})
                return

            if not user.ilink_user_id or not user.context_token:
                self.send_json(400, {"code": 400, "error": "Context not ready"})
                return

            if send_message(user, user.ilink_user_id, text, user.context_token):
                self.send_json(200, {"code": 200, "message": "OK"})
            else:
                self.send_json(500, {"code": 500, "error": "Send failed"})

        elif action == "typing":
            status_str = self.get_param("status")
            status = int(status_str) if status_str else 1
            if send_typing(user, status):
                self.send_json(200, {"code": 200, "message": "OK"})
            else:
                self.send_json(500, {"code": 500, "error": "Send typing failed"})

        else:
            self.send_json(404, {"code": 404, "error": "Unknown action"})


def start_api_server(port: int):
    """启动API服务器"""
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"API服务启动: http://0.0.0.0:{port}")
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
                prompt = f"[{cfg.active_user}] > "
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
                    print(f"  {i}) [{mark}] BotID: {bot_id}  |  APIToken: {user.api_token}")
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

            if not user.ilink_user_id or not user.context_token:
                print("当前账号没有消息上下文，请先收到一条消息")
                continue

            if send_message(user, user.ilink_user_id, text, user.context_token):
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

    print("=" * 50)
    print("WeClawBot-API Python版本")
    print("基于微信ClawBot (iLink) 的消息推送服务")
    print("=" * 50)

    # 加载配置
    cfg.load()

    if not cfg.bots:
        print("\n未找到已登录账号，开始扫码登录...")
        do_qr_login()
    else:
        print(f"\n已加载 {len(cfg.bots)} 个账号")
        # 如果只有一个账号，自动选中
        if len(cfg.bots) == 1:
            cfg.active_user = list(cfg.bots.keys())[0]
            print(f"自动选中: {cfg.active_user}")

    # 为缺少api_token的账号补充token
    cfg.lock.acquire()
    for user in cfg.bots.values():
        if not user.api_token:
            user.api_token = generate_token(16)
    cfg.lock.release()
    cfg.save()

    # 启动所有账号的监听
    for user in cfg.bots.values():
        threading.Thread(target=monitor_weixin, args=(user,), daemon=True).start()

    # 信号处理
    def signal_handler(sig, frame):
        print("\n收到退出信号，保存配置...")
        cfg.save()
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动API服务器
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
