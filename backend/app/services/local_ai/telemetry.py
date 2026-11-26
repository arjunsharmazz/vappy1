"""Timing/resource metadata only. No transcripts or microphone audio are logged."""
import os
import time


def resources():
    try:
        import psutil
        parent = psutil.Process(os.getpid())
        processes = [parent, *parent.children(recursive=True)]
        rss, cpu = 0, 0
        for process in processes:
            try:
                rss += process.memory_info().rss
                t = process.cpu_times()
                cpu += t.user + t.system
            except psutil.Error:
                pass
        return {'rss_bytes': rss, 'cpu_seconds': cpu, 'at': time.perf_counter(),
                'system_available_bytes': psutil.virtual_memory().available}
    except ImportError:
        return {}


def resource_delta(before, after):
    if not before or not after:
        return {}
    elapsed = max(.001, after['at'] - before['at'])
    return {'rss_bytes': after['rss_bytes'], 'system_available_bytes': after['system_available_bytes'],
            'process_cpu_percent': max(0, (after['cpu_seconds'] - before['cpu_seconds']) / elapsed * 100)}
