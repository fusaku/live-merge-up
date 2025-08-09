# Showroom 直播录制处理系统

一个用于自动处理 Showroom 直播录制文件的 Python 系统，支持文件检查、合并、上传到 YouTube 和发布到 GitHub Pages。

## 功能特性

### 核心功能
- **自动文件检查**: 监控录制文件夹，检测 TS 文件的音视频流完整性
- **智能合并**: 根据配置策略自动合并录制片段
- **YouTube 自动上传**: 支持自动上传到 YouTube 并管理上传配额
- **GitHub Pages 发布**: 自动更新视频列表和字幕文件到 GitHub Pages

### 高级特性
- **多文件夹并行处理**: 同时监控多个录制文件夹
- **智能文件夹切换检测**: 检测录制软件的文件夹切换行为
- **基于字幕的智能合并**: 根据字幕文件存在情况决定合并策略
- **配额管理**: YouTube API 配额智能管理，避免超限
- **直播状态监控**: 监控直播状态并在异常时重启录制服务

## 系统架构

```
├── main.py                      # 主控制器，支持多种运行模式
├── checker.py                   # 文件检查模块
├── merger.py                    # 文件合并模块
├── upload_youtube.py            # YouTube上传模块
├── github_pages_publisher.py    # GitHub Pages发布模块
├── monitor_showroom.py          # 直播状态监控模块
├── config.py                    # 主配置文件
└── github_publisher_config.py   # GitHub发布配置文件
```

## 安装要求

### 系统依赖
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install ffmpeg python3 python3-pip git

# CentOS/RHEL
sudo yum install ffmpeg python3 python3-pip git
```

### Python 依赖
```bash
pip install -r requirements.txt
```

### requirements.txt
```
google-auth>=2.0.0
google-auth-oauthlib>=0.4.0
google-api-python-client>=2.0.0
requests>=2.25.0
```

## 配置

### 1. 基础配置 (config.py)

#### 路径配置
```python
PARENT_DIR = Path("~/Downloads/Showroom/active").expanduser()  # 录制文件目录
OUTPUT_DIR = Path("~/Videos/merged").expanduser()              # 合并输出目录
```

#### 检查配置
```python
CHECK_INTERVAL = 30                    # 检测间隔(秒)
LIVE_INACTIVE_THRESHOLD = 90           # 判定直播结束的空闲时间(秒)
MAX_WORKERS = 1                        # 并发线程数
LIVE_CHECK_INTERVAL = 60               # 直播中检查间隔(秒)
FILE_STABLE_TIME = 5                   # 文件稳定时间(秒)
```

#### 智能功能配置
```python
ENABLE_SMART_FOLDER_DETECTION = True   # 启用智能文件夹切换检测
PROCESS_ALL_FOLDERS = True             # 处理所有文件夹
ENABLE_SUBTITLE_BASED_MERGE = True     # 启用基于字幕的智能合并
```

### 2. YouTube 配置

#### API 认证设置
```python
# 创建 credentials 目录并放置认证文件
YOUTUBE_CLIENT_SECRET_PATH = BASE_DIR / "credentials" / "client_secret.json"
YOUTUBE_TOKEN_PATH = BASE_DIR / "credentials" / "youtube_token.pickle"
```

#### 上传设置
```python
YOUTUBE_DEFAULT_TITLE = ""                    # 默认标题
YOUTUBE_DEFAULT_TAGS = ["AKB48", "Team8"]     # 默认标签
YOUTUBE_PRIVACY_STATUS = "unlisted"           # 隐私设置
YOUTUBE_PLAYLIST_ID = ""                      # 播放列表ID
```

### 3. GitHub Pages 配置 (github_publisher_config.py)

```python
# GitHub Pages 仓库路径
GITHUB_PAGES_REPO_PATH = Path("~/your-username.github.io").expanduser()

# 字幕文件源目录
SUBTITLES_SOURCE_ROOT = Path("~/Downloads/Showroom").expanduser()

# 启用自动发布
ENABLE_GIT_AUTO_PUBLISH = True
```

## 使用方法

### 1. 基础使用

```bash
# 同时运行检查和合并功能
python main.py

# 只运行文件检查
python main.py --check-only

# 只运行合并功能
python main.py --merge-only

# 执行一次合并检查
python main.py --merge-once
```

### 2. 服务部署

创建 systemd 服务文件 `/etc/systemd/system/showroom-processor.service`：

```ini
[Unit]
Description=Showroom Recording Processor
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 /path/to/your/project/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl enable showroom-processor
sudo systemctl start showroom-processor
```

### 3. 直播监控服务

创建监控服务 `/etc/systemd/system/showroom-monitor.service`：

```ini
[Unit]
Description=Showroom Live Monitor
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 /path/to/your/project/monitor_showroom.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

