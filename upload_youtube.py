import pickle
import time
import fcntl
import os
import shutil
import json

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from github_pages_publisher import publish_to_github_pages
from config import *

# 全局变量
LAST_QUOTA_EXHAUSTED_DATE = None
JST = ZoneInfo("Asia/Tokyo")
PACIFIC = ZoneInfo("America/Los_Angeles")

# 加载成员配置
def load_members_config():
    """从 members.json 加载成员配置"""
    try:
        with open(MEMBERS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('members', [])
    except Exception as e:
        if DEBUG_MODE:
            log(f"加载 members.json 失败: {e}")
        return []

# 全局成员列表
MEMBERS = load_members_config()

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

def convert_title_to_japanese(title: str) -> str:
    """
    将标题中的英文名字转换为日文名字
    
    Args:
        title: 原始标题
    
    Returns:
        转换后的标题
    """
    converted_title = title
    
    # 遍历所有成员，进行名字转换
    for member in MEMBERS:
        en_name = member.get('name_en', '')
        jp_name = member.get('name_jp', '')
        
        if en_name and jp_name:
            # 将英文名替换为日文名
            converted_title = converted_title.replace(en_name, jp_name)
    
    if DEBUG_MODE and converted_title != title:
        log(f"标题转换: {title} -> {converted_title}")
    
    return converted_title

def get_today_utc_date_str():
    """获取今天的UTC日期字符串"""
    return datetime.utcnow().strftime("%Y-%m-%d")

def get_next_retry_time_japan():
    """获取下次重试时间（太平洋时间0点对应的日本时间）"""
    if not YOUTUBE_ENABLE_QUOTA_MANAGEMENT:
        return "配额管理已禁用"
    
    # 下一个太平洋时间配额重置时间 => 对应的日本时间
    now_pacific = datetime.now(PACIFIC)
    next_reset_pacific = now_pacific.replace(
        hour=YOUTUBE_QUOTA_RESET_HOUR_PACIFIC, 
        minute=0, 
        second=0, 
        microsecond=0
    )
    
    # 如果今天的重置时间已过，则选择明天
    if now_pacific >= next_reset_pacific:
        next_reset_pacific += timedelta(days=1)

    next_reset_in_japan = next_reset_pacific.astimezone(JST)
    return next_reset_in_japan.strftime("%Y-%m-%d %H:%M:%S")

def get_authenticated_service():
    """获取已认证的YouTube服务对象"""
    creds = None
    
    # 加载已保存的凭据
    if YOUTUBE_TOKEN_PATH.exists():
        try:
            with open(YOUTUBE_TOKEN_PATH, "rb") as token_file:
                creds = pickle.load(token_file)
        except Exception as e:
            if DEBUG_MODE:
                log(f"加载token失败: {e}")
            creds = None

    # 检查凭据是否有效
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                if DEBUG_MODE:
                    log(f"刷新token失败: {e}")
                creds = None
        
        # 如果凭据无效，重新认证
        if not creds:
            if not YOUTUBE_CLIENT_SECRET_PATH.exists():
                raise FileNotFoundError(f"客户端密钥文件不存在: {YOUTUBE_CLIENT_SECRET_PATH}")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(YOUTUBE_CLIENT_SECRET_PATH), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 保存凭据
        try:
            with open(YOUTUBE_TOKEN_PATH, "wb") as token_file:
                pickle.dump(creds, token_file)
        except Exception as e:
            if DEBUG_MODE:
                log(f"保存token失败: {e}")

    return build("youtube", "v3", credentials=creds)

def get_authenticated_service_alt():
    """获取副账号的已认证YouTube服务对象"""
    creds = None
    
    # 加载已保存的凭据
    if YOUTUBE_TOKEN_PATH_ALT.exists():
        try:
            with open(YOUTUBE_TOKEN_PATH_ALT, "rb") as token_file:
                creds = pickle.load(token_file)
        except Exception as e:
            if DEBUG_MODE:
                log(f"加载副账号token失败: {e}")
            creds = None

    # 检查凭据是否有效
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                if DEBUG_MODE:
                    log(f"刷新副账号token失败: {e}")
                creds = None
        
        # 如果凭据无效,重新认证
        if not creds:
            if not YOUTUBE_CLIENT_SECRET_PATH_ALT.exists():
                raise FileNotFoundError(f"副账号客户端密钥文件不存在: {YOUTUBE_CLIENT_SECRET_PATH_ALT}")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(YOUTUBE_CLIENT_SECRET_PATH_ALT), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 保存凭据
        try:
            YOUTUBE_TOKEN_PATH_ALT.parent.mkdir(parents=True, exist_ok=True)
            with open(YOUTUBE_TOKEN_PATH_ALT, "wb") as token_file:
                pickle.dump(creds, token_file)
        except Exception as e:
            if DEBUG_MODE:
                log(f"保存副账号token失败: {e}")

    return build("youtube", "v3", credentials=creds)

def is_uploaded(file_path: Path) -> bool:
    """检查文件是否已上传"""
    uploaded_flag = file_path.with_suffix(file_path.suffix + ".uploaded")
    return uploaded_flag.exists()

def mark_as_uploaded(file_path: Path, video_id: str):
    """标记文件为已上传并保存视频ID"""
    uploaded_flag = file_path.with_suffix(file_path.suffix + ".uploaded")
    
    # 将视频ID写入.uploaded文件
    with open(uploaded_flag, 'w', encoding='utf-8') as f:
        f.write(video_id)

def handle_post_upload_actions(file_path: Path):
    """处理上传完成后的操作"""
    if YOUTUBE_DELETE_AFTER_UPLOAD:
        try:
            file_path.unlink()
            if VERBOSE_LOGGING:
                log(f"已删除本地文件: {file_path.name}")
        except Exception as e:
            log(f"删除文件失败: {e}")
    
    elif YOUTUBE_MOVE_AFTER_UPLOAD:
        try:
            # 确保备份目录存在
            YOUTUBE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            
            backup_path = YOUTUBE_BACKUP_DIR / file_path.name
            # 如果备份文件已存在，添加时间戳
            if backup_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = YOUTUBE_BACKUP_DIR / f"{file_path.stem}_{timestamp}{file_path.suffix}"
            
            shutil.move(str(file_path), str(backup_path))
            if VERBOSE_LOGGING:
                log(f"已移动文件到备份目录: {backup_path.name}")
        except Exception as e:
            log(f"移动文件失败: {e}")

def send_upload_notification(file_name: str, video_id: str, success: bool = True):
    """发送上传完成通知"""
    if not YOUTUBE_ENABLE_NOTIFICATIONS or not YOUTUBE_NOTIFICATION_WEBHOOK_URL:
        return
    
    try:
        import requests
        
        if success:
            message = f"✅ 视频上传成功\n文件: {file_name}\n视频ID: {video_id}\n链接: https://youtu.be/{video_id}"
        else:
            message = f"❌ 视频上传失败\n文件: {file_name}"
        
        # 这里是通用的webhook格式，您可以根据具体服务调整
        payload = {"content": message}
        
        requests.post(YOUTUBE_NOTIFICATION_WEBHOOK_URL, json=payload, timeout=10)
        if VERBOSE_LOGGING:
            log(f"已发送通知: {file_name}")
    except Exception as e:
        if DEBUG_MODE:
            log(f"发送通知失败: {e}")

def add_video_to_playlist(youtube, video_id: str, playlist_id: str):
    """将视频添加到播放列表"""
    try:
        request = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        )
        response = request.execute()
        if VERBOSE_LOGGING:
            log(f"已添加视频 {video_id} 到播放列表 {playlist_id}")
        return True
    except HttpError as e:
        log(f"添加到播放列表失败: {e}")
        return False

