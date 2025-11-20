import os
import time
import logging
import sys
import cx_Oracle
from pathlib import Path
from datetime import datetime
from logger_config import setup_logger
from config import (
    ENABLED_MEMBERS, 
    RESTART_CHECK_INTERVAL, 
    MIN_RESTART_INTERVAL,
    TS_PARENT_DIR,
    LOG_DIR, 
    GRACEFUL_START_DELAY,
    # 新增下面这些
    WALLET_DIR,
    DB_USER,
    DB_PASSWORD,
    DB_TABLE,
    TNS_ALIAS
)
os.environ["TNS_ADMIN"] = WALLET_DIR


"""获取Oracle数据库连接"""
try:
    # **全局变量：数据库连接**
    GLOBAL_CONN = cx_Oracle.connect(user=DB_USER, password=DB_PASSWORD, dsn=TNS_ALIAS)
    # logging.info("Oracle数据库持久连接成功建立。")
except Exception as e:
    logging.error(f"Oracle数据库连接失败，脚本退出: {e}")
    sys.exit(1)

MEMBER_ID = os.getenv("MEMBER_ID")

if MEMBER_ID:
    MEMBER = next((m for m in ENABLED_MEMBERS if m["id"] == MEMBER_ID), None)
    if not MEMBER:
        print(f"错误: 找不到成员 ID: {MEMBER_ID}")
        sys.exit(1)
else:
    MEMBER = ENABLED_MEMBERS[0]
    print(f"未指定 MEMBER_ID，使用默认成员: {MEMBER['id']}")

SERVICE_NAME = f"showroom-{MEMBER['id']}.service"

last_restart_time = 0

def read_live_status():
    """
    从数据库读取直播状态。
    使用全局持久连接 GLOBAL_CONN，因此查询后不关闭连接。
    """
    # 直接使用全局连接
    conn = GLOBAL_CONN
    
    try:
        # 使用 with 语句确保游标会被自动关闭
        with conn.cursor() as cursor:
            
            # 查询当前成员的状态
            query = f"""
                SELECT IS_LIVE, STARTED_AT
                FROM {DB_TABLE}
                WHERE MEMBER_ID = :member_id
            """
            
            # 使用绑定变量防止 SQL 注入
            cursor.execute(query, {'member_id': MEMBER['id']})
            result = cursor.fetchone()
            
            if result:
                is_live = bool(result[0])  # IS_LIVE 字段 (1=True, 0=False)
                started_at = None
                
                if is_live and result[1]:  # STARTED_AT 字段
                    # 假定 cx_Oracle 返回的是 datetime 对象
                    if isinstance(result[1], datetime):
                        started_at = int(result[1].timestamp())
                    else:
                        # 以防万一，尝试将其他类型（如数字字符串）转换为 int
                        try:
                            started_at = int(result[1])
                        except (TypeError, ValueError):
                            logging.error(f"STARTED_AT 字段类型或值错误: {result[1]}")
                            started_at = None

                logging.debug(f"从数据库读取状态: is_live={is_live}, started_at={started_at}")
                return is_live, started_at
            else:
                logging.warning(f"数据库中未找到成员 {MEMBER['id']} 的记录")
                return False, None
            
    except Exception as e:
        # 捕获查询或游标操作的错误。连接仍然保持开放状态。
        logging.error(f"从数据库读取状态失败: {e}")
        return False, None

def get_latest_subfolder(parent: Path):
    """获取当前成员的最新录制子文件夹，通过匹配日期和成员英文名"""
    
    # 获取当前监控成员的英文名用于文件夹匹配
    # 这里的 MEMBER 变量是在脚本启动时根据 MEMBER_ID 或默认值设置的
    member_name_in_folder = MEMBER.get('name_en', MEMBER['id']) 
    match_name_lower = member_name_in_folder.lower()
    
    today_str = datetime.now().strftime("%y%m%d")
    
    folders = []
    for f in parent.iterdir(): 
        if f.is_dir() and today_str in f.name:
            folder_name_lower = f.name.lower()
            
            # 【核心修改】：检查文件夹名称是否包含成员的英文名
            if match_name_lower in folder_name_lower:
                 folders.append(f)
                 
    if not folders:
        logging.warning(f"没有找到包含 {today_str} 和昵称 '{member_name_in_folder}' 的录制文件夹")
        return None
        
    # 返回最新修改时间的文件夹
    return max(folders, key=lambda f: f.stat().st_mtime)

