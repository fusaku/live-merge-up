import os
import time
import requests
import logging
from pathlib import Path
from datetime import datetime

# ==== 配置 ====
ROOM_ID = "Haruna_Hashimoto"  # メンバー名
CHECK_INTERVAL = 60  # 秒
TS_PARENT_DIR = Path("~/Downloads/Showroom/active").expanduser()
SERVICE_NAME = "showroom-hashimoto-haruna.service"  # 录制服务名
LOG_DIR = Path("~/logs").expanduser()
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR = Path("/home/ubuntu/temp")
TEMP_DIR.mkdir(exist_ok=True)

# ==== 设置日志 ====
def setup_logger():
    log_file = LOG_DIR / f"monitor_{datetime.now().date()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

# ==== 状态 ====
last_ts_files = set()
last_folder = None

def is_live(room_id):
    url = f"https://www.showroom-live.com/api/room/status?room_url_key=48_{room_id}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        is_live_flag = data.get("is_live", False)
        started_at = data.get("started_at") if is_live_flag else None
        
        # === 保存到 /home/ubuntu/temp/is_live.txt ===
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"{now_str} | is_live={is_live_flag}\n"

        temp_file = TEMP_DIR / "is_live.tmp"
        final_file = TEMP_DIR / "is_live.txt"

        # 先写入临时文件
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)

        # 原子替换，避免读写冲突
        os.replace(temp_file, final_file)

        return is_live_flag, started_at
    except Exception as e:
        logging.error(f"获取直播状态失败: {e}")
        return False, None

def get_latest_subfolder(parent: Path):
    today_str = datetime.now().strftime("%y%m%d")  # 例如 "250807"
    folders = [f for f in parent.iterdir() if f.is_dir() and today_str in f.name]
    if not folders:
        return None
    return max(folders, key=lambda f: f.stat().st_mtime)

def has_new_ts_files(started_at_unix: int) -> bool:
    """
    检查最新文件夹中是否有 .ts 文件，并且有文件的修改时间晚于直播开始时间
    """
    folder = get_latest_subfolder(TS_PARENT_DIR)
    if folder is None:
        logging.warning("没有找到任何子文件夹")
        return False

    ts_files = list(folder.glob("*.ts"))
    if not ts_files:
        logging.warning(f"文件夹 {folder.name} 中没有任何 .ts 文件")
        return False

    txt_files = list(folder.glob("*.txt"))
    if not txt_files:
        logging.warning(f"文件夹 {folder.name} 中没有 .txt 文件")
        return True

    # 查找最近的 .ts 文件
    latest_ts = max(ts_files, key=lambda f: f.stat().st_mtime)
    latest_mtime = latest_ts.stat().st_mtime

    if latest_mtime >= started_at_unix and not txt_files:
        logging.info(f"检测到新 .ts 文件: {latest_ts.name}，时间: {time.ctime(latest_mtime)}")
        return True
    else:
        logging.warning(f"最近的 .ts 文件 {latest_ts.name} 过旧（{time.ctime(latest_mtime)}），可能录制停止")
        return False

def restart_service(service_name):
    logging.warning(f"重启服务: {service_name}")
    os.system(f"systemctl restart {service_name}")


def monitor_loop():
    logging.info(f"开始监视主播 {ROOM_ID} ...")
    while True:
        is_live_flag, started_at = is_live(ROOM_ID)

        if is_live_flag:
            logging.info(f"{ROOM_ID} 主播正在直播中...")
            if not has_new_ts_files(started_at):
                logging.warning("直播中但未检测到新 ts 文件，重启脚本")
                restart_service(SERVICE_NAME)
        else:
            logging.info(f"{ROOM_ID} 当前未直播")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    setup_logger()

    if not TS_PARENT_DIR.exists():
        logging.error(f"错误: ts 目录 {TS_PARENT_DIR} 不存在")
    else:
        monitor_loop()
