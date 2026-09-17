#!/usr/bin/env python3
"""
极简 CORS 代理：将 /chat/completions 请求转发到配置的上游大模型 API。
当浏览器直接调用大模型 API 遇到 CORS 限制时使用。

用法：
  python proxy.py
然后在应用设置中将 Base URL 改为 http://localhost:8787
"""
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# 读取配置（从 localStorage 无法直接读，这里从同目录 tg_proxy_config.json 读，或用环境变量）
import os
UPSTREAM = os.environ.get("TG_UPSTREAM", "https://api.deepseek.com")

class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # 从 body 中提取 Authorization（前端应把 api_key 放到 body 里，或 header）
        try:
            data = json.loads(body)
        except Exception:
            data = {}
        api_key = data.pop("_api_key", "") or self.headers.get("Authorization", "").replace("Bearer ", "")
        upstream_body = json.dumps(data).encode()

        req = urllib.request.Request(
            f"{UPSTREAM}/chat/completions",
            data=upstream_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(result)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[proxy] {args[0]}")

if __name__ == "__main__":
    port = int(os.environ.get("TG_PROXY_PORT", "8787"))
    print(f"CORS proxy running on http://localhost:{port} -> {UPSTREAM}")
    print("In app settings, set Base URL to http://localhost:8787")
    HTTPServer(("0.0.0.0", port), ProxyHandler).serve_forever()
