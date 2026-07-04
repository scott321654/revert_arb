#!/usr/bin/env python3
import os
from webui.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print("🌐 TW50 尾盤套利 Web UI")
    print(f"   啟動位置: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