def upload_video(
    file_path: str, 
    title: str = None, 
    description: str = None, 
    tags: list = None, 
    category_id: str = None,
    playlist_id: str = None
) -> str | None:
    """
    上传视频到YouTube
    """
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        log(f"文件不存在: {file_path}")
        return None
    
    # 判断是否是橋本陽菜的视频
    # 检查文件名中是否包含橋本陽菜的英文或日文名
    is_hashimoto = False
    for member in MEMBERS:
        if member.get('id') == 'hashimoto_haruna':
            en_name = member.get('name_en', '')
            jp_name = member.get('name_jp', '')
            
            if en_name in file_path_obj.stem or jp_name in file_path_obj.stem:
                is_hashimoto = True
                break
    
    try:
        if is_hashimoto:
            youtube = get_authenticated_service()
            if VERBOSE_LOGGING:
                log("使用主账号上传 (橋本陽菜)")
        else:
            youtube = get_authenticated_service_alt()
            if VERBOSE_LOGGING:
                log("使用副账号上传 (其他成员)")
    except Exception as e:
        log(f"获取YouTube服务失败: {e}")
        return None
    
    # 检测视频属于哪个成员,并获取其YouTube配置
    member_config = None
    for member in MEMBERS:
        en_name = member.get('name_en', '')
        jp_name = member.get('name_jp', '')

        if (en_name and en_name in file_path_obj.stem) or \
           (jp_name and jp_name in file_path_obj.stem):
            member_config = member.get('youtube', {})
            if VERBOSE_LOGGING:
                log(f"检测到成员: {jp_name or en_name}")
            break

    # 使用配置的默认值和文件名处理标题
    if title is None:
        # 优先使用成员配置的标题模板
        if member_config and member_config.get('title_template'):
            title = member_config['title_template']
        elif YOUTUBE_DEFAULT_TITLE:
            title = YOUTUBE_DEFAULT_TITLE
        else:
            # 使用文件名作为标题
            title = file_path_obj.stem

        # 应用日文名字转换
        title = convert_title_to_japanese(title)

    if description is None:
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 优先使用成员配置的描述模板
        if member_config and member_config.get('description_template'):
            description = member_config['description_template'].format(upload_time=upload_time)
        else:
            description = YOUTUBE_DEFAULT_DESCRIPTION.format(upload_time=upload_time)

    if tags is None:
        # 优先使用成员配置的标签
        if member_config and member_config.get('tags'):
            tags = member_config['tags'].copy()
        else:
            tags = YOUTUBE_DEFAULT_TAGS.copy()

    if category_id is None:
        # 优先使用成员配置的分类
        if member_config and member_config.get('category_id'):
            category_id = member_config['category_id']
        else:
            category_id = YOUTUBE_DEFAULT_CATEGORY_ID

    if playlist_id is None:
        # 优先使用成员配置的播放列表
        if member_config and member_config.get('playlist_id'):
            playlist_id = member_config['playlist_id']
            if VERBOSE_LOGGING:
                log(f"使用成员播放列表: {playlist_id}")
        else:
            playlist_id = YOUTUBE_PLAYLIST_ID
    
    # 构建上传请求
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": YOUTUBE_PRIVACY_STATUS
        },
        "madeForKids": False   # 直接声明“不是为儿童制作”
    }
    
    try:
        media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
    except Exception as e:
        log(f"创建上传请求失败: {e}")
        return None

    # 执行上传
    response = None
    try:
        log(f"开始上传: {file_path_obj.name}")
        log(f"视频标题: {title}")
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                log(f"上传进度: {progress}%")
                
    except HttpError as e:
        if e.resp.status == 403 and 'quotaExceeded' in str(e):
            log("上传配额已用尽")
            raise  # 重新抛出配额错误
        else:
            log(f"上传失败: {e}")
            return None
    except Exception as e:
        log(f"上传过程中出现错误: {e}")
        return None

    if not response:
        log("上传失败：未收到响应")
        return None

    video_id = response.get("id")
    if not video_id:
        log("上传失败：未获取到视频ID")
        return None
    
    log(f"上传完成，视频ID: {video_id}")

    # 添加到播放列表
    if playlist_id:
        add_video_to_playlist(youtube, video_id, playlist_id)

    return video_id

