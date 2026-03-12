#!/usr/bin/env python3
"""
OpenClaw 对话历史提取器
从 ~/.openclaw/agents/main/sessions/*.jsonl 中提取真实用户发言
"""

import json
import os
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
import argparse


def parse_timestamp(ts_ms):
    """将毫秒级 timestamp 转换为 Asia/Shanghai 时区的 naive datetime"""
    dt_utc_ts = ts_ms / 1000.0
    dt_sh = datetime(1970, 1, 1) + timedelta(seconds=dt_utc_ts) + timedelta(hours=8)
    return dt_sh


def extract_user_text(content_text):
    """
    从 content text 中提取真实用户发言
    跳过系统消息、heartbeat、内部事件
    """
    # 跳过系统消息
    if 'OpenClaw runtime context (internal)' in content_text:
        return None
    if 'Inter-session message' in content_text:
        return None
    if 'task completion event' in content_text:
        return None
    if 'Read HEARTBEAT.md' in content_text:
        return None
    if 'A new session was started via /new or /reset' in content_text:
        return None
    
    # 处理 Queued messages
    if '[Queued messages while agent was busy]' in content_text:
        messages = []
        # 分割每个 queued message
        parts = re.split(r'\n---\nQueued #\d+\n', content_text)
        for part in parts[1:]:  # 跳过第一个 (header)
            # 提取 [message_id: xxx]\n黄智勋: 真实消息
            m = re.search(r'\[message_id:\s*([^\]]+)\]\s*\n([^:]+):\s*(.+)', part, re.DOTALL)
            if m:
                msg_id = m.group(1).strip()
                sender = m.group(2).strip()
                text = m.group(3).strip()
                # 提取 timestamp
                ts_match = re.search(r'"timestamp":\s*"([^"]+)"', part)
                ts_str = ts_match.group(1) if ts_match else None
                messages.append({
                    'message_id': msg_id,
                    'sender': sender,
                    'text': text,
                    'timestamp_str': ts_str
                })
        return messages if messages else None
    
    # 普通消息: [message_id: xxx]\n黄智勋: 真实消息
    m = re.search(r'\[message_id:\s*([^\]]+)\]\s*\n([^:]+):\s*(.+)', content_text, re.DOTALL)
    if m:
        msg_id = m.group(1).strip()
        sender = m.group(2).strip()
        text = m.group(3).strip()
        return [{
            'message_id': msg_id,
            'sender': sender,
            'text': text,
            'timestamp_str': None
        }]
    
    return None


def parse_timestamp_str(ts_str):
    """解析 'Thu 2026-03-12 09:51 GMT+8' 格式的时间戳"""
    if not ts_str:
        return None
    try:
        # 去掉星期和时区
        parts = ts_str.split()
        if len(parts) >= 4:
            date_str = parts[1]  # 2026-03-12
            time_str = parts[2]  # 09:51
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            return dt
    except:
        pass
    return None


def load_session_key_map(sessions_json_path):
    """从 sessions.json 加载 session_key -> sessionFile 映射"""
    if not os.path.exists(sessions_json_path):
        return {}
    
    with open(sessions_json_path, 'r') as f:
        data = json.load(f)
    
    # 反向映射: sessionFile -> session_key
    file_to_key = {}
    for key, info in data.items():
        session_file = info.get('sessionFile')
        if session_file:
            file_to_key[session_file] = key
    
    return file_to_key


def now_shanghai():
    """当前 Asia/Shanghai 时间 (naive)"""
    epoch = datetime(1970, 1, 1)
    import time
    return epoch + timedelta(seconds=time.time()) + timedelta(hours=8)


