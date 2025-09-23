import time
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import *
from merger import merge_once
from datetime import datetime

# ========================= 文件夹操作 =========================

def find_all_live_folders(parent_dir: Path):
    """获取所有直播文件夹路径"""
    folders = []
    for f in parent_dir.iterdir():
        if f.is_dir() and not f.name.startswith("temp_"):  # 排除临时目录
            folders.append(f)
    return sorted(folders, key=lambda x: x.stat().st_mtime)


def find_latest_live_folder(parent_dir: Path):
    """获取最新创建的直播文件夹路径（保持向后兼容）"""
    folders = [f for f in parent_dir.iterdir() if f.is_dir()]
    return max(folders, key=lambda x: x.stat().st_mtime, default=None)


def has_been_merged(ts_dir: Path):
    """判断该直播是否已经合并过"""
    return (ts_dir / FILELIST_NAME).exists()


def has_files_to_check(ts_dir: Path):
    """检查文件夹是否有足够的文件可以开始检查"""
    ts_files = list(ts_dir.glob("*.ts"))
    return len(ts_files) >= MIN_FILES_FOR_CHECK


def all_folders_completed(folders):
    """检查所有文件夹是否都已完成检查（都有filelist.txt）"""
    if not folders:
        return False
    return all(has_been_merged(folder) for folder in folders)


# ========================= 文件状态检查 =========================

def is_file_stable(file_path: Path, stable_time: int = FILE_STABLE_TIME):
    """检查文件是否稳定（在指定时间内没有被修改）"""
    if not file_path.exists():
        return False
    time_since_modified = time.time() - file_path.stat().st_mtime
    return time_since_modified > stable_time


def is_live_active(ts_dir: Path):
    """检查直播是否还在进行中"""
    ts_files = list(ts_dir.glob("*.ts"))
    if not ts_files:
        return False
    
    latest_mtime = max(f.stat().st_mtime for f in ts_files)
    seconds_since_last_update = time.time() - latest_mtime
    return seconds_since_last_update <= LIVE_INACTIVE_THRESHOLD


def is_really_stream_ended(all_folders, grace_period=FINAL_INACTIVE_THRESHOLD):
    """综合判断直播是否真正结束 - 检查所有文件夹的文件活跃度"""
    current_time = time.time()
    
    for ts_dir in all_folders:
        ts_files = list(ts_dir.glob("*.ts"))
        if not ts_files:
            continue
            
        # 获取该文件夹最新文件的修改时间
        latest_mtime = max(f.stat().st_mtime for f in ts_files)
        seconds_since_last_update = current_time - latest_mtime
        
        # 如果任何文件夹的文件在宽限期内还有更新，说明可能还在录制
        if seconds_since_last_update <= grace_period:
            if DEBUG_MODE:
                log(f"文件夹 {ts_dir.name} 在 {seconds_since_last_update:.0f} 秒前还有文件更新，可能还在录制中")
            return False
    
    return True

def has_matching_subtitle_file(ts_dir: Path):
    """检查指定文件夹是否有对应的字幕文件，支持自动处理不匹配情况"""
    if not ts_dir:
        return False
    
    folder_name = ts_dir.name
    
    try:
        date_part = folder_name[:6]  # 取前6位作为日期
        # 转换为完整日期格式 250826 -> 2025-08-26
        year = "20" + date_part[:2]
        month = date_part[2:4]
        day = date_part[4:6]
        date_folder = f"{year}-{month}-{day}"
        
        # 构建字幕文件路径
        subtitle_dir = SUBTITLE_ROOT / date_folder / SUBTITLE_SUBPATH
        exact_subtitle = subtitle_dir / f"{folder_name}.ass"
        
        # 首先检查精确匹配
        if exact_subtitle.exists():
            return True
        
        # 如果精确匹配失败，查找同一天的其他字幕文件
        if subtitle_dir.exists():
            subtitle_files = list(subtitle_dir.glob(f"{date_part} Showroom*.ass"))
            if subtitle_files:
                # 找到同一天的字幕文件，自动创建软链接
                source_subtitle = subtitle_files[0]  # 取第一个匹配的
                log(f"检测到字幕文件不匹配情况:")
                log(f"  视频文件夹: {folder_name}")
                log(f"  字幕文件: {source_subtitle.name}")
                log(f"  自动创建匹配的字幕文件...")
                
                try:
                    # 创建软链接
                    exact_subtitle.symlink_to(source_subtitle)
                    log(f"✓ 成功创建软链接: {exact_subtitle.name}")
                    return True
                except Exception as e:
                    log(f"✗ 创建软链接失败: {e}")
                    return False
        
        return False
        
    except Exception as e:
        if DEBUG_MODE:
            log(f"解析文件夹日期失败: {folder_name}, 错误: {e}")
        return False

