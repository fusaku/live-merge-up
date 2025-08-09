import time
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import *

def find_all_live_folders(parent_dir: Path):
    """获取所有直播文件夹路径"""
    folders = [f for f in parent_dir.iterdir() if f.is_dir()]
    return sorted(folders, key=lambda x: x.stat().st_mtime)

def find_latest_live_folder(parent_dir: Path):
    """获取最新创建的直播文件夹路径（保持向后兼容）"""
    folders = [f for f in parent_dir.iterdir() if f.is_dir()]
    return max(folders, key=lambda x: x.stat().st_mtime, default=None)

def is_file_stable(file_path: Path, stable_time: int = FILE_STABLE_TIME):
    """检查文件是否稳定（在指定时间内没有被修改）"""
    if not file_path.exists():
        return False
    
    time_since_modified = time.time() - file_path.stat().st_mtime
    return time_since_modified > stable_time

def get_unchecked_stable_files(ts_dir: Path, checked_files: set):
    """获取未检查且稳定的ts文件"""
    ts_files = list(ts_dir.glob("*.ts"))
    unchecked_files = []
    
    for ts_file in ts_files:
        # 如果文件还没检查过且已经稳定
        if ts_file not in checked_files and is_file_stable(ts_file):
            unchecked_files.append(ts_file)
    
    return unchecked_files

def is_live_active(ts_dir: Path):
    """检查直播是否还在进行中"""
    ts_files = list(ts_dir.glob("*.ts"))
    if not ts_files:
        return False

    latest_mtime = max(f.stat().st_mtime for f in ts_files)
    seconds_since_last_update = time.time() - latest_mtime
    return seconds_since_last_update <= LIVE_INACTIVE_THRESHOLD

def is_newer_folder_active(ts_dir: Path, all_folders: list):
    """
    检查是否有更新的文件夹正在活跃
    这个函数帮助判断当前文件夹是否因为录制切换到新文件夹而变得不活跃
    """
    if not ENABLE_SMART_FOLDER_DETECTION:
        return False, None
        
    current_dir_mtime = ts_dir.stat().st_mtime
    
    for folder in all_folders:
        # 跳过当前文件夹
        if folder == ts_dir:
            continue
            
        # 如果找到比当前文件夹更新的活跃文件夹
        if folder.stat().st_mtime > current_dir_mtime:
            if is_live_active(folder):
                return True, folder
    
    return False, None

def should_finalize_folder(ts_dir: Path, all_folders: list, folder_states: dict):
    """
    智能判断是否应该结束文件夹的检查
    考虑多种因素：
    1. 文件夹本身的活跃状态
    2. 是否有更新的活跃文件夹
    3. 文件夹的"冷却期"
    4. 文件夹最小存在时间
    """
    current_time = time.time()
    
    # 基本检查：如果文件夹仍然活跃，不要结束
    if is_live_active(ts_dir):
        return False, "文件夹仍在活跃中"
    
    # 检查文件夹最小存在时间
    state = folder_states.get(ts_dir, {})
    creation_time = state.get('creation_time', current_time)
    folder_age = current_time - creation_time
    
    if folder_age < MIN_FOLDER_AGE_FOR_FINALIZE:
        return False, f"文件夹创建时间过短 ({folder_age:.0f}/{MIN_FOLDER_AGE_FOR_FINALIZE} 秒)"
    
    # 检查是否有更新的活跃文件夹
    has_newer_active, newer_folder = is_newer_folder_active(ts_dir, all_folders)
    
    # 获取文件夹状态
    last_activity_time = state.get('last_activity_time', 0)
    
    # 更新最后活跃时间
    ts_files = list(ts_dir.glob("*.ts"))
    if ts_files:
        latest_mtime = max(f.stat().st_mtime for f in ts_files)
        if latest_mtime > last_activity_time:
            folder_states[ts_dir]['last_activity_time'] = latest_mtime
            last_activity_time = latest_mtime
    
    # 计算文件夹不活跃的时间
    inactive_duration = current_time - last_activity_time
    
    # 如果有更新的活跃文件夹，并且当前文件夹已经不活跃足够长时间
    if has_newer_active:
        # 对于有新文件夹的情况，使用更长的等待时间确保文件传输完成
        if FOLDER_SWITCH_EXTENDED_WAIT:
            extended_threshold = LIVE_INACTIVE_THRESHOLD * (1 + EXTENDED_INACTIVE_MULTIPLIER)
        else:
            extended_threshold = LIVE_INACTIVE_THRESHOLD
            
        if inactive_duration > extended_threshold:
            return True, f"检测到更新的活跃文件夹 {newer_folder.name}，当前文件夹已不活跃 {inactive_duration:.0f} 秒"
        else:
            return False, f"等待文件夹彻底结束 (已等待 {inactive_duration:.0f}/{extended_threshold} 秒)"
    
    # 如果没有更新的活跃文件夹，使用标准阈值
    if inactive_duration > LIVE_INACTIVE_THRESHOLD:
        return True, f"文件夹已不活跃 {inactive_duration:.0f} 秒，无其他活跃文件夹"
    
    return False, f"等待文件夹结束 (已等待 {inactive_duration:.0f}/{LIVE_INACTIVE_THRESHOLD} 秒)"

