#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import re
from collections import deque

# ==============================================================================
# ===                           用户配置区 (USER CONFIG)                         ===
# ==============================================================================
PRIMARY_WIFI_SSIDS = ["", "", ""]
PRIMARY_WIFI_PASSWORD = ""
SECONDARY_WIFI_SSID = ""
SECONDARY_WIFI_PASSWORD = ""
PING_TARGET = "8.8.8.8"
FAILURE_THRESHOLD = 3
CHECK_INTERVAL = 3
SYSTEM_RESELECT_INTERVAL = 300
# ==============================================================================
# ===                        系统与高级配置 (ADVANCED)                         ===
# ==============================================================================
WIFI_INTERFACE = "en0"
PING_TIMEOUT_MS = 1500
PROFILER_TIMEOUT_S = 10
SWITCH_TIMEOUT_S = 15
LATENCY_SAMPLE_SIZE = 10
# ==============================================================================

# --- (基础函数部分与之前版本相同，此处省略以保持简洁) ---
PRIMARY_LATENCIES = deque(maxlen=LATENCY_SAMPLE_SIZE)
SECONDARY_LATENCIES = deque(maxlen=LATENCY_SAMPLE_SIZE)
def log(message, important=False):
    if important: print("=" * 60); print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"); print("=" * 60)
    else: print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
def get_current_ssid():
    try:
        result = subprocess.run(['system_profiler', 'SPAirPortDataType'], capture_output=True, text=True, timeout=PROFILER_TIMEOUT_S)
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            for i, line in enumerate(lines):
                if "Current Network Information:" in line or "当前网络信息:" in line:
                    if i + 1 < len(lines):
                        ssid = lines[i + 1].strip().rstrip(':');
                        if ssid and "Status:" not in ssid: return ssid
    except Exception: pass
    return None
def ping_test(host):
    try:
        result = subprocess.run(['ping', '-c', '1', '-W', str(PING_TIMEOUT_MS), host], capture_output=True, text=True, timeout=(PING_TIMEOUT_MS / 1000) + 1)
        if result.returncode == 0:
            match = re.search(r'time=([\d.]+)\s*ms', result.stdout);
            return float(match.group(1)) if match else 0.0
    except Exception: return None
def ensure_preferred_networks():
    log("正在检查并优化系统首选网络列表...")
    try:
        all_ssids = PRIMARY_WIFI_SSIDS + [SECONDARY_WIFI_SSID]
        for ssid in all_ssids: subprocess.run(['networksetup', '-removepreferredwirelessnetwork', WIFI_INTERFACE, ssid], capture_output=True, text=True)
        for i, ssid in enumerate(PRIMARY_WIFI_SSIDS):
            cmd = ['networksetup', '-addpreferredwirelessnetworkatindex', WIFI_INTERFACE, ssid, str(i), 'WPA2/WPA3 Personal'];
            if PRIMARY_WIFI_PASSWORD: cmd.append(PRIMARY_WIFI_PASSWORD)
            subprocess.run(cmd, capture_output=True, text=True); log(f"已将主网络 '{ssid}' 设置为优先级 {i}。")
        sec_idx = len(PRIMARY_WIFI_SSIDS); cmd = ['networksetup', '-addpreferredwirelessnetworkatindex', WIFI_INTERFACE, SECONDARY_WIFI_SSID, str(sec_idx), 'WPA2/WPA3 Personal']
        if SECONDARY_WIFI_PASSWORD: cmd.append(SECONDARY_WIFI_PASSWORD)
        subprocess.run(cmd, capture_output=True, text=True); log(f"已将备用网络 '{SECONDARY_WIFI_SSID}' 设置为优先级 {sec_idx}。")
        log("系统首选网络列表已优化。")
    except Exception as e: log(f"优化首选网络时出错: {e}")
def trigger_system_reselect():
    log("正在触发系统进行网络重选...");
    try:
        subprocess.run(['networksetup', '-setairportpower', WIFI_INTERFACE, 'off'], capture_output=True); time.sleep(2)
        subprocess.run(['networksetup', '-setairportpower', WIFI_INTERFACE, 'on'], capture_output=True); log("系统网络重选已触发，等待10秒..."); time.sleep(10)
    except Exception as e: log(f"触发系统重选时出错: {e}")
def switch_to_wifi_forcefully(ssid, password=""):
    log(f"正在强制切换到网络: {ssid}...");
    try:
        cmd = ['networksetup', '-setairportnetwork', WIFI_INTERFACE, ssid];
        if password: cmd.append(password)
        subprocess.run(cmd, capture_output=True, text=True, timeout=SWITCH_TIMEOUT_S); log(f"强制切换指令已发送。等待网络响应..."); time.sleep(10)
        return True
    except Exception as e: log(f"强制切换到 {ssid} 时发生异常: {e}"); return False


