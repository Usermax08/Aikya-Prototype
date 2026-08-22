import numpy as np
from scipy.signal import butter, filtfilt

def butter_highpass_filter(data, cutoff=0.3, fs=20.0, order=2):
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    return filtfilt(b, a, data)

def detect_spike(accel_window, threshold=12.5):
    if len(accel_window) < 8:
        return max([abs(x) for x in accel_window]) > threshold

    filtered = butter_highpass_filter(np.array(accel_window))
    return float(np.max(np.abs(filtered))) > threshold