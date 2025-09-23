#!/usr/bin/env python3
"""
直播视频处理主控制器

这个脚本可以同时运行检查和合并功能，或者分别运行它们。

使用方法:
    python main.py                    # 同时运行检查和合并
    python main.py --check-only       # 只运行检查功能
    python main.py --merge-only       # 只运行合并功能
    python main.py --merge-once       # 执行一次上传检查
"""

import argparse
import sys
import threading
import time
from config import *

def run_checker():
    """运行检查功能"""
    try:
        from checker import main_loop as checker_main
        log("启动检查模块...")
        checker_main()
    except KeyboardInterrupt:
        log("检查模块已停止")
    except Exception as e:
        log(f"检查模块发生错误: {e}")

def run_merger():
    """运行合并功能"""
    try:
        from merger import merge_once as merger_main
        log("启动合并模块...")
        merger_main()
    except KeyboardInterrupt:
        log("合并模块已停止")
    except Exception as e:
        log(f"合并模块发生错误: {e}")

def run_merger_once():
    """执行一次合并检查"""
    try:
        from merger import merge_once
        log("执行一次合并检查...")
        merge_once()
    except Exception as e:
        log(f"合并模块发生错误: {e}")

def check_dependencies():
    """检查依赖项"""
    missing_modules = []
    
    # 检查必需的Python模块
    required_modules = [
        'concurrent.futures',
        'subprocess',
        'pathlib',
        'datetime',
    ]
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)
    
    # 检查上传相关模块（可选）
    if ENABLE_AUTO_UPLOAD:
        upload_modules = [
            'pickle',
            'google.auth.transport.requests',
            'google_auth_oauthlib.flow',
            'googleapiclient.discovery',
            'googleapiclient.errors',
            'googleapiclient.http',
            'zoneinfo'
        ]
        
        for module in upload_modules:
            try:
                __import__(module)
            except ImportError:
                log(f"警告: 上传模块 {module} 不可用，将禁用自动上传功能")
    
    if missing_modules:
        log(f"错误: 缺少必需的模块: {', '.join(missing_modules)}")
        return False
    
    return True

def check_directories():
    """检查必需的目录"""
    directories_to_check = [
        (PARENT_DIR, "直播文件夹目录"),
        (OUTPUT_DIR, "输出目录")
    ]
    
    for directory, description in directories_to_check:
        if not directory.exists():
            log(f"警告: {description} 不存在: {directory}")
            try:
                directory.mkdir(parents=True, exist_ok=True)
                log(f"已创建目录: {directory}")
            except Exception as e:
                log(f"无法创建目录 {directory}: {e}")
                return False
    
    return True

def check_external_tools():
    """检查外部工具"""
    import subprocess
    
    tools = ['ffmpeg', 'ffprobe']
    missing_tools = []
    
    for tool in tools:
        try:
            subprocess.run([tool, '-version'], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL, 
                         check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing_tools.append(tool)
    
    if missing_tools:
        log(f"错误: 缺少必需的工具: {', '.join(missing_tools)}")
        log("请安装 FFmpeg 工具包")
        return False
    
    return True

def print_config():
    """打印当前配置"""
    log("=" * 50)
    log("当前配置:")
    log(f"  直播文件夹: {PARENT_DIR}")
    log(f"  输出目录: {OUTPUT_DIR}")
    log(f"  检查间隔: {CHECK_INTERVAL}秒")
    log(f"  直播中检查间隔: {LIVE_CHECK_INTERVAL}秒")
    log(f"  并发线程数: {MAX_WORKERS}")
    log(f"  自动上传: {'启用' if ENABLE_AUTO_UPLOAD else '禁用'}")
    log(f"  调试模式: {'启用' if DEBUG_MODE else '禁用'}")
    log("=" * 50)

def main():
    parser = argparse.ArgumentParser(
        description="直播视频处理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                 # 同时运行检查和合并
  python main.py --check-only    # 只运行检查功能
  python main.py --merge-only    # 只运行合并功能
  python main.py --merge-once    # 执行一次合并检查
        """
    )
    
    parser.add_argument(
        '--check-only', 
        action='store_true',
        help='只运行检查功能'
    )
    parser.add_argument(
        '--merge-only', 
        action='store_true',
        help='只运行合并功能'
    )
    parser.add_argument(
        '--merge-once', 
        action='store_true',
        help='执行一次合并检查后退出'
    )
    parser.add_argument(
        '--no-config-check', 
        action='store_true',
        help='跳过配置和依赖检查'
    )
    
    args = parser.parse_args()
    
    # 检查冲突的参数
    exclusive_args = [args.check_only, args.merge_only, args.merge_once]
    if sum(exclusive_args) > 1:
        log("错误: --check-only, --merge-only, --merge-once 不能同时使用")
        sys.exit(1)
    
    log("直播视频处理系统启动")
    
    # 配置和依赖检查
    if not args.no_config_check:
        log("检查系统环境...")
        
        if not check_dependencies():
            sys.exit(1)
        
        if not check_directories():
            sys.exit(1)
        
        if not check_external_tools():
            sys.exit(1)
        
        log("系统环境检查通过")
    
    print_config()
    
    try:
        if args.check_only:
            # 只运行检查
            run_checker()
        elif args.merge_only:
            # 只运行合并
            run_merger()
        elif args.merge_once:
            # 执行一次合并
            run_merger_once()
        else:
            # 同时运行检查和合并
            log("启动多线程模式...")
            
            checker_thread = threading.Thread(target=run_checker, name="Checker")
            merger_thread = threading.Thread(target=run_merger, name="Merger")
            
            checker_thread.daemon = True
            merger_thread.daemon = True
            
            checker_thread.start()
            merger_thread.start()
            
            log("检查和合并模块已启动")
            log("按 Ctrl+C 停止程序")
            
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                log("\n正在停止程序...")
                
    except KeyboardInterrupt:
        log("\n程序已停止")
    except Exception as e:
        log(f"程序发生错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()