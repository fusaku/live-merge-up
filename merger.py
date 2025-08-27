import time
import subprocess
import fcntl
import os
from pathlib import Path
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

def find_ready_folders(parent_dir: Path):
    """查找所有准备好合并的文件夹，按名称排序合并"""
    folders = [f for f in parent_dir.iterdir() if f.is_dir()]
    
    # 找出所有有filelist.txt但没有.mp4的文件夹
    candidate_folders = []
    for folder in folders:
        # 检查是否有合并标记文件
        merged_marker = folder / ".merged"
        if merged_marker.exists():
            continue
            
        filelist_txt = folder / FILELIST_NAME
        output_file = OUTPUT_DIR / f"{folder.name}{OUTPUT_EXTENSION}"
        if filelist_txt.exists() and not output_file.exists():
            candidate_folders.append(folder)
    
    if not candidate_folders:
        return []
    
    # 按文件夹名称排序（从小到大）
    candidate_folders.sort(key=lambda x: x.name)
    
    # 创建一个合并项目，包含所有待合并的文件夹
    if len(candidate_folders) == 1:
        # 如果只有一个文件夹，直接处理
        folder = candidate_folders[0]
        return [{
            'type': 'single',
            'filelist': folder / FILELIST_NAME,
            'name': folder.name,
            'folders': [folder]
        }]
    else:
        # 如果有多个文件夹，合并成一个
        merged_name = candidate_folders[0].name  # 使用第一个文件夹的名称
        merged_filelist = create_combined_filelist(candidate_folders, merged_name)
        return [{
            'type': 'merged',
            'filelist': merged_filelist,
            'name': merged_name,
            'folders': candidate_folders
        }]

def create_combined_filelist(folders_list, merged_name):
    """创建合并的filelist.txt"""
    temp_dir = Path(OUTPUT_DIR) / ".temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    merged_file = temp_dir / f"{merged_name}_combined.txt"
    
    # 合并所有文件夹的 filelist.txt
    with open(merged_file, 'w') as out:
        for folder in folders_list:
            filelist_path = folder / FILELIST_NAME
            if filelist_path.exists():
                with open(filelist_path, 'r') as f:
                    out.writelines(f.readlines())
    
    return merged_file

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
            # 新增：为所有被合并的文件夹创建标记文件
            if item['type'] == 'merged':
                for folder in item['folders']:
                    marker_file = folder / ".merged"
                    marker_file.write_text(f"已合并到: {name}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
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
            #upload_all_pending_videos(OUTPUT_DIR)
        elif ENABLE_AUTO_UPLOAD and not UPLOAD_AVAILABLE:
            print("自动上传已启用但上传模块不可用")

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
        merge_once()