def has_been_merged(ts_dir: Path):
    """判断该直播是否已经合并过"""
    return (ts_dir / FILELIST_NAME).exists()

def has_files_to_check(ts_dir: Path):
    """检查文件夹是否有足够的文件可以开始检查"""
    ts_files = list(ts_dir.glob("*.ts"))
    return len(ts_files) >= MIN_FILES_FOR_CHECK

def check_live_folder_incremental(ts_dir: Path, checked_files: set, valid_files: list, error_logs: list):
    """增量检查直播文件夹中的新文件"""
    base_name = ts_dir.name
    
    # 获取未检查且稳定的文件
    unchecked_files = get_unchecked_stable_files(ts_dir, checked_files)
    
    if not unchecked_files:
        return
    
    if DEBUG_MODE or VERBOSE_LOGGING:
        print(f"[{base_name}] 发现 {len(unchecked_files)} 个新的稳定文件需要检查")
    
    # 检查新文件
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_ts_file, f): f for f in unchecked_files}
        for future in as_completed(futures):
            ts_file = futures[future]
            valid_file, err_msg = future.result()
            
            # 标记为已检查
            checked_files.add(ts_file)
            
            if valid_file:
                valid_files.append(valid_file)
                if DEBUG_MODE:
                    print(f"[{base_name}] ✓ {ts_file.name}")
            if err_msg:
                print(f"[{base_name}] {err_msg}")
                error_logs.append(err_msg)

def finalize_live_check(ts_dir: Path, checked_files: set, valid_files: list, error_logs: list):
    """直播结束后的最终检查和文件列表生成"""
    base_name = ts_dir.name
    filelist_txt = ts_dir / FILELIST_NAME
    log_file = OUTPUT_DIR / f"{base_name}{LOG_SUFFIX}"
    
    # 检查剩余未检查的文件（包括不稳定的）
    ts_files = list(ts_dir.glob("*.ts"))
    unchecked_files = [f for f in ts_files if f not in checked_files]
    
    if unchecked_files:
        print(f"[{base_name}] 最终检查剩余 {len(unchecked_files)} 个文件")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(check_ts_file, f): f for f in unchecked_files}
            for future in as_completed(futures):
                ts_file = futures[future]
                valid_file, err_msg = future.result()
                
                if valid_file:
                    valid_files.append(valid_file)
                if err_msg:
                    print(f"[{base_name}] {err_msg}")
                    error_logs.append(err_msg)
    
    if not valid_files:
        print(f"[{base_name}] 没有有效的 .ts 文件")
        return False
    
    # 按文件名排序
    valid_files.sort()
    
    # 写 filelist.txt
    with open(filelist_txt, "w", encoding="utf-8") as f:
        for vf in valid_files:
            f.write(f"file '{vf.resolve()}'\n")
    
    print(f"[{base_name}] 检查完成，共 {len(valid_files)} 个有效文件")
    
    # 写日志文件
    if error_logs:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as logf:
            logf.write(f"检测时间：{datetime.now()}\n")
            logf.write(f"总文件数：{len(ts_files)}\n")
            logf.write(f"有效文件数：{len(valid_files)}\n")
            logf.write(f"错误文件数：{len(error_logs)}\n\n")
            logf.write("\n".join(error_logs))
        print(f"[{base_name}] 存在异常，日志写入：{log_file}")
    
    return True

def check_ts_file(ts_file: Path):
    """检测ts文件是否含视频和音频流"""
    # 构建FFprobe命令，使用配置的参数
    base_cmd = ["ffprobe"]
    
    # 添加隐藏banner选项
    if FFMPEG_HIDE_BANNER:
        base_cmd.append("-hide_banner")
    
    # 添加日志级别
    base_cmd.extend(["-v", FFMPEG_LOGLEVEL])
    
    v_cmd = base_cmd + [
        "-select_streams", "v",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(ts_file)
    ]
    a_cmd = base_cmd + [
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(ts_file)
    ]
    
    try:
        video_stream = subprocess.run(
            v_cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            timeout=FFPROBE_TIMEOUT
        ).stdout.strip()
        
        audio_stream = subprocess.run(
            a_cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            timeout=FFPROBE_TIMEOUT
        ).stdout.strip()
        
        if video_stream and audio_stream:
            return ts_file, None
        else:
            msg = f"[不同步或缺流] {ts_file.name}"
            return None, msg
    except Exception as e:
        return None, f"[错误] {ts_file.name} 检测失败: {e}"

def check_and_prepare_folder(ts_dir: Path):
    """检查文件夹中的ts文件并生成filelist.txt（兼容旧版本的函数）"""
    print(f"使用兼容模式检查 {ts_dir.name}")
    
    checked_files = set()
    valid_files = []
    error_logs = []
    
    return finalize_live_check(ts_dir, checked_files, valid_files, error_logs)

