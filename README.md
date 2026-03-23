# WeClawBot-API Python版本

基于 `微信ClawBot` (iLink) 的个人微信消息推送 API 服务 - Python实现。

> 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API) (Go版本)

## 功能特性

- **多账号支持**: 支持同时登录多个微信号
- **扫码登录**: 控制台打印二维码，微信扫码授权
- **持久化存储**: 登录凭证自动保存，重启后自动重连
- **命令行交互**: 内置控制台，可直接收发微信消息
- **HTTP API**: RESTful接口，支持文本消息发送和输入状态

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

### 发送文本消息

```bash
# GET
curl "http://localhost:26322/bots/{bot_id}/messages?token={api_token}&text=Hello"

# POST
curl -X POST "http://localhost:26322/bots/{bot_id}/messages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"text": "Hello"}'
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
# 将图片转为base64并发送
IMAGE_BASE64=$(base64 -w 0 image.jpg)
curl -X POST "http://localhost:26322/bots/{bot_id}/images" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"image_base64\": \"$IMAGE_BASE64\"}"
```

### 仅上传图片（返回URL）

```bash
IMAGE_BASE64=$(base64 -w 0 image.jpg)
curl -X POST "http://localhost:26322/bots/{bot_id}/upload" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {api_token}" \
  -d "{\"image_base64\": \"$IMAGE_BASE64\"}"

# 响应: {"code": 200, "image_url": "..."}
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
      "get_updates_buf": "..."
    }
  }
}
```

## 安全提示

- 妥善保管 `config/auth.json` 和 `api_token`
- 不要泄露登录凭证

## 致谢

- 原项目: [Cp0204/WeClawBot-API](https://github.com/Cp0204/WeClawBot-API)
- 微信官方插件: [@tencent-weixin/openclaw-weixin](https://www.npmjs.com/package/@tencent-weixin/openclaw-weixin)

## License

MIT
