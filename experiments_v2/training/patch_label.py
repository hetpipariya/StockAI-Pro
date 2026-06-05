"""
experiments_v2/training/patch_label.py
Utility script (kept for historical reference only).
The label_tpsl function has been replaced by build_entry_labels()
in experiments_v2/training/train_5m.py which uses pure forward-return labels.
This file is no longer needed in production — see train_5m.py directly.
"""
print("[INFO] patch_label.py is deprecated.")
print("       Labels are now built via build_entry_labels() in train_5m.py")
print("       using pure forward-return (no TP/SL scan in label construction).")