def handle_merged_video(mp4_path: Path) -> bool:
    """
    处理单个合并后的视频文件
    
    Args:
        mp4_path: MP4文件路径
    
    Returns:
        是否成功处理（True=成功，False=配额用尽或失败）
    """
    if is_uploaded(mp4_path):
        if VERBOSE_LOGGING:
            log(f"{mp4_path.name} 已上传，跳过")
        return True
    
    video_id = None
    
    try:
        video_id = upload_video(str(mp4_path))
    except HttpError as e:
        if e.resp.status == 403 and 'quotaExceeded' in str(e):
            log("检测到上传配额用尽，暂停上传，等待配额重置后继续。")
            return False
        else:
            log(f"上传时发生HTTP错误: {e}")
            send_upload_notification(mp4_path.name, "", False)
            return False
    except Exception as e:
        log(f"上传时发生未知错误: {e}")
        send_upload_notification(mp4_path.name, "", False)
        return False

    if video_id:
        # 获取实际使用的标题、描述和标签(用于保存上传信息)
        title = mp4_path.stem
        title = convert_title_to_japanese(title)

        # 检测成员配置
        member_config = None
        for member in MEMBERS:
            en_name = member.get('name_en', '')
            jp_name = member.get('name_jp', '')
            if (en_name and en_name in mp4_path.stem) or \
               (jp_name and jp_name in mp4_path.stem):
                member_config = member.get('youtube', {})
                break
            
        # 生成描述和标签
        upload_time_for_desc = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if member_config and member_config.get('description_template'):
            description = member_config['description_template'].format(upload_time=upload_time_for_desc)
        else:
            description = YOUTUBE_DEFAULT_DESCRIPTION.format(upload_time=upload_time_for_desc)

        if member_config and member_config.get('tags'):
            tags = member_config['tags'].copy()
        else:
            tags = YOUTUBE_DEFAULT_TAGS.copy()

        mark_as_uploaded(mp4_path, video_id)
        log(f"{mp4_path.name} 上传成功并已标记")
        
        # 发送成功通知
        send_upload_notification(mp4_path.name, video_id, True)
        # 保存上传信息（传递实际使用的上传信息）
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_upload_info(mp4_path, video_id, title, description, tags, upload_time)
        
        # 处理上传后操作
        handle_post_upload_actions(mp4_path)
        
        return True
    else:
        log(f"{mp4_path.name} 上传失败")
        send_upload_notification(mp4_path.name, "", False)
        return False

