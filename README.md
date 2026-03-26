# WeClawBot-API Python版本

基于 `微信ClawBot` (iLink) 的个人微信消息推送 API 服务 - Python实现。

> 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API) (Go版本)

## ✨ 功能特性

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 文本消息 | ✅ | 支持中英文 |
| 图片发送 | ✅ | CDN上传 + AES加密 |
| 文件发送 | ✅ | 支持任意文件类型 |
| 视频发送 | ✅ | 大文件自动处理 |
| 输入状态 | ✅ | 正在输入/停止 |
| 多账号管理 | ✅ | 同时登录多个微信号 |
| 扫码登录 | ✅ | 控制台二维码 |
| 持久化存储 | ✅ | 重启自动重连 |
| HTTP API | ✅ | RESTful接口 |

## 🛠 技术实现

基于对 `@tencent-weixin/openclaw-weixin` 插件的逆向学习：

### CDN 上传流程

```
┌──────────────┐     ┌────────────────┐     ┌─────────────────┐
│   原始文件    │────►│  AES-128-ECB   │────►│   加密后文件     │
│  (明文bytes)  │     │    加密         │     │    (密文)       │
└──────────────┘     └────────────────┘     └────────┬────────┘
                                                      │
                              ┌───────────────────────▼───────────────────────┐
                              │              微信 CDN 上传                      │
                              │  POST /upload?encrypted_query_param=xxx        │
                              │  Content-Type: application/octet-stream        │
                              │  Body: 加密后的二进制数据                        │
                              └───────────────────────┬───────────────────────┘
                                                      │
                              ┌───────────────────────▼───────────────────────┐
                              │  响应 Headers:                                  │
                              │  x-encrypted-query-param: xxx  ◄── 正确参数     │
                              │  x-encrypted-param: yyy        ◄── 内部参数    │
                              └───────────────────────────────────────────────┘
```

### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| **CDN Base URL** | `https://novac2c.cdn.weixin.qq.com/c2c` | ⚠️ 不是 `wxbot-cdn.wechat.com` |
| **CDN 参数名** | `encrypted_query_param` | ⚠️ 不是 `upload_param` |
| **aes_key 格式** | `base64(hex_string)` | ⚠️ 不是 `base64(raw_bytes)` |
| **响应头** | `x-encrypted-query-param` | ⚠️ 不是 `x-encrypted-param` |

### 媒体类型常量

```python
MEDIA_TYPE_IMAGE = 1  # 图片
MEDIA_TYPE_VIDEO = 2  # 视频
MEDIA_TYPE_FILE = 3   # 文件
```

### 消息类型常量

```python
TEXT = 1   # 文本
IMAGE = 2  # 图片
VOICE = 3  # 语音
FILE = 4   # 文件
VIDEO = 5  # 视频
```

## 🚀 快速开始

### Docker Compose (推荐)

```bash
# 克隆项目
git clone https://github.com/upchr/weclawbot-api-py.git
cd weclawbot-api-py

# 启动服务
docker-compose up -d

# 进入控制台
docker exec -it weclawbot-api-py python main.py
```

### 本地运行

```bash
# 克隆项目
git clone https://github.com/upchr/weclawbot-api-py.git
cd weclawbot-api-py

# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
```

### 初次登录

1. 启动后输入 `/login` 扫码登录
2. 微信扫码授权
3. **重要**：向「微信ClawBot」发送一条消息激活上下文
4. 开始使用 API 发送消息

## 💻 控制台命令

| 命令 | 说明 |
|------|------|
| `/login` | 扫码登录新账号 |
| `/bots` | 列出所有已登录账号及其 API Token |
| `/bot <序号>` | 切换当前活跃账号 |
| `/del <序号>` | 删除指定账号 |
| `<文本>` | 向当前账号发送消息 |
| `/quit` | 退出程序 |

## 📡 API 文档

### 认证方式

所有 API 支持以下认证方式：

```bash
# 方式1: Query参数
curl "http://localhost:26322/bots/{bot_id}/messages?token={api_token}&text=Hello"

# 方式2: Authorization Header
curl -H "Authorization: Bearer {api_token}" "http://localhost:26322/bots/{bot_id}/messages?text=Hello"

# 方式3: JSON Body
curl -d '{"token": "{api_token}", "text": "Hello"}' ...
```

### 发送文本消息

**Endpoint**: `POST /bots/{bot_id}/messages`

```bash
# 发送文本
curl -X POST "http://localhost:26322/bots/{bot_id}/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"text": "你好，这是测试消息"}'

# 指定接收者
curl -X POST "http://localhost:26322/bots/{bot_id}/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"text": "Hello", "to": "xxx@im.wechat"}'
```

### 发送图片消息

**Endpoint**: `POST /bots/{bot_id}/images`

```bash
# 方式1: 提供图片URL
curl -X POST "http://localhost:26322/bots/{bot_id}/images" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"image_url": "https://example.com/image.jpg"}'

# 方式2: Base64编码
IMAGE_BASE64=$(base64 -w 0 image.png)
curl -X POST "http://localhost:26322/bots/{bot_id}/images" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"image_base64\": \"$IMAGE_BASE64\"}"
```

### 发送文件消息

**Endpoint**: `POST /bots/{bot_id}/files`

```bash
FILE_BASE64=$(base64 -w 0 document.pdf)
curl -X POST "http://localhost:26322/bots/{bot_id}/files" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"file_base64\": \"$FILE_BASE64\", \"filename\": \"文档.pdf\"}"
```

### 发送视频消息

