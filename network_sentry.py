#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ==============================================================================
# ===                      《Mac电脑网络高可用保障》脚本                      ===
# ===        Network Sentry for macOS High Availability by Karin Tung & Gemini ===
# ==============================================================================
#
#  版本: v11.0 (最终注释完整版)
#  功能: 持续监控网络连接，在主网络中断时，按预设优先级自动切换到备用网络，
#        并在主网络恢复后，引导系统切回。同时具备唤醒宽限期等智能化功能。
#
import subprocess
import time
import re
from collections import deque

# ==============================================================================
# ===                           用户配置区 (USER CONFIG)                         ===
# ==============================================================================

# --- 您的主力Wi-Fi网络名称列表 (请按偏好顺序排列，例如5G优先，名称需精确，区分大小写) ---
# 脚本会优先尝试连接列表顶端的网络。
PRIMARY_WIFI_SSIDS = ["WIFI_NAME_1", "WIFI_NAME_5G", "WIFI_NAME_2"]

# --- 您的主力Wi-Fi网络密码 (假设所有主力网络密码相同) ---
# 如果主网络是公开的，留空即可: ""
PRIMARY_WIFI_PASSWORD = "YOUR_PRIMARY_PASSWORD"

# --- 您的备用Wi-Fi网络名称 (例如手机热点，名称需精确，区分大小写) ---
SECONDARY_WIFI_SSID = "SECONDARY_WIFI_NAME"

# --- 您的备用Wi-Fi网络密码 ---
# 如果备用网络是公开的，留空即可: ""
SECONDARY_WIFI_PASSWORD = "YOUR_SECONDARY_PASSWORD"

# --- 用来测试网络稳定性的目标地址 ---
# 8.8.8.8 是 Google 的公共DNS服务器，非常稳定。您也可以换成其他可靠的IP地址。
PING_TARGET = "8.8.8.8"

# --- 触发切换的阈值: 连续Ping失败多少次，就触发切换 ---
FAILURE_THRESHOLD = 3

# --- 常规检查间隔: 每隔多少秒，检查一次网络 ---
CHECK_INTERVAL = 3

# --- 当连接备用网络超过此时间后，触发一次主网恢复尝试 (秒) ---
SYSTEM_RESELECT_INTERVAL = 300 # 默认5分钟

# ==============================================================================
# ===                        系统与高级配置 (ADVANCED)                         ===
# ==============================================================================

# --- 您的Wi-Fi硬件接口名称 (通常是 en0, 无需修改) ---
WIFI_INTERFACE = "en0"

# --- Ping命令超时时间 (毫秒) ---
PING_TIMEOUT_MS = 1500

# --- system_profiler命令超时时间 (秒) ---
PROFILER_TIMEOUT_S = 10

# --- 切换Wi-Fi命令超时时间 (秒) ---
SWITCH_TIMEOUT_S = 15

# --- 用于计算平均延迟的样本数量 ---
LATENCY_SAMPLE_SIZE = 10

# --- 检测到从休眠唤醒后的网络“宽限期” (秒) ---
# 给系统足够的时间自行恢复网络，避免脚本过早介入。
WAKEUP_GRACE_PERIOD = 15

# --- 判断为“休眠唤醒”的时间阈值 (秒) ---
# 两次循环间隔超过此值，即判定为一次唤醒事件。应远大于CHECK_INTERVAL。
WAKEUP_DETECTION_THRESHOLD = 60

# ==============================================================================
# ===                         脚本主逻辑 (SCRIPT CORE)                         ===
# ==============================================================================

# 用于存储最近延迟的队列
PRIMARY_LATENCIES = deque(maxlen=LATENCY_SAMPLE_SIZE)
SECONDARY_LATENCIES = deque(maxlen=LATENCY_SAMPLE_SIZE)

def log(message, important=False):
    """带时间戳的日志打印函数"""
    if important:
        print("=" * 60)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        print("=" * 60)
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def get_current_ssid():
    """通过 system_profiler 获取当前Wi-Fi网络名称"""
    try:
        result = subprocess.run(
            ['system_profiler', 'SPAirPortDataType'],
            capture_output=True, text=True, timeout=PROFILER_TIMEOUT_S
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            for i, line in enumerate(lines):
                if "Current Network Information:" in line or "当前网络信息:" in line:
                    if i + 1 < len(lines):
                        ssid = lines[i + 1].strip().rstrip(':')
                        if ssid and "Status:" not in ssid:
                             return ssid
    except Exception:
        pass
    return None

def ping_test(host):
    """执行一次ping测试，返回延迟时间(ms)或None"""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(PING_TIMEOUT_MS), host],
            capture_output=True, text=True, timeout=(PING_TIMEOUT_MS / 1000) + 1
        )
        if result.returncode == 0:
            match = re.search(r'time=([\d.]+)\s*ms', result.stdout)
            return float(match.group(1)) if match else 0.0
    except Exception:
        return None

