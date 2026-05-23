import imaplib

host = "imap.qq.com"
port = 993
user = "2834926690@qq.com"
pwd = "umluggqqdqvwdgid"

try:
    conn = imaplib.IMAP4_SSL(host, port)
    print("端口连接成功")
    conn.login(user, pwd)
    print("✅ 邮箱登录正常")
    conn.logout()
except Exception as e:
    print(f"❌ 连接失败：{e}")