**Endpoint**: `POST /bots/{bot_id}/videos`

```bash
VIDEO_BASE64=$(base64 -w 0 video.mp4)
curl -X POST "http://localhost:26322/bots/{bot_id}/videos" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"video_base64\": \"$VIDEO_BASE64\"}"
```

### 发送输入状态

**Endpoint**: `POST /bots/{bot_id}/typing`

```bash
# status: 1=正在输入, 2=停止输入
curl -X POST "http://localhost:26322/bots/{bot_id}/typing" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"status": 1}'
```

### 响应格式

```json
// 成功
{
  "code": 200,
  "message": "OK"
}

// 失败
{
  "code": 401,
  "error": "Unauthorized"
}

// 上传成功（仅 /upload 接口）
{
  "code": 200,
  "message": "OK",
  "aeskey": "...",
  "aes_key": "...",
  "encrypt_query_param": "...",
  "filesize": 1024,
  "rawsize": 1000
}
```

## 📁 配置文件

登录信息保存在 `config/auth.json`:

```json
{
  "bots": {
    "xxx@im.bot": {
      "bot_token": "微信Bot Token",
      "bot_id": "xxx@im.bot",
      "api_token": "API访问令牌",
      "ilink_user_id": "微信用户ID",
      "context_token": "消息上下文Token",
      "get_updates_buf": "消息游标",
      "base_url": "https://ilinkai.weixin.qq.com",
      "cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c"
    }
  }
}
```

## 🔧 Docker 部署

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY main.py .

# 创建配置目录
RUN mkdir -p /app/config
VOLUME /app/config

# 暴露端口
EXPOSE 26322

# 启动服务
CMD ["python", "main.py"]
```

### docker-compose.yml

```yaml
name: weclawbot-api-py
services:
  weclawbot-api-py:
    build: .
    image: weclawbot-api-py:latest
    container_name: weclawbot-api-py
    ports:
      - "26322:26322"
    volumes:
      - ./config:/app/config
    restart: unless-stopped
```

## ❓ 常见问题

### Q: 发送图片/文件显示异常或无法打开？

**A**: 这是 CDN 参数问题，已在 v1.2.0 修复。确保使用：
- CDN Base URL: `https://novac2c.cdn.weixin.qq.com/c2c`
- 参数名: `encrypted_query_param`（不是 `upload_param`）
- 响应头: `x-encrypted-query-param`（不是 `x-encrypted-param`）

### Q: 发送中文消息显示乱码？

**A**: 这是 URL 编码问题。**推荐使用 POST 方式发送中文**：

```bash
# ✅ 推荐：POST 方式（中文正常显示）
curl -X POST 'http://localhost:26322/bots/{bot_id}/messages' \
  -H 'Content-Type: application/json; charset=utf-8' \
  -H 'Authorization: Bearer {api_token}' \
  -d '{"text": "你好，测试消息"}'

# ❌ 不推荐：GET 方式直接传中文（可能乱码）
curl "http://localhost:26322/bots/{bot_id}/messages?token={api_token}&text=测试"

# ✅ 如果必须用 GET，需要 URL 编码
curl -G 'http://localhost:26322/bots/{bot_id}/messages' \
  -H 'Authorization: Bearer {api_token}' \
  --data-urlencode 'text=测试消息'
```

### Q: 提示"当前账号没有消息上下文"？

**A**: 需要先向「微信ClawBot」发送一条消息激活上下文。系统需要获取 `context_token` 才能发送消息。

### Q: 会话过期怎么办？

**A**: 运行 `/login` 重新扫码登录。

### Q: 如何发送给指定用户？

**A**: 在请求中添加 `to` 参数：
```bash
curl -d '{"text": "Hello", "to": "xxx@im.wechat"}' ...
```

### Q: 支持发送给群聊吗？

**A**: 当前版本仅支持发送给个人（直接消息）。

### Q: 为什么只能发送 24 小时内的消息？

**A**: 这是微信平台的限制，无法绕过。根据微信官方说明：

> 当你发消息后，微信ClawBot仅接收 OpenClaw 24 小时内的回复。

**解决方案**：
1. 用户每天发送一条消息续期（最简单）
2. 设置定时任务提醒用户续期
3. 用于被动推送场景（用户触发后回复）

⚠️ **注意**：任何尝试绕过此限制的方法都可能违反微信服务条款。

### Q: 大文件上传超时？

**A**: 大文件（视频等）需要更长时间，默认超时 120 秒。可以在代码中调整 `timeout` 参数。

## 🔐 安全提示

- ⚠️ 妥善保管 `config/auth.json` 和 `api_token`
- ⚠️ 不要在公网暴露 API 端口（26322）
- ⚠️ 生产环境建议使用 HTTPS 反向代理
- ⚠️ 定期更换 `api_token`

## 📝 更新日志

### v1.2.0 (2026-03-26)
- ✅ 修复 CDN 上传问题
- ✅ 修复图片/文件发送
- ✅ 添加视频发送支持
- ✅ 修复 `parse_qs` 变量作用域 bug
- ✅ 改进消息监听和上下文更新逻辑

### v1.1.0
- ✅ 初始 Python 实现
- ✅ 文本消息发送
- ✅ 多账号管理
- ✅ HTTP API

## 🙏 致谢

- 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API)
- 微信官方插件: [@tencent-weixin/openclaw-weixin](https://www.npmjs.com/package/@tencent-weixin/openclaw-weixin)

## 📜 License

MIT

---

<p align="center">
  Made with ❤️ by OpenClaw Agent
</p>
