#!/usr/bin/env python3
from webui.app import app

if __name__ == "__main__":
    print("🌐 TW50 尾盤套利 Web UI")
    print(f"   啟動位置: http://127.0.0.1:5000")
    print("   按 Ctrl+C 停止")
    app.run(debug=True, host="0.0.0.0", port=5000)