## 工作流程

### 1. 文件检查流程
1. **监控录制目录**: 扫描指定目录下的所有录制文件夹
2. **增量检查**: 对新生成的 TS 文件进行音视频流完整性检查
3. **智能判断直播状态**: 
   - 文件夹活跃状态检测
   - 智能文件夹切换检测
   - 最小文件夹存在时间验证
4. **生成文件列表**: 为完整的录制生成 `filelist.txt`

### 2. 合并处理流程
1. **扫描待合并文件**: 查找有 `filelist.txt` 但无对应 MP4 的文件夹
2. **智能合并策略**: 
   - 检查字幕文件存在情况
   - 决定单独处理还是合并处理
3. **FFmpeg 合并**: 使用 FFmpeg 的 concat 协议合并文件
4. **文件锁保护**: 防止多进程重复处理同一文件

### 3. 上传流程
1. **配额管理**: 检查 YouTube API 配额状态
2. **批量上传**: 上传所有未处理的 MP4 文件
3. **元数据处理**: 
   - 自动生成标题和描述
   - 应用标签和分类
   - 添加到指定播放列表
4. **后处理**: 标记上传完成，可选删除或移动原文件

### 4. GitHub Pages 发布流程
1. **扫描上传记录**: 从上传信息中提取视频数据
2. **更新视频列表**: 更新 `videos.json` 文件
3. **处理字幕文件**: 复制并重命名字幕文件
4. **Git 同步**: 自动提交并推送到 GitHub Pages

## 高级功能

### 智能文件夹切换检测
系统能够检测录制软件的文件夹切换行为，当检测到新的活跃文件夹时，会智能判断旧文件夹是否应该结束处理。

### 基于字幕的合并策略
- **场景**: 录制软件可能因为各种原因产生多个文件夹
- **逻辑**: 如果第一个文件夹有字幕文件，第二个没有，则将两者合并
- **好处**: 避免产生重复或不完整的视频文件

### YouTube 配额智能管理
- **配额追踪**: 自动追踪每日配额使用情况
- **时区处理**: 正确处理太平洋时间的配额重置时间
- **失败恢复**: 配额用尽时自动暂停，重置后继续

### 多进程安全
- **文件锁机制**: 使用文件锁防止多进程冲突
- **状态管理**: 维护每个文件夹的处理状态
- **内存优化**: 自动清理过期的文件夹状态

## 监控和日志

### 日志级别
```python
DEBUG_MODE = True          # 调试模式
VERBOSE_LOGGING = True     # 详细日志
```

### 日志内容
- 文件检查进度和结果
- 合并操作状态
- 上传进度和结果
- 错误和异常信息
- 配额使用情况

## 故障排除

### 常见问题

1. **FFmpeg 相关错误**
   ```bash
   # 确认 FFmpeg 安装
   ffmpeg -version
   ffprobe -version
   ```

2. **YouTube 认证问题**
   - 检查 `client_secret.json` 文件是否存在
   - 重新运行认证流程
   - 检查 API 配额限制

3. **文件权限问题**
   ```bash
   # 确保目录权限正确
   chmod 755 /path/to/directories
   chown user:group /path/to/directories
   ```

4. **Git 同步问题**
   - 检查 GitHub 仓库权限
   - 确认 SSH 密钥配置
   - 验证网络连接

### 性能优化

1. **并发设置**
   ```python
   MAX_WORKERS = 2  # 根据CPU核心数调整
   ```

2. **检查间隔**
   ```python
   CHECK_INTERVAL = 60        # 降低CPU使用
   LIVE_CHECK_INTERVAL = 120  # 减少磁盘IO
   ```

3. **文件夹限制**
   ```python
   MAX_CONCURRENT_FOLDERS = 3  # 限制同时处理的文件夹数
   ```

## 扩展开发

### 添加新的上传服务
1. 创建新的上传模块
2. 实现标准的上传接口
3. 在 `merger.py` 中集成调用

### 自定义合并策略
1. 修改 `should_merge_folders()` 函数
2. 实现自定义的判断逻辑
3. 更新配置选项

### 添加通知功能
```python
# 配置通知 webhook
YOUTUBE_ENABLE_NOTIFICATIONS = True
YOUTUBE_NOTIFICATION_WEBHOOK_URL = "your-webhook-url"
```

## 许可证

本项目使用 MIT 许可证。详见 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v2.0.0
- 添加 GitHub Pages 自动发布功能
- 智能文件夹切换检测
- 配额管理优化
- 多进程安全改进

### v1.0.0
- 基础的文件检查和合并功能
- YouTube 自动上传
- 直播状态监控