def ensure_preferred_networks():
    """确保主网络和热点网络在macOS首选网络列表的顶部"""
    log("正在检查并优化系统首选网络列表...")
    try:
        all_ssids = PRIMARY_WIFI_SSIDS + [SECONDARY_WIFI_SSID]
        for ssid in all_ssids: subprocess.run(['networksetup', '-removepreferredwirelessnetwork', WIFI_INTERFACE, ssid], capture_output=True, text=True)
        for i, ssid in enumerate(PRIMARY_WIFI_SSIDS):
            cmd = ['networksetup', '-addpreferredwirelessnetworkatindex', WIFI_INTERFACE, ssid, str(i), 'WPA2/WPA3 Personal']
            if PRIMARY_WIFI_PASSWORD: cmd.append(PRIMARY_WIFI_PASSWORD)
            subprocess.run(cmd, capture_output=True, text=True)
            log(f"已将主网络 '{ssid}' 设置为优先级 {i}。")
        sec_idx = len(PRIMARY_WIFI_SSIDS)
        cmd = ['networksetup', '-addpreferredwirelessnetworkatindex', WIFI_INTERFACE, SECONDARY_WIFI_SSID, str(sec_idx), 'WPA2/WPA3 Personal']
        if SECONDARY_WIFI_PASSWORD: cmd.append(SECONDARY_WIFI_PASSWORD)
        subprocess.run(cmd, capture_output=True, text=True)
        log(f"已将备用网络 '{SECONDARY_WIFI_SSID}' 设置为优先级 {sec_idx}。")
        log("系统首选网络列表已优化。")
    except Exception as e:
        log(f"优化首选网络时出错: {e}")

def trigger_system_reselect():
    """通过快速开关Wi-Fi，触发系统进行网络重选"""
    log("正在触发系统进行网络重选...")
    try:
        subprocess.run(['networksetup', '-setairportpower', WIFI_INTERFACE, 'off'], capture_output=True)
        time.sleep(2)
        subprocess.run(['networksetup', '-setairportpower', WIFI_INTERFACE, 'on'], capture_output=True)
        log("系统网络重选已触发，等待10秒...")
        time.sleep(10)
    except Exception as e:
        log(f"触发系统重选时出错: {e}")

def switch_to_wifi_forcefully(ssid, password=""):
    """强制切换到指定的Wi-Fi网络"""
    log(f"正在强制切换到网络: {ssid}...")
    try:
        cmd = ['networksetup', '-setairportnetwork', WIFI_INTERFACE, ssid]
        if password:
            cmd.append(password)
        subprocess.run(cmd, capture_output=True, text=True, timeout=SWITCH_TIMEOUT_S)
        log(f"强制切换指令已发送。等待网络响应...")
        time.sleep(10)
        return True
    except Exception as e:
        log(f"强制切换到 {ssid} 时发生异常: {e}")
        return False

