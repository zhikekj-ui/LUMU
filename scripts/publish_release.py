#!/usr/bin/env python3
"""
LUMU 发布脚本 —— 把「当前干净源码」打包推到官网 (180) 的 /downloads/，
让官网成为实时分发中心（不经过 GitHub）。

用法（密码走环境变量，不入库）:
  LUMU_PORTAL_PASS='<180 root 密码>' python scripts/publish_release.py

流程:
  1. 扫描工作树是否含真实密钥（sk-/AWS/私钥等），有则中止
  2. 打包干净源码（剔除 .git/.venv/node_modules/data/.env/备份等）
  3. 上传 lumu-latest.zip + lumu-version.json 到 180 的 public/downloads 与 dist/downloads
"""
import os
import re
import sys
import time
import json
import zipfile
import subprocess
import paramiko

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ~/LUMU
HOST = os.environ.get("LUMU_PORTAL_HOST", "8.133.254.180")
USER = os.environ.get("LUMU_PORTAL_USER", "root")
PASS = os.environ.get("LUMU_PORTAL_PASS", "")
if not PASS:
    PASS = input("180 root password: ")

REMOTE_PUBLIC = "/opt/lumu-portal/site/public/downloads"
REMOTE_DIST = "/opt/lumu-portal/site/dist/downloads"
DL_URL = "https://lumux.cn/downloads/lumu-latest.zip"

# 排除项（相对 SRC）
EXCLUDE_DIRS = {".git", ".venv", "node_modules", "data", "__pycache__", "dist", "build", ".idea", ".vscode"}
EXCLUDE_FILES = {".DS_Store", ".lumu_prev", ".env", ".env.local"}
EXCLUDE_SUFFIX = (".pyc", ".bak", ".prev", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".log", ".tmp")

# 真实密钥特征（变量名引用不算，只抓真实密钥形态）
LEAK_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),        # OpenAI / 兼容
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)stepfun[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)deepseek[A-Za-z0-9]{16,}"),
    re.compile(r"ehqeERFS"),                     # 服务器 root 密码特征
]

TEXT_SUFFIX = (".py", ".ps1", ".sh", ".ts", ".tsx", ".js", ".json", ".md", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".css", ".html", ".env")


def scan_leaks() -> list:
    hits = []
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES or f.endswith(EXCLUDE_SUFFIX):
                continue
            rel = os.path.relpath(os.path.join(root, f), SRC)
            if rel == "scripts/publish_release.py":
                continue  # 发布脚本自身含检测特征，跳过
            if not f.endswith(TEXT_SUFFIX):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        for pat in LEAK_PATTERNS:
                            if pat.search(line):
                                hits.append(f"{os.path.relpath(p, SRC)}:{i}: {line.strip()[:80]}")
            except Exception:
                pass
    return hits


def build_zip(out_path: str) -> int:
    n = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f in EXCLUDE_FILES or f.endswith(EXCLUDE_SUFFIX):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, SRC)
                if rel.startswith("scripts/publish_release.py"):
                    continue  # 发布脚本本身不进分发包
                z.write(full, rel)
                n += 1
    return n


def main() -> int:
    print("== 1) 扫描密钥泄露 ==")
    leaks = scan_leaks()
    if leaks:
        print("✗ 发现疑似真实密钥，已中止发布（请先清理）：")
        for h in leaks[:20]:
            print("   ", h)
        return 1
    print("   ✓ 未发现真实密钥")

    print("== 2) 打包干净源码 ==")
    tmp_zip = "/tmp/lumu_release.zip"
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    count = build_zip(tmp_zip)
    size = os.path.getsize(tmp_zip)
    print(f"   ✓ {count} 个文件，{size/1024/1024:.2f} MB -> {tmp_zip}")

    print("== 3) 取版本号 ==")
    try:
        ver = subprocess.check_output(["git", "-C", SRC, "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        ver = time.strftime("%Y%m%d")
    date = time.strftime("%Y-%m-%dT%H:%M:%S")
    version = {"version": ver, "date": date, "url": DL_URL, "size": size, "notes": "官网实时分发版本"}
    tmp_json = "/tmp/lumu-version.json"
    with open(tmp_json, "w", encoding="utf-8") as fh:
        json.dump(version, fh, ensure_ascii=False, indent=2)
    print(f"   version={ver}  date={date}")

    print(f"== 4) 上传到 {HOST} ==")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, 22, USER, PASS, timeout=30)
    sftp = ssh.open_sftp()
    for base in (REMOTE_PUBLIC, REMOTE_DIST):
        try:
            sftp.stat(base)
        except IOError:
            ssh.exec_command(f"mkdir -p {base}")
            time.sleep(0.5)
        sftp.put(tmp_zip, f"{base}/lumu-latest.zip")
        sftp.put(tmp_json, f"{base}/lumu-version.json")
        print(f"   put {base}/lumu-latest.zip + lumu-version.json")
    sftp.close()

    # 验证
    def run(c):
        i, o, e = ssh.exec_command(c)
        return o.read().decode().strip() + "\n" + e.read().decode().strip()
    print("== 5) 验证 ==")
    print("  zip HTTP:", run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/downloads/lumu-latest.zip; echo"))
    print("  json HTTP:", run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/downloads/lumu-version.json; echo"))
    print("  version:", run("curl -s http://127.0.0.1/downloads/lumu-version.json | head -c 200; echo"))
    ssh.close()
    print("✓ 发布完成。官网已是最新。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