def get_earliest_active_folder(all_folders):
    """获取最早的活跃文件夹（当前录制中且有文件的文件夹中最早创建的）"""
    active_folders = []
    for folder in all_folders:
        ts_files = list(folder.glob("*.ts"))
        # 必须同时满足：有文件 + 还在录制中（文件还在活跃）
        if ts_files and is_live_active(folder):
            active_folders.append(folder)
    
    if not active_folders:
        return None
    
    # 返回创建时间最早的文件夹
    return min(active_folders, key=lambda x: x.stat().st_ctime)

def read_is_live():
    file_path = Path("/home/ubuntu/temp/is_live.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            line = f.readline().strip()  # 读第一行
        # 格式类似 "2025-08-30 00:22:15 | is_live=True"
        if "is_live=True" in line:
            return True
        else:
            return False
    except FileNotFoundError:
        return False  # 文件不存在就当作没开播
# ========================= 文件检查和处理 =========================

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


def get_unchecked_stable_files(ts_dir: Path, checked_files: set):
    """获取未检查且稳定的ts文件"""
    ts_files = list(ts_dir.glob("*.ts"))
    unchecked_files = []
    
    for ts_file in ts_files:
        # 如果文件还没检查过且已经稳定
        if ts_file not in checked_files and is_file_stable(ts_file):
            unchecked_files.append(ts_file)
    
    return unchecked_files


def check_live_folder_incremental(ts_dir: Path, checked_files: set, valid_files: list, error_logs: list):
    """增量检查直播文件夹中的新文件"""
    base_name = ts_dir.name
    
    # 获取未检查且稳定的文件
    unchecked_files = get_unchecked_stable_files(ts_dir, checked_files)
    
    if not unchecked_files:
        return
    
    if DEBUG_MODE or VERBOSE_LOGGING:
        log(f"[{base_name}] 发现 {len(unchecked_files)} 个新的稳定文件需要检查")
    
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
                    log(f"[{base_name}] ✓ {ts_file.name}")
            if err_msg:
                log(f"[{base_name}] {err_msg}")
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
        log(f"[{base_name}] 最终检查剩余 {len(unchecked_files)} 个文件")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(check_ts_file, f): f for f in unchecked_files}
            for future in as_completed(futures):
                ts_file = futures[future]
                valid_file, err_msg = future.result()
                
                if valid_file:
                    valid_files.append(valid_file)
                if err_msg:
                    log(f"[{base_name}] {err_msg}")
                    error_logs.append(err_msg)
    
    if not valid_files:
        log(f"[{base_name}] 没有有效的 .ts 文件")
        return False
    
    # 按文件名排序
    valid_files.sort()
    
    # 写 filelist.txt
    with open(filelist_txt, "w", encoding="utf-8") as f:
        for vf in valid_files:
            f.write(f"file '{vf.resolve()}'\n")
    
    log(f"[{base_name}] 检查完成，共 {len(valid_files)} 个有效文件")
    
    # 写日志文件
    if error_logs:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as logf:
            logf.write(f"检测时间：{datetime.now()}\n")
            logf.write(f"总文件数：{len(ts_files)}\n")
            logf.write(f"有效文件数：{len(valid_files)}\n")
            logf.write(f"错误文件数：{len(error_logs)}\n\n")
            logf.write("\n".join(error_logs))
        log(f"[{base_name}] 存在异常，日志写入：{log_file}")
    
    return True


