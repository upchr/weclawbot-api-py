# WeClawBot-API Python版本

基于 `微信ClawBot` (iLink) 的个人微信消息推送 API 服务 - Python实现。

> 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API) (Go版本)

## 功能特性

- **多账号支持**: 支持同时登录多个微信号
- **扫码登录**: 控制台打印二维码，微信扫码授权
- **持久化存储**: 登录凭证自动保存，重启后自动重连
- **命令行交互**: 内置控制台，可直接收发微信消息
- **HTTP API**: RESTful接口，支持文本/图片/文件/视频发送

## 技术实现

基于对 `@tencent-weixin/openclaw-weixin` 插件的逆向学习：

### CDN 上传流程
1. 生成随机 AES-128 密钥 (16字节)
2. 使用 AES-128-ECB 加密文件
3. 调用 `getUploadUrl` 获取上传参数
4. POST 加密数据到 CDN
5. 获取 `x-encrypted-query-param` 作为下载参数

### 关键发现
- `aes_key` 格式：必须将 hex 字符串再 base64 编码，而非直接编码原始字节
- CDN 参数：必须使用 `x-encrypted-query-param`，而非 `x-encrypted-param`
- 消息类型：TEXT(1), IMAGE(2), VIDEO(3), FILE(4)

## 快速开始

### Docker Compose (推荐)

```bash
docker-compose up -d
docker exec -it weclawbot-api-py python main.py
```

### 本地运行

```bash
pip install -r requirements.txt
python main.py
```

### 初次登录

启动后输入 `/login` 扫码登录，授权后发送一条消息给"微信ClawBot"激活API发信。

## 常用命令

| 命令 | 说明 |
|------|------|
| `/login` | 扫码登录新账号 |
| `/bots` | 列出所有已登录账号 |
| `/bot <序号>` | 切换当前账号 |
| `/del <序号>` | 删除指定账号 |
| `/quit` | 退出程序 |

## API 文档

所有 API 支持 GET 和 POST 请求，参数可通过以下方式传递：
- Query String: `?token=xxx&text=hello`
- JSON Body: `{"text": "hello"}`
- Authorization Header: `Bearer {api_token}`

### 发送文本消息

```bash
# GET
curl "http://localhost:26322/bots/{bot_id}/messages?token={api_token}&text=Hello"

# POST
curl -X POST "http://localhost:26322/bots/{bot_id}/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"text": "Hello"}'

# 指定接收者
curl -X POST "http://localhost:26322/bots/{bot_id}/messages" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"text": "Hello", "to": "xxx@im.wechat"}'
```

### 发送图片消息

**方式一：提供图片URL**

```bash
curl -X POST "http://localhost:26322/bots/{bot_id}/images" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"image_url": "https://example.com/image.jpg"}'
```

**方式二：Base64编码图片**

```bash
IMAGE_BASE64=$(base64 -w 0 image.jpg)
curl -X POST "http://localhost:26322/bots/{bot_id}/images" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"image_base64\": \"$IMAGE_BASE64\"}"
```

### 发送文件消息

```bash
FILE_BASE64=$(base64 -w 0 document.pdf)
curl -X POST "http://localhost:26322/bots/{bot_id}/files" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"file_base64\": \"$FILE_BASE64\", \"filename\": \"document.pdf\"}"
```

### 发送视频消息

```bash
VIDEO_BASE64=$(base64 -w 0 video.mp4)
curl -X POST "http://localhost:26322/bots/{bot_id}/videos" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"video_base64\": \"$VIDEO_BASE64\"}"
```

### 发送输入状态

```bash
# status: 1=正在输入, 2=停止输入
curl "http://localhost:26322/bots/{bot_id}/typing?token={api_token}&status=1"
```

### 响应格式

```json
// 成功
{"code": 200, "message": "OK"}

// 失败
{"code": 401, "error": "Unauthorized"}
```

## 配置文件

登录信息保存在 `config/auth.json`:

```json
{
  "bots": {
    "xxx@im.bot": {
      "bot_token": "...",
      "bot_id": "xxx@im.bot",
      "api_token": "...",
      "ilink_user_id": "...",
      "context_token": "...",
      "get_updates_buf": "...",
      "base_url": "https://ilinkai.weixin.qq.com",
      "cdn_base_url": "https://wxbot-cdn.wechat.com"
    }
  }
}
```

## 安全提示

- 妥善保管 `config/auth.json` 和 `api_token`
- 不要泄露登录凭证
- 建议在生产环境使用 HTTPS

## Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p /app/config
VOLUME /app/config

EXPOSE 26322

CMD ["python", "main.py"]
```

```yaml
# docker-compose.yml
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

## 常见问题

### Q: 发送图片/文件失败？
A: 确保 CDN 上传成功，检查日志中的错误信息。常见原因：
- 文件过大
- 网络问题
- Token 过期

### Q: 会话过期怎么办？
A: 重新运行 `/login` 扫码登录。

### Q: 如何发送给指定用户？
A: 在 API 请求中添加 `to` 参数，值为用户的微信 ID (格式: `xxx@im.wechat`)。

## 致谢

- 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API)
- 微信官方插件: [@tencent-weixin/openclaw-weixin](https://www.npmjs.com/package/@tencent-weixin/openclaw-weixin)

## License

MIT