def main():
    """主循环函数"""
    # 初始化所有状态变量和计数器
    consecutive_failures = 0
    current_mode = 'PRIMARY'
    last_reselect_time = 0
    gentle_attempts, forceful_attempts = 0, 0
    gentle_successes, forceful_successes = 0, 0
    
    log("=== 网络哨兵 v11.0 (最终注释完整版) ===", important=True)
    ensure_preferred_networks()
    log(f"主网络列表: {', '.join(PRIMARY_WIFI_SSIDS)} (按优先级)")
    log(f"备用网络: {SECONDARY_WIFI_SSID} (终极备份)")
    log("监控开始...")
    
    last_loop_time = time.time()

    while True:
        # --- 唤醒检测 ---
        current_time = time.time()
        time_since_last_loop = current_time - last_loop_time
        last_loop_time = current_time

        if time_since_last_loop > WAKEUP_DETECTION_THRESHOLD:
            log(f"检测到系统从休眠中唤醒，进入 {WAKEUP_GRACE_PERIOD}秒 网络宽限期...", important=True)
            time.sleep(WAKEUP_GRACE_PERIOD)
            log("宽限期结束，恢复正常监控。")
        
        loop_start_time = time.time()
        try:
            # --- 网络状态检查 ---
            actual_ssid = get_current_ssid()
            latency = ping_test(PING_TARGET)
            is_connected = latency is not None

            # --- 日志与状态处理 ---
            if is_connected:
                # 打印详细状态日志
                avg_latency_str = ""
                if actual_ssid in PRIMARY_WIFI_SSIDS:
                    PRIMARY_LATENCIES.append(latency)
                    if len(PRIMARY_LATENCIES) > 1: avg_latency_str = f" / 平均: {sum(PRIMARY_LATENCIES)/len(PRIMARY_LATENCIES):.2f}ms"
                elif actual_ssid == SECONDARY_WIFI_SSID:
                    SECONDARY_LATENCIES.append(latency)
                    if len(SECONDARY_LATENCIES) > 1: avg_latency_str = f" / 平均: {sum(SECONDARY_LATENCIES)/len(SECONDARY_LATENCIES):.2f}ms"
                latency_info = f"延迟: {latency:.2f}ms{avg_latency_str}"
                log(f"当前网络: {actual_ssid or '未知'} | 模式: {current_mode} | 状态: 正常 ({latency_info})")
                
                # 网络正常，重置失败计数器并修正内部状态
                consecutive_failures = 0
                if actual_ssid in PRIMARY_WIFI_SSIDS and current_mode != 'PRIMARY':
                    log(f"检测到已连接主网络 ({actual_ssid})，模式修正为 PRIMARY。", important=True)
                    current_mode = 'PRIMARY'
                elif actual_ssid == SECONDARY_WIFI_SSID and current_mode != 'SECONDARY':
                    log("检测到已连接备用网络，模式修正为 SECONDARY。", important=True)
                    current_mode = 'SECONDARY'
                    last_reselect_time = time.time()
                
                # 如果在备用网络，定时尝试恢复主网
                if current_mode == 'SECONDARY':
                    if time.time() - last_reselect_time > SYSTEM_RESELECT_INTERVAL:
                        log("已连接备用网络超过5分钟，尝试恢复主网络...", important=True)
                        trigger_system_reselect()
                        last_reselect_time = time.time()
            else:
                # 网络异常，增加失败计数
                log(f"当前网络: {actual_ssid or '未连接'} | 模式: {current_mode} | 状态: 异常")
                consecutive_failures += 1
                
                # --- 故障恢复核心逻辑 ---
                if consecutive_failures >= FAILURE_THRESHOLD:
                    log(f"网络连接中断，达到切换阈值！", important=True)
                    disconnect_time = time.time()
                    consecutive_failures = 0
                    
                    # 确定恢复目标列表
                    recovery_targets = []
                    if current_mode == 'PRIMARY':
                        other_primary_ssids = [ssid for ssid in PRIMARY_WIFI_SSIDS if ssid != actual_ssid]
                        recovery_targets.extend(other_primary_ssids)
                        recovery_targets.append(SECONDARY_WIFI_SSID)
                    else:
                        recovery_targets.extend(PRIMARY_WIFI_SSIDS)

                    # 遍历目标列表，尝试恢复
                    successful_recovery = False
                    for target_ssid in recovery_targets:
                        log(f"尝试恢复到网络: {target_ssid}...", important=True)
                        target_password = PRIMARY_WIFI_PASSWORD if target_ssid in PRIMARY_WIFI_SSIDS else SECONDARY_WIFI_PASSWORD
                        
                        # 先礼: 尝试系统引导
                        log(f"第一步 (先礼): 尝试通过系统引导进行切换到 {target_ssid}...")
                        gentle_attempts += 1
                        trigger_system_reselect()
                        time.sleep(5)
                        
                        if get_current_ssid() == target_ssid and ping_test(PING_TARGET) is not None:
                            log(f"系统引导切换成功！已连接到 {target_ssid}。")
                            gentle_successes += 1
                            successful_recovery = True
                        else:
                            # 后兵: 强制切换
                            log(f"系统引导切换失败，启动B计划 (后兵): 强制切换到 {target_ssid}！")
                            forceful_attempts += 1
                            if switch_to_wifi_forcefully(target_ssid, target_password) and get_current_ssid() == target_ssid and ping_test(PING_TARGET) is not None:
                                log(f"强制切换成功！已连接到 {target_ssid}。")
                                forceful_successes += 1
                                successful_recovery = True
                            else:
                                log(f"强制切换到 {target_ssid} 后验证失败。")
                        
                        # 如果恢复成功，则记录并跳出循环
                        if successful_recovery:
                            recovery_time = time.time()
                            recovery_duration = recovery_time - disconnect_time
                            total_success = gentle_successes + forceful_successes
                            stats_log = (f"累计成功: {total_success} (先礼: {gentle_successes}/{gentle_attempts}, "
                                         f"后兵: {forceful_successes}/{forceful_attempts})")
                            log(f"网络恢复成功！本次恢复耗时: {recovery_duration:.2f}秒。{stats_log}", important=True)
                            break
                        else:
                            log(f"尝试恢复到 {target_ssid} 失败，继续尝试下一个可用网络...", important=True)
                    
                    if not successful_recovery:
                        log("尝试了所有可用网络，均未能恢复连接！请检查网络环境。", important=True)
            
            # --- 精确的循环间隔控制 ---
            work_duration = time.time() - loop_start_time
            sleep_time = CHECK_INTERVAL - work_duration
            if sleep_time > 0:
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            # --- 退出时打印最终统计 ---
            total_success = gentle_successes + forceful_successes
            total_attempts = gentle_attempts + forceful_attempts
            log("程序被用户中断。", important=True)
            log(f"本次运行期间，脚本总共尝试介入 {total_attempts} 次, 成功 {total_success} 次。")
            log(f"-> '先礼' 尝试: {gentle_attempts} 次, 成功: {gentle_successes} 次")
            log(f"-> '后兵' 尝试: {forceful_attempts} 次, 成功: {forceful_successes} 次")
            break
        except Exception as e:
            log(f"主循环发生未知错误: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
