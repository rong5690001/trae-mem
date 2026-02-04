#!/usr/bin/env python3
"""
Trae-Mem 一键安装脚本
功能：自动将 trae-mem 配置添加到 Trae IDE 的 mcp.json 中
"""

import json
import os
import sys
import shutil
from pathlib import Path

def get_trae_config_dir():
    """获取 Trae 用户配置目录"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Trae" / "User"
    elif sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Trae" / "User"
    elif sys.platform == "linux":
        return Path.home() / ".config" / "Trae" / "User"
    else:
        print(f"❌ 不支持的操作系统: {sys.platform}")
        sys.exit(1)

def install():
    print("🚀 开始安装 trae-mem MCP 服务...")

    # 1. 确定关键路径
    # 假设脚本位于 repo/scripts/install_mcp.py，repo_root 就是脚本的上上一级
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    
    # 检查核心模块是否存在
    if not (repo_root / "trae_mem").exists():
        print(f"❌ 错误: 在 {repo_root} 下未找到 trae_mem 模块。请确保你在 trae-mem 仓库中运行此脚本。")
        sys.exit(1)

    print(f"📂 仓库路径: {repo_root}")

    # 2. 定位 mcp.json
    config_dir = get_trae_config_dir()
    mcp_config_path = config_dir / "mcp.json"
    
    if not config_dir.exists():
        print(f"⚠️  Trae 配置目录不存在: {config_dir}")
        print("请先安装并运行一次 Trae IDE。")
        sys.exit(1)

    print(f"📄 配置文件: {mcp_config_path}")

    # 3. 准备配置内容
    # 使用当前运行脚本的 python 解释器，确保兼容性
    python_exe = sys.executable
    
    mcp_entry = {
        "command": python_exe,
        "args": ["-m", "trae_mem.mcp_server"],
        "env": {
            "PYTHONPATH": str(repo_root),
            "TRAE_MEM_HOME": str(Path.home() / ".trae-mem")
        }
    }

    # 4. 读取现有配置
    config = {"mcpServers": {}}
    if mcp_config_path.exists():
        try:
            content = mcp_config_path.read_text(encoding="utf-8")
            if content.strip():
                config = json.loads(content)
        except json.JSONDecodeError:
            print("⚠️  现有的 mcp.json 格式错误，将创建新文件并备份旧文件。")
            shutil.copy(mcp_config_path, mcp_config_path.with_suffix(".json.bak"))
        except Exception as e:
            print(f"❌ 读取配置失败: {e}")
            sys.exit(1)
    
    # 备份
    if mcp_config_path.exists():
        backup_path = mcp_config_path.with_suffix(".json.bak")
        shutil.copy(mcp_config_path, backup_path)
        print(f"📦 已备份原配置至: {backup_path.name}")

    # 5. 更新配置
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    
    config["mcpServers"]["trae-mem"] = mcp_entry
    
    # 6. 写入文件
    try:
        mcp_config_path.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
        print("✅ 配置写入成功！")
    except Exception as e:
        print(f"❌ 写入配置失败: {e}")
        sys.exit(1)

    print("\n🎉 安装完成！")
    print("👉 请重启 Trae IDE 以使更改生效。")
    print("💡 验证方式: 在 Trae 对话框输入 '@trae-mem' 或检查工具列表是否包含 'trae_mem_search'。")

if __name__ == "__main__":
    install()