def upload_all_pending_videos(directory: Path = None):
    """
    上传目录中所有待上传的视频
    
    Args:
        directory: 包含MP4文件的目录（None时使用配置的OUTPUT_DIR）
    """
    if not ENABLE_AUTO_UPLOAD:
        if DEBUG_MODE:
            log("自动上传功能已禁用")
        return
    
    if directory is None:
        directory = OUTPUT_DIR
    
    global LAST_QUOTA_EXHAUSTED_DATE

    # 创建全局上传锁，防止多个进程同时上传
    upload_lock_file = LOCK_DIR / "upload_global.lock"
    
    with FileLock(upload_lock_file, UPLOAD_LOCK_TIMEOUT) as lock:
        if lock is None:
            if VERBOSE_LOGGING:
                log("其他进程正在上传，跳过本次上传")
            return
        
        _upload_all_pending_videos_internal(directory)

def _upload_all_pending_videos_internal(directory: Path):
    """内部上传函数，已经获得锁保护"""
    global LAST_QUOTA_EXHAUSTED_DATE

    today_str = get_today_utc_date_str()
    retry_time = get_next_retry_time_japan()

    # 检查今天是否已经配额用尽
    if YOUTUBE_ENABLE_QUOTA_MANAGEMENT and LAST_QUOTA_EXHAUSTED_DATE == today_str:
        if VERBOSE_LOGGING:
            log(f"检测到上传配额在 {today_str} 已用尽，将在日本时间 {retry_time} 后重试。")
        return

    if not directory.exists():
        log(f"目录不存在: {directory}")
        return

    if VERBOSE_LOGGING:
        log(f"扫描目录: {directory}")

    # 查找所有MP4文件
    mp4_files = sorted(directory.glob("*.mp4"))
    if VERBOSE_LOGGING:
        log(f"找到 {len(mp4_files)} 个 MP4 文件")
    
    if not mp4_files:
        if VERBOSE_LOGGING:
            log("没有找到MP4文件")
        return

    # 过滤出未上传的文件
    pending_files = []
    for mp4_file in mp4_files:
        if is_uploaded(mp4_file):
            if VERBOSE_LOGGING:
                log(f"跳过（已上传）: {mp4_file.name}")
        else:
            if VERBOSE_LOGGING:
                log(f"待上传: {mp4_file.name}")
            pending_files.append(mp4_file)

    if not pending_files:
        if VERBOSE_LOGGING:
            log("没有未上传的视频")
        return

    log(f"开始上传 {len(pending_files)} 个未上传的视频")
    
    # 逐个上传文件
    for mp4_file in pending_files:
        if VERBOSE_LOGGING:
            log(f"\n处理文件: {mp4_file.name}")
        
        success = handle_merged_video(mp4_file)
        
        if not success:
            if YOUTUBE_ENABLE_QUOTA_MANAGEMENT:
                log(f"上传配额耗尽，将在日本时间 {retry_time} 后重试")
                LAST_QUOTA_EXHAUSTED_DATE = today_str
            break
            
        # 在文件之间添加延迟，避免过于频繁的API调用
        if len(pending_files) > 1:
            time.sleep(5)
    
    log("上传任务完成")

def save_upload_info(file_path: Path, video_id: str, title: str, description: str, tags: list, upload_time: str):
    """保存上传信息到JSON文件"""
    from config import OUTPUT_DIR
    
    upload_info_file = OUTPUT_DIR / "recent_uploads.json"
    
    # 读取现有数据
    upload_data = {"uploads": []}
    if upload_info_file.exists():
        try:
            with open(upload_info_file, 'r', encoding='utf-8') as f:
                upload_data = json.load(f)
        except:
            upload_data = {"uploads": []}
    
    # 添加新的上传信息
    new_upload = {
        "filename": file_path.name,
        "video_id": video_id,
        "title": title,
        "description": description,
        "tags": tags,
        "upload_time": upload_time,
        "file_path": str(file_path)
    }
    
    upload_data["uploads"].insert(0, new_upload)  # 最新的在前面
    
    # 只保留最近50条记录
    upload_data["uploads"] = upload_data["uploads"][:50]
    
    # 保存到文件
    try:
        with open(upload_info_file, 'w', encoding='utf-8') as f:
            json.dump(upload_data, f, ensure_ascii=False, indent=2)
        if VERBOSE_LOGGING:
            log(f"上传信息已保存到: {upload_info_file}")
            publish_to_github_pages()
    except Exception as e:
        log(f"保存上传信息失败: {e}")

def main():
    """主函数，用于测试"""
    upload_all_pending_videos()

if __name__ == "__main__":
    main()