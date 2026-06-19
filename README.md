# English Buddy Bot

Bot Discord tự động sửa ngữ pháp và gợi ý cách viết tự nhiên hơn, dùng OpenAI API (gpt-4o-mini).

## Cách hoạt động
- Bot lắng nghe tin nhắn trong channel có tên `chat-en` (đổi tên channel này trong Discord, hoặc đổi biến `TARGET_CHANNEL_NAME` nếu muốn dùng tên khác).
- Nếu câu đúng -> bot react ✅
- Nếu câu có lỗi -> bot react ✏️ và tạo 1 thread riêng gắn vào tin nhắn đó, gửi bản sửa + gợi ý cách nói tự nhiên hơn + giải thích ngắn gọn.

## Environment Variables cần thiết (điền trên Railway)
- `DISCORD_BOT_TOKEN` — token lấy từ Discord Developer Portal
- `OPENAI_API_KEY` — key lấy từ platform.openai.com
- `TARGET_CHANNEL_NAME` — (tùy chọn) tên channel bot sẽ hoạt động, mặc định là `chat-en`

## Quan trọng
- Trong Discord server, tạo 1 channel tên đúng là `chat-en` (hoặc tên bạn đặt trong `TARGET_CHANNEL_NAME`).
- Đảm bảo đã bật "Message Content Intent" trong Discord Developer Portal (mục Bot).
