# recorder/upscaler.py

import subprocess
import logging
import os
from pathlib import Path
import time


def get_frame_rate(input_paths) -> str:
    """从原始 TS 分片采样估算帧率（仅作备用，主路径用 probe_video_info）"""
    if isinstance(input_paths, Path):
        input_paths = [input_paths]
    if not input_paths:
        return "30"

    mid = len(input_paths) // 2
    sample = input_paths[mid]

    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate,avg_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(sample)
        ], capture_output=True, text=True, timeout=30)

        lines = [l for l in result.stdout.strip().split('\n') if l and l != '0/0']

        rates = []
        for line in lines:
            if '/' in line:
                num, den = line.split('/')
                if int(den) > 0:
                    rates.append(int(num) // int(den))

        if rates:
            return str(max(rates))
    except Exception:
        pass
    return "30"


def probe_video_info(file_path: Path) -> tuple[float, int]:
    """
    用 ffprobe 精确获取视频的时长与帧率分类。

    帧率计算方式：总帧数 ÷ 时长（比直接读流头部更准确）
    帧率分类：以 45fps 为分界线，≤45 归为 30，>45 归为 60
    （Showroom 内容只有这两种物理帧率，就近归类比范围判断更健壮）

    Returns:
        (duration_seconds, fps_category)  →  例如 (498.3, 30)
        失败时返回 (0.0, 30)
    """
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1",   # 去掉 nokey=1，保留 key
            str(file_path)
        ], capture_output=True, text=True, timeout=30)

        lines = [l.strip() for l in result.stdout.strip().split('\n') if '=' in l]
        info = {line.split('=')[0]: line.split('=')[1] for line in lines}
        duration = float(info.get('duration', 0))
        nb_frames_str = info.get('nb_frames', '0')
        nb_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0

        if duration <= 0:
            logging.warning(f"⚠️ [probe] 时长为0，跳过帧率计算")
            return 0.0, 30

        fps_raw = nb_frames / duration
        fps_category = 30 if fps_raw <= 45 else 60

        logging.info(
            f"📊 [probe] 时长={duration:.2f}s  "
            f"总帧数={nb_frames}  "
            f"实测帧率={fps_raw:.2f}fps  →  分类为 {fps_category}fps"
        )
        return duration, fps_category

    except Exception as e:
        logging.warning(f"⚠️ [probe] 解析失败: {e}")
        return 0.0, 30


def _run_upscale(actual_input: Path, temp_output_path: Path, fps_category: int) -> float:
    """
    执行一次拉伸编码，返回输出文件的时长（秒）。
    失败时抛出异常。
    """
    cmd = [
        "nice", "-n", "15",
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-fflags", "+genpts",
        "-i", str(actual_input),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "18",
        "-c:a", "copy",
        "-vf", f"scale=1920:1080:flags=lanczos,fps={fps_category}",
        "-vsync", "cfr",
        "-f", "mp4",
        str(temp_output_path)
    ]
    subprocess.run(cmd, check=True, timeout=600)

    output_duration, _ = probe_video_info(temp_output_path)
    return output_duration


def upscale_file(input_path: Path, output_path: Path, fps: str = "30", is_filelist: bool = False) -> bool:
    """
    调用 ffmpeg 将输入文件拉伸到 1080p。

    流程：
      1. 预处理：将 TS 列表合并为单一 MP4（仅 is_filelist=True 时执行）
      2. probe：从合并文件计算帧率分类与时长
      3. 拉伸：按 probe 结果编码为 1080p
      4. 校验：对比输入与输出时长，差值 >1s 时自动重试一次
      5. 重试失败：写入失败日志，跳过，不阻塞后续任务
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        return True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_suffix(".temp")

    temp_combined_path = None
    actual_input = input_path

    try:
        # --- 步骤 1: 预处理（仅针对 TS 列表）---
        if is_filelist:
            temp_combined_path = output_path.parent / f"pre_merge_{int(time.time())}.mp4"
            logging.info(f"🔄 [1/3 预处理] 正在合并片段以稳定时间轴: {input_path.name}")

            merge_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(input_path),
                "-c", "copy", "-movflags", "+faststart",
                str(temp_combined_path)
            ]

            start_merge = time.time()
            subprocess.run(merge_cmd, check=True, timeout=300)
            logging.info(f"✅ [1/3 预处理] 合并成功，耗时 {time.time() - start_merge:.2f}s")
            actual_input = temp_combined_path

        # --- 步骤 2: probe 合并文件，确定帧率与基准时长 ---
        logging.info(f"🔍 [2/3 检测] 正在分析视频信息: {actual_input.name}")
        input_duration, fps_category = probe_video_info(actual_input)

        if input_duration <= 0:
            logging.error(f"❌ [检测失败] 无法获取有效时长，跳过拉伸: {actual_input.name}")
            return False

        # --- 步骤 3: 拉伸（含自动重试）---
        if temp_output_path.exists():
            temp_output_path.unlink()

        logging.info(f"🔥 [3/3 拉伸中] 正在进行 1080p 编码 ({fps_category}fps): {output_path.name}")

        start_upscale = time.time()
        output_duration = _run_upscale(actual_input, temp_output_path, fps_category)
        elapsed = time.time() - start_upscale

        # --- 步骤 4: 时长校验 ---
        diff = abs(output_duration - input_duration)
        logging.info(
            f"⏱ [时长校验] 输入={input_duration:.2f}s  "
            f"输出={output_duration:.2f}s  "
            f"差值={diff:.2f}s  {'✅ 正常' if diff <= 1.0 else '⚠️ 异常'}"
        )

        if diff > 1.0:
            logging.warning(f"🔁 [重试] 时长差值 {diff:.2f}s 超过阈值，自动重试一次...")
            if temp_output_path.exists():
                temp_output_path.unlink()

            start_retry = time.time()
            output_duration_retry = _run_upscale(actual_input, temp_output_path, fps_category)
            diff_retry = abs(output_duration_retry - input_duration)

            logging.info(
                f"⏱ [重试校验] 输入={input_duration:.2f}s  "
                f"输出={output_duration_retry:.2f}s  "
                f"差值={diff_retry:.2f}s  {'✅ 正常' if diff_retry <= 1.0 else '❌ 仍异常'}"
            )

            if diff_retry > 1.0:
                logging.error(
                    f"❌ [最终失败] {output_path.name} 重试后时长差值仍为 {diff_retry:.2f}s，"
                    f"已跳过，请人工检查源文件"
                )
                if temp_output_path.exists():
                    temp_output_path.unlink()
                return False

            elapsed = time.time() - start_retry

        # 原子重命名
        os.rename(temp_output_path, output_path)
        logging.info(f"✨ [任务完成] 成功产出: {output_path.name}，编码耗时 {elapsed:.2f}s")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ [FFmpeg 报错] 任务 {input_path.name} 失败。返回码: {e.returncode}")
        if temp_output_path.exists():
            temp_output_path.unlink()
        return False

    except Exception as e:
        logging.error(f"❌ [未知错误] {str(e)}")
        if temp_output_path.exists():
            temp_output_path.unlink()
        return False

    finally:
        # --- 清理临时中间文件 ---
        if temp_combined_path and temp_combined_path.exists():
            try:
                temp_combined_path.unlink()
                logging.debug(f"🧹 已清理临时中间文件")
            except Exception as e:
                logging.warning(f"⚠️ 清理临时文件失败: {e}")