def process_single_folder(ts_dir: Path, folder_states: dict, all_folders: list, current_time: float):
    """处理单个文件夹的检查逻辑"""
    base_name = ts_dir.name
    
    # 初始化文件夹状态
    if ts_dir not in folder_states:
        folder_states[ts_dir] = {
            'checked_files': set(),
            'valid_files': [],
            'error_logs': [],
            'last_check': 0,
            'last_activity_time': 0,
            'creation_time': current_time
        }
    
    state = folder_states[ts_dir]
    
    # 检查是否已经完成检查
    if has_been_merged(ts_dir):
        if DEBUG_MODE:
            print(f"直播 {base_name} 已检查完成，跳过")
        return True  # 返回True表示该文件夹已完成
    
    # 检查文件数量是否足够开始检查
    if not has_files_to_check(ts_dir):
        if DEBUG_MODE:
            ts_count = len(list(ts_dir.glob("*.ts")))
            print(f"直播 {base_name} 文件数量不足({ts_count}/{MIN_FILES_FOR_CHECK})，等待中...")
        return False  # 返回False表示该文件夹还不能处理
    
    # 智能判断是否应该结束文件夹检查
    should_finalize, reason = should_finalize_folder(ts_dir, all_folders, folder_states)
    
    if should_finalize:
        # 直播已结束 - 最终检查
        print(f"发现已结束的直播：{base_name} ({reason})，进行最终检查...")
        success = finalize_live_check(
            ts_dir, 
            state['checked_files'], 
            state['valid_files'], 
            state['error_logs']
        )
        return success  # 返回最终检查结果
    else:
        # 直播进行中或等待中 - 增量检查稳定的文件
        if current_time - state['last_check'] >= LIVE_CHECK_INTERVAL:
            if VERBOSE_LOGGING:
                print(f"处理中：{base_name} ({reason})，进行增量检查...")
            check_live_folder_incremental(
                ts_dir, 
                state['checked_files'], 
                state['valid_files'], 
                state['error_logs']
            )
            state['last_check'] = current_time
        else:
            if DEBUG_MODE:
                remaining = LIVE_CHECK_INTERVAL - (current_time - state['last_check'])
                print(f"文件夹 {base_name} 等待 {remaining:.0f} 秒后进行下次检查 ({reason})")
        return False  # 直播还在进行中或等待中

def cleanup_old_folder_states(folder_states: dict, active_folders: list, current_time: float):
    """清理过期的文件夹状态，释放内存"""
    folders_to_remove = []
    
    for folder_path, state in folder_states.items():
        # 如果文件夹不在活动列表中，且状态保留时间超过配置的延迟
        if (folder_path not in active_folders and 
            current_time - state.get('last_check', 0) > FOLDER_CLEANUP_DELAY):
            folders_to_remove.append(folder_path)
    
    for folder_path in folders_to_remove:
        if DEBUG_MODE:
            print(f"清理过期文件夹状态: {folder_path.name}")
        del folder_states[folder_path]

def main_loop():
    """主循环：持续监听目录并检查文件"""
    print("开始监控直播文件夹...")
    
    # 用于跟踪每个文件夹的检查状态
    folder_states = {}  # {folder_path: {'checked_files': set, 'valid_files': list, 'error_logs': list, 'last_check': time, 'last_activity_time': time}}
    
    while True:
        current_time = time.time()
        
        # 获取直播文件夹
        if PROCESS_ALL_FOLDERS:
            all_folders = find_all_live_folders(PARENT_DIR)
            # 限制同时处理的文件夹数量
            if len(all_folders) > MAX_CONCURRENT_FOLDERS:
                all_folders = all_folders[-MAX_CONCURRENT_FOLDERS:]
        else:
            # 只处理最新的文件夹（保持向后兼容）
            latest_folder = find_latest_live_folder(PARENT_DIR)
            all_folders = [latest_folder] if latest_folder else []
        
        if not all_folders:
            if DEBUG_MODE:
                print("未找到直播文件夹，等待中...")
            time.sleep(CHECK_INTERVAL)
            continue
        
        if VERBOSE_LOGGING:
            print(f"发现 {len(all_folders)} 个文件夹")
        
        # 处理每个文件夹
        completed_folders = []
        active_folders = 0
        waiting_folders = 0
        
        for ts_dir in all_folders:
            try:
                result = process_single_folder(ts_dir, folder_states, all_folders, current_time)
                if result is True:
                    # 文件夹已完成，标记为待清理
                    completed_folders.append(ts_dir)
                elif result is False:
                    # 文件夹仍在处理中或等待中
                    if is_live_active(ts_dir):
                        active_folders += 1
                    else:
                        waiting_folders += 1
            except Exception as e:
                print(f"处理文件夹 {ts_dir.name} 时出错: {e}")
                continue
        
        # 清理已完成的文件夹状态（延迟清理）
        cleanup_old_folder_states(folder_states, all_folders, current_time)
        
        # 显示状态摘要
        if VERBOSE_LOGGING and (active_folders > 0 or waiting_folders > 0 or completed_folders):
            print(f"状态摘要: {active_folders} 个活动, {waiting_folders} 个等待结束, {len(completed_folders)} 个已完成")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()