import time
import subprocess
from pathlib import Path
import fcntl
import os
from config import *

# 尝试导入上传模块，如果不存在则跳过
try:
    from upload_youtube import upload_all_pending_videos
    UPLOAD_AVAILABLE = True
except ImportError:
    UPLOAD_AVAILABLE = False
    print("上传模块不可用，跳过自动上传功能")

class FileLock:
    """文件锁类，防止多个进程同时处理同一个文件"""
    
    def __init__(self, lock_file_path: Path, timeout: int = 300):
        self.lock_file_path = lock_file_path
        self.timeout = timeout
        self.lock_file = None
        
    def __enter__(self):
        """获取锁"""
        # 确保锁目录存在
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            self.lock_file = open(self.lock_file_path, 'w')
            # 尝试获取排他锁
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # 写入进程信息
            self.lock_file.write(f"PID: {os.getpid()}\nTime: {time.time()}\n")
            self.lock_file.flush()
            return self
        except (OSError, IOError):
            if self.lock_file:
                self.lock_file.close()
            return None
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """释放锁"""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                # 删除锁文件
                if self.lock_file_path.exists():
                    self.lock_file_path.unlink()
            except:
                pass

def should_merge_folders(folder1: Path, folder2: Path, date_str: str = None):
    """判断两个文件夹是否应该合并（第一个有字幕，第二个没有）"""
    if not ENABLE_SUBTITLE_BASED_MERGE:
        return False
        
    if date_str is None:
        # 使用文件夹的修改时间来确定日期，而不是今天的日期
        from datetime import datetime
        folder_time = datetime.fromtimestamp(folder1.stat().st_mtime)
        date_str = folder_time.strftime("%Y-%m-%d")
    
    # 构建完整的字幕目录路径
    subtitle_dir = SUBTITLE_ROOT / date_str / SUBTITLE_SUBPATH
    sub1 = subtitle_dir / f"{folder1.name}.ass"
    sub2 = subtitle_dir / f"{folder2.name}.ass"

    if DEBUG_MODE:
        print(f"检查字幕: {sub1} ({'存在' if sub1.exists() else '不存在'})")
        print(f"检查字幕: {sub2} ({'存在' if sub2.exists() else '不存在'})")
    
    return sub1.exists() and not sub2.exists()

def create_merged_filelist(folder1: Path, folder2: Path):
    """创建合并的filelist.txt"""
    TEMP_MERGED_DIR.mkdir(parents=True, exist_ok=True)
    merged_name = f"{folder1.name}_{folder2.name}_merged"
    merged_file = TEMP_MERGED_DIR / f"{merged_name}.txt"
    
    with open(folder1 / FILELIST_NAME, 'r') as f1, \
         open(folder2 / FILELIST_NAME, 'r') as f2, \
         open(merged_file, 'w') as out:
        out.writelines(f1.readlines())
        out.writelines(f2.readlines())
    
    return merged_file, merged_name

def find_ready_folders(parent_dir: Path):
    """查找所有准备好合并的文件夹，考虑字幕合并策略"""
    folders = [f for f in parent_dir.iterdir() if f.is_dir()]
    ready_items = []  # 改为存储合并项目而不是文件夹
    
    # 先找出所有有filelist.txt但没有.mp4的文件夹
    candidate_folders = []
    for folder in folders:
        filelist_txt = folder / FILELIST_NAME
        output_file = OUTPUT_DIR / f"{folder.name}{OUTPUT_EXTENSION}"
        if filelist_txt.exists() and not output_file.exists():
            candidate_folders.append(folder)
    
    # 按时间排序
    candidate_folders.sort(key=lambda x: x.stat().st_mtime)
    
    # 应用合并策略
    i = 0
    while i < len(candidate_folders):
        current = candidate_folders[i]
        
        # 检查是否能与下一个文件夹合并
        if i + 1 < len(candidate_folders):
            next_folder = candidate_folders[i + 1]
            if should_merge_folders(current, next_folder):
                merged_file, merged_name = create_merged_filelist(current, next_folder)
                ready_items.append({
                    'type': 'merged',
                    'filelist': merged_file,
                    'name': merged_name,
                    'folders': [current, next_folder]
                })
                i += 2  # 跳过下一个
                continue
        
        # 单独处理
        ready_items.append({
            'type': 'single',
            'filelist': current / FILELIST_NAME,
            'name': current.name,
            'folders': [current]
        })
        i += 1
    
    return ready_items

def merge_item(item: dict) -> bool:
    """合并单个项目（可能是单个文件夹或合并的文件夹）"""
    name = item['name']
    filelist_txt = item['filelist']
    output_file = OUTPUT_DIR / f"{name}{OUTPUT_EXTENSION}"
    
    # 创建锁文件路径
    lock_file = LOCK_DIR / f"{name}.merge.lock"
    
    if not filelist_txt.exists():
        print(f"{name} 没有 {FILELIST_NAME}，跳过合并")
        return False

    if output_file.exists():
        print(f"跳过已合并：{name}")
        return True

    # 使用文件锁防止重复合并
    with FileLock(lock_file, MERGE_LOCK_TIMEOUT) as lock:
        if lock is None:
            print(f"{name} 正在被其他进程合并，跳过")
            return False
        
        # 再次检查文件是否存在（双重检查）
        if output_file.exists():
            print(f"跳过已合并：{name}")
            return True
        
        # 确保输出目录存在
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print(f"开始合并 {name} -> {output_file}")
        
        # 构建 FFmpeg 命令
        ffmpeg_cmd = ["ffmpeg"]
        
        if FFMPEG_HIDE_BANNER:
            ffmpeg_cmd.extend(["-hide_banner"])
        
        ffmpeg_cmd.extend([
            "-loglevel", FFMPEG_LOGLEVEL,
            "-f", "concat", "-safe", "0", "-i", str(filelist_txt),
            "-c", "copy", str(output_file)
        ])
        
        result = subprocess.run(ffmpeg_cmd)

        if result.returncode == 0:
            print(f"{name} 合并完成")
            return True
        else:
            print(f"{name} 合并失败，请检查 ffmpeg 日志")
            return False

def merge_all_ready():
    """合并所有准备好的文件夹"""
    ready_items = find_ready_folders(PARENT_DIR)
    
    if not ready_items:
        print("没有找到待合并的文件夹")
        return 0
    
    print(f"找到 {len(ready_items)} 个待合并的文件夹")
    
    success_count = 0
    for folder in ready_items:
        if merge_item(folder):
            success_count += 1

    print(f"成功合并 {success_count} 个视频")
    return success_count

def upload_if_needed(success_count):
    if success_count > 0:
        if ENABLE_AUTO_UPLOAD and UPLOAD_AVAILABLE:
            print("检测是否有已经合并,还未上传的视频")
            upload_all_pending_videos(OUTPUT_DIR)
        elif ENABLE_AUTO_UPLOAD and not UPLOAD_AVAILABLE:
            print("自动上传已启用但上传模块不可用")

def main_loop():
    """主循环：持续检查并合并准备好的视频"""
    print("开始监控待合并文件...")
    
    while True:
        success_count = merge_all_ready()
        upload_if_needed(success_count)
        time.sleep(MERGE_CHECK_INTERVAL)

def merge_once():
    """执行一次合并检查（用于脚本调用）"""
    success_count = merge_all_ready()
    upload_if_needed(success_count)

if __name__ == "__main__":
    # 可以选择运行模式
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        merge_once()
    else:
        main_loop()