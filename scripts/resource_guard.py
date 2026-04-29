import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_ram_info():
    """Returns (available_mb, total_mb, percent_used) for system RAM on Windows."""
    if os.name == 'nt':
        stat = MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_mb = stat.ullTotalPhys / (1024 * 1024)
        avail_mb = stat.ullAvailPhys / (1024 * 1024)
        percent_used = stat.dwMemoryLoad
        return avail_mb, total_mb, percent_used
    return 8000, 16000, 50 # Fallback

def get_vram_info(gpu_index=0):
    """Returns (available_mb, total_mb) for GPU VRAM using nvidia-smi."""
    try:
        cmd = [
            "nvidia-smi",
            f"--id={gpu_index}",
            "--query-gpu=memory.free,memory.total",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
        free, total = map(float, result.stdout.strip().split(','))
        return free, total
    except Exception:
        return 4000, 8000 # Fallback

def estimate_required_memory(num_images, max_image_size):
    """Very rough estimation of required VRAM and RAM in MB."""
    # VRAM depends heavily on max_image_size and patch_match window/iterations
    pixels = (max_image_size ** 2)
    vram_per_image = (pixels * 4 * 10) / (1024 * 1024) # Rough estimate
    # active set of images in patch match
    estimated_vram = min(20, num_images) * vram_per_image + 1024 
    estimated_ram = num_images * 50 + 2048 # Rough RAM estimate
    return estimated_ram, estimated_vram

def check_resources_before_dense(num_images, max_image_size, gpu_index=0, max_ram_percent=85, max_vram_percent=90):
    """Checks resources and returns (bool: is_safe, dict: adjustments, str: reason)."""
    avail_ram, total_ram, ram_percent = get_ram_info()
    avail_vram, total_vram = get_vram_info(gpu_index)
    vram_percent = 100 - (avail_vram / total_vram * 100) if total_vram > 0 else 0

    est_ram, est_vram = estimate_required_memory(num_images, max_image_size)
    
    adjustments = {}
    is_safe = True
    reasons = []

    if ram_percent > max_ram_percent or avail_ram < est_ram:
        is_safe = False
        reasons.append(f"High RAM usage ({ram_percent}%) or insufficient available ({avail_ram:.0f}MB < {est_ram:.0f}MB est).")
        adjustments['reduce_frames'] = True
    
    if vram_percent > max_vram_percent or avail_vram < est_vram:
        is_safe = False
        reasons.append(f"High VRAM usage ({vram_percent:.0f}%) or insufficient available ({avail_vram:.0f}MB < {est_vram:.0f}MB est).")
        if max_image_size > 1920:
            adjustments['max_image_size'] = 1920
        elif max_image_size > 1600:
            adjustments['max_image_size'] = 1600
            
    if not is_safe and not adjustments:
        # Fallback if already low
        adjustments['max_image_size'] = 1600
        adjustments['num_iterations'] = 7

    return is_safe, adjustments, " | ".join(reasons) if reasons else "Resources OK."

def check_colmap_error_log(log_path):
    """Parses log for specific failure signatures."""
    log_path = Path(log_path)
    if not log_path.exists():
        return "Unknown error"
    
    content = log_path.read_text(encoding='utf-8', errors='ignore')
    if "out of memory" in content.lower() or "bad_alloc" in content.lower():
        return "RAM/VRAM Out of Memory"
    if "cudaerror" in content.lower() or "cuda_error" in content.lower():
        return "CUDA Error"
    if "segmentation fault" in content.lower():
        return "Segmentation Fault"
    return "Process Failed (check logs for details)"

def prepare_dry_run_dataset(full_image_dir, dry_run_image_dir, num_images=20):
    """Copies a subset of images for a quick dry run."""
    full_image_dir = Path(full_image_dir)
    dry_run_image_dir = Path(dry_run_image_dir)
    if dry_run_image_dir.exists():
        shutil.rmtree(dry_run_image_dir)
    dry_run_image_dir.mkdir(parents=True, exist_ok=True)
    
    images = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        images.extend(full_image_dir.glob(ext))
    
    # Take evenly spaced images
    if not images:
        return 0
    
    step = max(1, len(images) // num_images)
    subset = images[::step][:num_images]
    
    for img in subset:
        shutil.copy2(img, dry_run_image_dir / img.name)
        
    return len(subset)

def enforce_frame_limit(image_dir, max_frames=180):
    """Removes images to enforce a strict limit if Level 3 fallback is hit."""
    image_dir = Path(image_dir)
    images = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        images.extend(image_dir.glob(ext))
    
    if len(images) <= max_frames:
        return len(images)
        
    images.sort()
    # Remove evenly distributed frames to hit max_frames
    to_remove = len(images) - max_frames
    step = len(images) / to_remove
    
    removed = 0
    indices_to_remove = [int(i * step) for i in range(to_remove)]
    for idx in reversed(indices_to_remove):
        if idx < len(images):
            try:
                images[idx].unlink()
                removed += 1
            except Exception:
                pass
    return len(images) - removed