def main():
    """主循环函数 (逻辑修复 & 详细计数最终版)"""
    consecutive_failures = 0
    current_mode = 'PRIMARY'
    last_reselect_time = 0
    # --- 初始化分类计数器 ---
    gentle_successes = 0 # “先礼”成功次数
    forceful_successes = 0 # “后兵”成功次数

    log("=== 网络哨兵 v9.6 (逻辑修复 & 详细计数最终版) ===", important=True)
    ensure_preferred_networks()
    log(f"主网络列表: {', '.join(PRIMARY_WIFI_SSIDS)} (最高优先级)")
    log(f"备用网络: {SECONDARY_WIFI_SSID} (次高优先级)")
    log("监控开始...")

    while True:
        loop_start_time = time.time()
        try:
            actual_ssid = get_current_ssid()
            latency = ping_test(PING_TARGET)
            is_connected = latency is not None

            # --- 恢复：完整的状态日志打印逻辑 ---
            if is_connected:
                avg_latency_str = ""
                if actual_ssid in PRIMARY_WIFI_SSIDS:
                    PRIMARY_LATENCIES.append(latency)
                    if len(PRIMARY_LATENCIES) > 1: avg_latency_str = f" / 平均: {sum(PRIMARY_LATENCIES)/len(PRIMARY_LATENCIES):.2f}ms"
                elif actual_ssid == SECONDARY_WIFI_SSID:
                    SECONDARY_LATENCIES.append(latency)
                    if len(SECONDARY_LATENCIES) > 1: avg_latency_str = f" / 平均: {sum(SECONDARY_LATENCIES)/len(SECONDARY_LATENCIES):.2f}ms"

                latency_info = f"延迟: {latency:.2f}ms{avg_latency_str}"
                log(f"当前网络: {actual_ssid or '未知'} | 模式: {current_mode} | 状态: 正常 ({latency_info})")
            else:
                log(f"当前网络: {actual_ssid or '未连接'} | 模式: {current_mode} | 状态: 异常")

            # --- 核心逻辑 ---
            if is_connected:
                # --- 恢复：完整的网络正常时的核心逻辑 ---
                if actual_ssid in PRIMARY_WIFI_SSIDS and current_mode != 'PRIMARY':
                    log(f"检测到已连接主网络 ({actual_ssid})，模式修正为 PRIMARY。", important=True)
                    current_mode = 'PRIMARY'
                elif actual_ssid == SECONDARY_WIFI_SSID and current_mode != 'SECONDARY':
                    log("检测到已连接备用网络，模式修正为 SECONDARY。", important=True)
                    current_mode = 'SECONDARY'

                consecutive_failures = 0

                if current_mode == 'SECONDARY':
                    if time.time() - last_reselect_time > SYSTEM_RESELECT_INTERVAL:
                        trigger_system_reselect()
                        last_reselect_time = time.time()
            else:
                # --- 网络异常时的逻辑 (带计数器) ---
                consecutive_failures += 1
                log(f"网络连接失败次数: {consecutive_failures}/{FAILURE_THRESHOLD}")

                if consecutive_failures >= FAILURE_THRESHOLD:
                    log(f"网络连接中断，达到切换阈值！", important=True)
                    consecutive_failures = 0
                    
                    if current_mode == 'PRIMARY':
                        target_ssid, target_password = SECONDARY_WIFI_SSID, SECONDARY_WIFI_PASSWORD
                    else:
                        target_ssid, target_password = PRIMARY_WIFI_SSIDS[0], PRIMARY_WIFI_PASSWORD
                    
                    log(f"当前模式为 {current_mode}，将尝试切换到 {target_ssid}...")
                    log("第一步: 尝试通过系统引导进行切换...")
                    trigger_system_reselect()
                    
                    time.sleep(5)
                    new_ssid = get_current_ssid()
                    if new_ssid == target_ssid and ping_test(PING_TARGET) is not None:
                        log("系统引导切换成功！")
                        gentle_successes += 1
                        total = gentle_successes + forceful_successes
                        log(f"唤醒加速器成功！累计次数: {total} (先礼: {gentle_successes}, 后兵: {forceful_successes})", important=True)
                    else:
                        log("系统引导切换失败，启动B计划：强制切换！")
                        if switch_to_wifi_forcefully(target_ssid, target_password):
                            if get_current_ssid() == target_ssid and ping_test(PING_TARGET) is not None:
                                log(f"强制切换成功！已连接到 {target_ssid}。")
                                forceful_successes += 1
                                total = gentle_successes + forceful_successes
                                log(f"唤醒加速器成功！累计次数: {total} (先礼: {gentle_successes}, 后兵: {forceful_successes})", important=True)
                            else:
                                log(f"强制切换后验证失败，请检查网络 {target_ssid}。")
                        else:
                            log("强制切换指令发送失败。")

            # --- 恢复：精确的间隔控制 ---
            work_duration = time.time() - loop_start_time
            sleep_time = CHECK_INTERVAL - work_duration
            if sleep_time > 0:
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            total_switches = gentle_successes + forceful_successes
            log("程序被用户中断。", important=True)
            log(f"本次运行期间，唤醒加速器总共成功切换 {total_switches} 次。")
            log(f"-> '先礼' 成功: {gentle_successes} 次")
            log(f"-> '后兵' 成功: {forceful_successes} 次")
            break
        except Exception as e:
            log(f"主循环发生未知错误: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