def has_new_ts_files(started_at_unix: int) -> bool:
    """检查最新文件夹中是否有 .ts 文件，并且有文件的修改时间晚于直播开始时间"""
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

    latest_ts = max(ts_files, key=lambda f: f.stat().st_mtime)
    latest_mtime = latest_ts.stat().st_mtime

    if latest_mtime >= started_at_unix and not txt_files:
        logging.info(f"检测到新 .ts 文件: {latest_ts.name}，时间: {time.ctime(latest_mtime)}")
        return True
    else:
        logging.warning(f"最近的 .ts 文件 {latest_ts.name} 过旧（{time.ctime(latest_mtime)}），可能录制停止")
        return False

def restart_service(service_name):
    """重启服务"""
    global last_restart_time
    
    current_time = time.time()
    time_since_last = current_time - last_restart_time
    
    if time_since_last < MIN_RESTART_INTERVAL:
        wait_time = MIN_RESTART_INTERVAL - time_since_last
        logging.info(f"距离上次重启仅 {time_since_last:.0f} 秒，等待 {wait_time:.0f} 秒后再重启")
        return False
    
    logging.warning(f"执行重启服务: {service_name}")
    result = os.system(f"sudo systemctl restart {service_name}")
    
    if result == 0:
        logging.info(f"服务 {service_name} 重启成功")
        last_restart_time = current_time
        return True
    else:
        logging.error(f"服务 {service_name} 重启失败，返回码: {result}")
        return False

def restart_loop():
    logging.info(f"开始监控重启状态 (成员: {MEMBER['id']})...")
    
    while True:
        is_live, started_at = read_live_status()
        
        if is_live and started_at:
            # ✅ 新增: 计算开播时长
            current_time = time.time()
            time_since_start = current_time - started_at
            
            # ✅ 新增: 如果开播时间太短,跳过检查,等待流稳定
            if time_since_start < GRACEFUL_START_DELAY:
                logging.info(f"{MEMBER['id']} 开播仅 {time_since_start:.1f} 秒,等待流稳定(需 {GRACEFUL_START_DELAY} 秒)")
                time.sleep(RESTART_CHECK_INTERVAL)
                continue
            
            # 开播时间已足够,开始正常检查
            logging.info(f"{MEMBER['id']} 正在直播中 (已开播 {time_since_start:.1f} 秒),检查录制状态...")
            
            if not has_new_ts_files(started_at):
                logging.warning("直播中但未检测到新 ts 文件")
                restart_service(SERVICE_NAME)
            else:
                logging.info("录制正常")
        else:
            logging.debug(f"{MEMBER['id']} 当前未直播")
        
        time.sleep(RESTART_CHECK_INTERVAL)

if __name__ == "__main__":
    setup_logger(LOG_DIR, "restart_handler")
    
    if not TS_PARENT_DIR.exists():
        logging.error(f"错误: ts 目录 {TS_PARENT_DIR} 不存在")
        # 即使目录不存在，我们也要确保连接被关闭
        if 'GLOBAL_CONN' in globals() and GLOBAL_CONN:
            GLOBAL_CONN.close()
        sys.exit(1)
    
    try:
        restart_loop()
    except KeyboardInterrupt:
        logging.info("监控循环被用户中断停止。")
    except Exception as e:
        logging.critical(f"监控循环发生严重异常: {e}")
    finally:
        if 'GLOBAL_CONN' in globals() and GLOBAL_CONN:
            try:
                GLOBAL_CONN.close()
                logging.info("数据库持久连接已关闭。")
            except Exception as close_e:
                logging.error(f"关闭数据库连接失败: {close_e}")
        sys.exit(0)