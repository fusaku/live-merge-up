from pathlib import Path

# ========================= 路径配置 =========================
PARENT_DIR = Path("~/Downloads/Showroom/active").expanduser()  # 所有直播文件夹所在目录
OUTPUT_DIR = Path("~/Videos/merged").expanduser()  # 输出合并视频和日志的目录

# ========================= 检查配置 =========================
CHECK_INTERVAL = 30  # 每次检测间隔秒数
LIVE_INACTIVE_THRESHOLD = 90  # 判定直播结束的空闲秒数
MAX_WORKERS = 1  # 并发线程数
LIVE_CHECK_INTERVAL = 60  # 直播中检查文件的间隔秒数
MIN_FILES_FOR_CHECK = 5  # 开始检查的最小文件数量
FILE_STABLE_TIME = 5  # 文件稳定时间（秒），超过这个时间没修改的文件才检查

# ========================= 智能文件夹切换检测配置 =========================
ENABLE_SMART_FOLDER_DETECTION = True  # 启用智能文件夹切换检测
FOLDER_SWITCH_EXTENDED_WAIT = True     # 检测到文件夹切换时使用延长的等待时间
EXTENDED_INACTIVE_MULTIPLIER = 1      # 延长等待时间的倍数（相对于LIVE_INACTIVE_THRESHOLD）
MIN_FOLDER_AGE_FOR_FINALIZE = 30      # 文件夹最小存在时间才能结束检查（秒）

# ========================= 多文件夹处理配置 =========================
PROCESS_ALL_FOLDERS = True  # 是否处理所有文件夹（True）还是只处理最新的（False）
MAX_CONCURRENT_FOLDERS = 5  # 最大同时处理的文件夹数量（防止内存占用过多）
FOLDER_CLEANUP_DELAY = 60  # 完成的文件夹状态保留时间（秒），防止重复处理

# ========================= 字幕合并配置 =========================
SUBTITLE_ROOT = Path("/home/ubuntu/Downloads/Showroom").expanduser() # 字幕文件根目录
SUBTITLE_SUBPATH = "AKB48/comments"  # 日期目录下的子路径
ENABLE_SUBTITLE_BASED_MERGE = True  # 是否启用基于字幕的智能合并
TEMP_MERGED_DIR = PARENT_DIR / "temp_merged"  # 临时合并文件目录
# ========================= 合并配置 =========================
MERGE_CHECK_INTERVAL = 30  # 合并检查间隔秒数

# ========================= 文件名配置 =========================
FILELIST_NAME = "filelist.txt"  # 文件列表文件名
LOG_SUFFIX = "_log.txt"  # 日志文件后缀
OUTPUT_EXTENSION = ".mp4"  # 输出视频文件扩展名

# ========================= FFmpeg 配置 =========================
FFMPEG_LOGLEVEL = "error"  # FFmpeg 日志级别 (quiet, panic, fatal, error, warning, info, verbose, debug)
FFMPEG_HIDE_BANNER = True  # 是否隐藏 FFmpeg banner

# ========================= FFprobe 配置 =========================
FFPROBE_TIMEOUT = 10  # FFprobe 检测超时时间（秒）

# ========================= 上传配置 =========================
ENABLE_AUTO_UPLOAD = True  # 是否启用自动上传功能

# ========================= 线程安全配置 =========================
LOCK_DIR = OUTPUT_DIR / ".locks"  # 锁文件目录
MERGE_LOCK_TIMEOUT = 300  # 合并锁超时时间（秒）
UPLOAD_LOCK_TIMEOUT = 600  # 上传锁超时时间（秒）

# ========================= 调试配置 =========================
DEBUG_MODE = True  # 调试模式，会输出更多信息
VERBOSE_LOGGING = True  # 详细日志模式

# ========================= YouTube API配置 =========================
# 认证文件路径
BASE_DIR = Path(__file__).parent.resolve()
#YOUTUBE_CLIENT_SECRET_PATH = BASE_DIR / "credentials" / "client_secret.json"  # OAuth2客户端密钥文件
#YOUTUBE_TOKEN_PATH = BASE_DIR / "credentials" / "youtube_token.pickle" # 访问令牌存储文件
YOUTUBE_CLIENT_SECRET_PATH = BASE_DIR / "credentials" / "autoupsr" / "client_secret.json"  # OAuth2客户端密钥文件
YOUTUBE_TOKEN_PATH = BASE_DIR / "credentials" / "autoupsr" / "youtube_token.pickle" # 访问令牌存储文件

# API权限范围
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# ========================= YouTube上传配置 =========================
EN_TO_JP = {
    "橋本 陽菜": "Hashimoto Haruna",
    # 更多映射...
}
# 视频默认设置
YOUTUBE_DEFAULT_TITLE = ""  # 默认标题（空字符串时使用文件名）
YOUTUBE_DEFAULT_DESCRIPTION = """
橋本陽菜
{upload_time}

#AKB48 #Team8 #橋本陽菜
""".strip()  # 默认描述，{upload_time}会被替换为上传时间

YOUTUBE_DEFAULT_TAGS = [
    "AKB48",
    "Team8", 
    "橋本陽菜",
    "Showroom",
]  # 默认标签

YOUTUBE_DEFAULT_CATEGORY_ID = "22"  # 默认分类ID (24=娱乐)
YOUTUBE_PRIVACY_STATUS = "unlisted"  # 隐私状态: private, public, unlisted

# 播放列表配置
YOUTUBE_PLAYLIST_ID = ""  # 播放列表ID（空字符串表示不添加到播放列表）

# ========================= YouTube上传行为配置 =========================
YOUTUBE_UPLOAD_INTERVAL = 30  # YouTube上传检查间隔（秒）
YOUTUBE_RETRY_DELAY = 300  # 上传失败重试延迟（秒）
YOUTUBE_MAX_RETRIES = 3  # 最大重试次数

# 配额管理
YOUTUBE_QUOTA_RESET_HOUR_PACIFIC = 0  # 太平洋时间配额重置小时（0表示午夜）
YOUTUBE_ENABLE_QUOTA_MANAGEMENT = True  # 是否启用配额管理

# 上传完成后的行为
YOUTUBE_DELETE_AFTER_UPLOAD = False  # 上传成功后是否删除本地文件
YOUTUBE_MOVE_AFTER_UPLOAD = False  # 上传成功后是否移动文件到备份目录
YOUTUBE_BACKUP_DIR = OUTPUT_DIR / "uploaded_backup"  # 备份目录

# ========================= YouTube通知配置 =========================
YOUTUBE_ENABLE_NOTIFICATIONS = False  # 是否启用上传完成通知
YOUTUBE_NOTIFICATION_WEBHOOK_URL = ""  # Webhook通知URL（如Discord、Slack等）