# ========================= 文件夹处理逻辑 =========================

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
            'creation_time': current_time
        }
    
    state = folder_states[ts_dir]
    
    # 检查是否已经完成检查
    if has_been_merged(ts_dir):
        if DEBUG_MODE:
            log(f"直播 {base_name} 已检查完成，跳过")
        return True  # 返回True表示该文件夹已完成
    
    # 检查文件数量是否足够开始检查
    if not has_files_to_check(ts_dir):
        if DEBUG_MODE:
            ts_count = len(list(ts_dir.glob("*.ts")))
            log(f"直播 {base_name} 文件数量不足({ts_count}/{MIN_FILES_FOR_CHECK})，等待中...")
        return False  # 返回False表示该文件夹还不能处理
    
    # 直播进行中 - 增量检查稳定的文件
    if current_time - state['last_check'] >= LIVE_CHECK_INTERVAL:
        if VERBOSE_LOGGING:
            log(f"处理中：{base_name}，进行增量检查...")
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
            log(f"文件夹 {base_name} 等待 {remaining:.0f} 秒后进行下次检查")
    
    return False  # 直播还在进行中，文件夹未完成


def cleanup_old_folder_states(folder_states: dict, active_folders: list, current_time: float):
    """清理过期的文件夹状态，释放内存"""
    folders_to_remove = []
    
    for folder_path, state in folder_states.items():
        # 如果文件夹不在活动列表中，且状态保留时间超过配置的延迟
        if (folder_path not in active_folders and 
            current_time - state.get('last_check', 0) > FOLDER_CLEANUP_DELAY):
            folders_to_remove.append(folder_path)
        # 如果文件夹已经有filelist.txt，强制清理
        elif has_been_merged(folder_path):
            folders_to_remove.append(folder_path)
    
    for folder_path in folders_to_remove:
        if DEBUG_MODE:
            log(f"清理过期文件夹状态: {folder_path.name}")
        del folder_states[folder_path]

# ========================= 主循环 =========================