def extract_messages(sessions_dir, date_filter=None, recent_days=None, all_messages=False):
    """
    提取对话消息
    date_filter: YYYYMMDD 格式，只提取该日期的消息
    recent_days: 提取最近 N 天的消息
    all_messages: 提取所有消息
    """
    sessions_json = os.path.join(sessions_dir, 'sessions.json')
    file_to_key = load_session_key_map(sessions_json)
    
    # 计算日期范围 (naive datetime, all in Asia/Shanghai)
    date_start = None
    date_end = None
    if date_filter:
        try:
            dt = datetime.strptime(date_filter, '%Y%m%d')
            date_start = dt.replace(hour=0, minute=0, second=0)
            date_end = dt.replace(hour=23, minute=59, second=59)
        except:
            print(f"Invalid date format: {date_filter}, expected YYYYMMDD", file=sys.stderr)
            return []
    elif recent_days:
        now = now_shanghai()
        date_start = now - timedelta(days=recent_days)
        date_end = now
    elif not all_messages:
        # 默认最近2天
        now = now_shanghai()
        date_start = now - timedelta(days=2)
        date_end = now
    
    messages = []
    session_files = list(Path(sessions_dir).glob('*.jsonl'))
    
    for session_file in session_files:
        session_key = file_to_key.get(str(session_file), 'unknown')
        
        # 流式处理
        with open(session_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    obj = json.loads(line)
                except:
                    continue
                
                if obj.get('type') != 'message':
                    continue
                
                msg = obj.get('message', {})
                if msg.get('role') != 'user':
                    continue
                
                # 提取 timestamp
                ts_ms = obj.get('timestamp')
                if isinstance(ts_ms, str):
                    # ISO format (e.g. "2026-03-12T01:51:49.311Z")
                    try:
                        ts_str_clean = ts_ms.replace('Z', '').split('+')[0]
                        dt_utc = datetime.strptime(ts_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                        dt = dt_utc + timedelta(hours=8)  # 转 Asia/Shanghai
                    except:
                        continue
                elif isinstance(ts_ms, (int, float)):
                    dt = parse_timestamp(ts_ms)
                else:
                    continue
                
                # 日期过滤
                if date_start and dt < date_start:
                    continue
                if date_end and dt > date_end:
                    continue
                
                # 提取 content
                content = msg.get('content', [])
                text = ''
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get('type') == 'text':
                            text = c['text']
                            break
                elif isinstance(content, str):
                    text = content
                
                if not text:
                    continue
                
                # 提取用户发言
                extracted = extract_user_text(text)
                if not extracted:
                    continue
                
                # 处理提取结果
                for item in extracted:
                    # 优先使用 metadata 中的 timestamp
                    item_dt = parse_timestamp_str(item.get('timestamp_str')) or dt
                    
                    messages.append({
                        'date': item_dt.strftime('%Y-%m-%d'),
                        'time': item_dt.strftime('%H:%M'),
                        'timestamp': item_dt.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
                        'source': 'chat',
                        'session_key': session_key,
                        'text': item['text'],
                        'message_id': item['message_id']
                    })
    
    # 按时间排序
    messages.sort(key=lambda x: x['timestamp'])
    return messages


def stats(sessions_dir):
    """统计信息"""
    session_files = list(Path(sessions_dir).glob('*.jsonl'))
    total_sessions = len(session_files)
    total_messages = 0
    total_user_messages = 0
    
    for session_file in session_files:
        with open(session_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except:
                    continue
                if obj.get('type') == 'message':
                    total_messages += 1
                    if obj.get('message', {}).get('role') == 'user':
                        total_user_messages += 1
    
    print(f"Total sessions: {total_sessions}")
    print(f"Total messages: {total_messages}")
    print(f"Total user messages: {total_user_messages}")


def main():
    parser = argparse.ArgumentParser(description='提取 OpenClaw 对话历史')
    parser.add_argument('--date', help='指定日期 (YYYYMMDD)')
    parser.add_argument('--recent', type=int, help='最近 N 天')
    parser.add_argument('--all', action='store_true', help='全量提取')
    parser.add_argument('--stats', action='store_true', help='统计信息')
    parser.add_argument('--feed-perception', action='store_true', help='输出 perception 兼容格式')
    parser.add_argument('--output', help='输出文件路径 (默认: memory/intelligence/chat_messages.jsonl)')
    
    args = parser.parse_args()
    
    sessions_dir = os.path.expanduser('~/.openclaw/agents/main/sessions')
    
    if args.stats:
        stats(sessions_dir)
        return
    
    # 提取消息
    messages = extract_messages(
        sessions_dir,
        date_filter=args.date,
        recent_days=args.recent,
        all_messages=args.all
    )
    
    # 输出
    if args.feed_perception:
        output_path = args.output or os.path.expanduser('~/.openclaw/workspace/memory/intelligence/chat_events.jsonl')
        with open(output_path, 'w') as f:
            for msg in messages:
                # 转换为 perception 格式
                perception_msg = {
                    'date': msg['date'],
                    'source': 'chat',
                    'type': 'direct_message',
                    'speaker': '饭团',  # 固定为饭团
                    'text': msg['text'],
                    'timestamp': msg['timestamp'],
                    'context': 'feishu_direct' if 'feishu:direct' in msg['session_key'] else 'other'
                }
                f.write(json.dumps(perception_msg, ensure_ascii=False) + '\n')
        print(f"Extracted {len(messages)} messages to {output_path}")
    else:
        output_path = args.output or os.path.expanduser('~/.openclaw/workspace/memory/intelligence/chat_messages.jsonl')
        with open(output_path, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        print(f"Extracted {len(messages)} messages to {output_path}")


if __name__ == '__main__':
    main()
