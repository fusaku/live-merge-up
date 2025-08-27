"""
GitHub Pages发布器配置文件
"""
from pathlib import Path
import os

# ==================== 路径配置 ====================

# GitHub Pages 仓库路径
GITHUB_PAGES_REPO_PATH = Path("~/fusaku.github.io").expanduser()

# videos.json 文件路径
VIDEOS_JSON_PATH = GITHUB_PAGES_REPO_PATH / "videos.json"

# 字幕文件目标目录
SUBTITLES_TARGET_DIR = GITHUB_PAGES_REPO_PATH / "subtitles"

# 字幕文件源目录根路径
SUBTITLES_SOURCE_ROOT = Path("~/Downloads/Showroom").expanduser()

# 合并后的视频文件目录
try:
    from config import OUTPUT_DIR as MERGED_VIDEOS_DIR
except ImportError:
    MERGED_VIDEOS_DIR = Path("~/Videos/merged").expanduser()

# ==================== Git 配置 ====================

# 是否启用Git自动发布
ENABLE_GIT_AUTO_PUBLISH = True

# Git提交信息模板
GIT_COMMIT_MESSAGE_TEMPLATE = "Update videos and subtitles - {date} - {count} new videos"

# Git推送到的远程分支
GIT_REMOTE_BRANCH = "main"

# Git操作超时时间（秒）
GIT_TIMEOUT = 300

# 是否在Git操作前先拉取最新代码
GIT_PULL_BEFORE_PUSH = True

# ==================== 字幕文件配置 ====================

# 支持的字幕文件扩展名
SUBTITLE_EXTENSIONS = ['.ass']

# 日期格式（用于从文件名提取日期）
DATE_FORMAT_IN_FILENAME = "%y%m%d"

# ==================== 发布行为配置 ====================

# 是否在上传完成后自动发布到GitHub Pages
ENABLE_AUTO_PUBLISH_AFTER_UPLOAD = True

# 每次发布后的延迟时间（秒）
PUBLISH_DELAY_SECONDS = 30

# ==================== 日志配置 ====================

# 是否启用详细日志
VERBOSE_LOGGING = True

# 是否启用调试模式
DEBUG_MODE = False

# ==================== 错误处理配置 ====================

# 遇到错误时是否继续处理其他文件
CONTINUE_ON_ERROR = True

# 最大重试次数（Git操作）
MAX_RETRY_ATTEMPTS = 3