def main_loop():
    """主循环：持续监控目录并检查文件"""
    log("开始监控直播文件夹...")
    
    # 用于跟踪每个文件夹的检查状态
    folder_states = {}
    merge_called = False  # 防止重复调用merge
    subtitle_check_count = {}  # 记录每个文件夹的字幕检查次数
    
    while True:
        current_time = time.time()
        
        # a: 网络状态 - 检查直播状态
        is_streaming = read_is_live()
        
        # 获取直播文件夹
        if PROCESS_ALL_FOLDERS:
            all_folders = find_all_live_folders(PARENT_DIR)
            # 过滤掉已完成的文件夹
            all_folders = [f for f in all_folders if not has_been_merged(f)]
            if len(all_folders) > MAX_CONCURRENT_FOLDERS:
                all_folders = all_folders[-MAX_CONCURRENT_FOLDERS:]
        else:
            latest_folder = find_latest_live_folder(PARENT_DIR)
            if latest_folder and not has_been_merged(latest_folder):
                all_folders = [latest_folder]
            else:
                all_folders = []
        
        if not all_folders:
            if DEBUG_MODE:
                log("未找到直播文件夹，等待中...")
            time.sleep(CHECK_INTERVAL)
            continue
        
        # b: 文件活跃度 - 检查是否还有文件在更新
        files_active = not is_really_stream_ended(all_folders, FINAL_INACTIVE_THRESHOLD)
        
        # c: 字幕文件匹配 - 检查最早的活跃文件夹是否有对应字幕文件
        if files_active:
            # 文件还活跃时，检查最早的活跃文件夹
            earliest_folder = get_earliest_active_folder(all_folders)
        else:
            # 文件不活跃时，检查最早的文件夹（不管是否活跃）
            earliest_folder = min(all_folders, key=lambda x: x.stat().st_ctime) if all_folders else None
        # 字幕文件检查逻辑，支持重试机制
        if earliest_folder:
            folder_key = earliest_folder.name
            if folder_key not in subtitle_check_count:
                subtitle_check_count[folder_key] = 0
            
            subtitle_check_count[folder_key] += 1
            subtitle_exists = has_matching_subtitle_file(earliest_folder)
            
            # 如果检查了5次还没有字幕文件，判定为无字幕视频
            if not subtitle_exists and subtitle_check_count[folder_key] >= 5:
                log(f"字幕文件检查已达到 {subtitle_check_count[folder_key]} 次，判定为无字幕视频: {folder_key}")
                subtitle_exists = True  # 强制设为True，允许合并
        else:
            subtitle_exists = False
                
        # 输出当前状态用于调试
        if VERBOSE_LOGGING:
            log(f"状态检查: 网络直播={is_streaming}, 文件活跃={files_active}, 字幕存在={subtitle_exists}")
            if earliest_folder:
                log(f"最早活跃文件夹: {earliest_folder.name}")
        
        # 根据新的逻辑判断
        if is_streaming or files_active:
            # 情况1-5: 还在直播中或录制中
            log(f"直播/录制进行中，处理 {len(all_folders)} 个文件夹")
            merge_called = False  # 重置合并标志
            
            # 处理每个文件夹的检查逻辑
            completed_folders = []
            active_folders = 0
            waiting_folders = 0
            
            for ts_dir in all_folders:
                try:
                    result = process_single_folder(ts_dir, folder_states, all_folders, current_time)
                    if result is True:
                        completed_folders.append(ts_dir)
                    elif result is False:
                        if is_live_active(ts_dir):
                            active_folders += 1
                        else:
                            waiting_folders += 1
                except Exception as e:
                    log(f"处理文件夹 {ts_dir.name} 时出错: {e}")
                    continue
            
            if VERBOSE_LOGGING and (active_folders > 0 or waiting_folders > 0 or completed_folders):
                log(f"状态摘要: {active_folders} 个活动, {waiting_folders} 个等待结束, {len(completed_folders)} 个已完成")
        
        elif subtitle_exists:
            # 情况6: 直播结束，录制完成，可以合并
            log("检测到直播结束且录制完成（字幕文件已生成），开始最终检查和合并...")
            
            # 对所有文件夹进行最终检查
            for ts_dir in all_folders:
                if not has_been_merged(ts_dir) and has_files_to_check(ts_dir):
                    log(f"对已结束的直播进行最终检查: {ts_dir.name}")
                    if ts_dir not in folder_states:
                        folder_states[ts_dir] = {
                            'checked_files': set(),
                            'valid_files': [],
                            'error_logs': [],
                            'last_check': 0,
                            'creation_time': current_time
                        }

                    finalize_live_check(
                        ts_dir,
                        folder_states[ts_dir]['checked_files'],
                        folder_states[ts_dir]['valid_files'],
                        folder_states[ts_dir]['error_logs']
                    )
            
            # 检查是否所有文件夹都已完成，然后合并
            if all_folders_completed(all_folders) and not merge_called:
                log("所有文件夹检查完成，开始合并...")
                merge_once()
                merge_called = True
        
        else:
            # 情况7: 没有直播或字幕还未生成
            if DEBUG_MODE:
                log("没有检测到活跃的直播，或字幕文件尚未生成，等待中...")
            merge_called = False  # 重置合并标志
        
        # 清理过期状态
        cleanup_old_folder_states(folder_states, all_folders, current_time)
        # 清理字幕检查计数器
        folders_to_cleanup = [key for key in subtitle_check_count.keys() 
                             if not any(f.name == key for f in all_folders)]
        for key in folders_to_cleanup:
            del subtitle_check_count[key]
        
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main_loop()