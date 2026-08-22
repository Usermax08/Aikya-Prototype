import numpy as np
from scipy.signal import butter, filtfilt

def butterworth_filter(data, cutoff=5.0, fs=50.0, order=4, btype='high'):
    """
    High-pass Butterworth filter to isolate high-frequency vertical acceleration spikes.
    """
    if len(data) < 15:
        return data  # Need minimum points for filtfilt padding
    
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype=btype, analog=False)
    filtered = filtfilt(b, a, data)
    return filtered.tolist()