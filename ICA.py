import numpy as np
import pandas as pd
from sklearn.decomposition import FastICA
from scipy.signal import iirfilter, lfilter, windows
from pyentrp import entropy as ent
import csv
import time
import statistics
import traceback

import threading
import os
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
########################################################################

#parameters
fs = 500 #Hz
dt = 1/fs #s
# Define filter coefficients
b1 = pd.read_csv('filters/firhigh.csv').to_numpy().flatten()
#b2 = pd.read_csv('filters/firfillow.csv').to_numpy().flatten()
b2 = pd.read_csv('filters/low_60.csv').to_numpy().flatten()

nyquist = 0.5 * fs
low = 47 / nyquist
high = 53 / nyquist
b3, a3 = iirfilter(N=3, Wn=[low, high], btype='bandstop', ftype='butter')

fil = pd.read_csv('filters/iirnotch.csv', header=None)
num = fil.iloc[:, 0].to_numpy().flatten()
den = fil.iloc[:, 1].to_numpy().flatten()

######################################################################
def rep_zeros(arr):  
    # Find indices where the array is 0
    zero_indices = np.where(arr == 0)[0]
    
    # Loop through zero indices and replace each zero with the average of its neighbors
    for inx in zero_indices:
        left_neighbor = arr[inx - 1] if inx > 0 else 0
        right_neighbor = arr[inx + 1] if inx < len(arr) - 1 else 0
        avg = (left_neighbor + right_neighbor) // 2
        arr[inx] = avg
    return arr

# Function to calculate threshold
def calculate_threshold(column):
    mean = np.mean(abs(column))  # Calculate mean
    std = np.std(abs(column))    # Calculate standard deviation
    threshold = mean + 4 * std  # Set threshold as 4 standard deviations
    return threshold

# #Function to identify invalid rows
def find_invalid_rows(df, threshold_A ,threshold_B,threshold_C,threshold_D   ):
    print()
    return (abs(df['A']) > threshold_A ) | (abs(df['B']) > threshold_B) | (abs(df['C']) > threshold_C) | (abs(df['D']) > threshold_D)

# Function to replace invalid rows with interpolated values
def clean_invalid_blocks(df, threshold_A ,threshold_B,threshold_C,threshold_D):
    # Find rows with invalid values
    invalid_mask = find_invalid_rows(df, threshold_A ,threshold_B,threshold_C,threshold_D)
    invalid_indexes = df[invalid_mask].index
    #print(invalid_indexes)
    # print("Before Filtering")
    
    # Replace invalid rows with NaN
    df_cleaned = df.copy()
   
    df_cleaned.loc[invalid_mask, :] = np.nan
    
    # Interpolate missing values (linear interpolation)
    df_cleaned = df_cleaned.interpolate(method='linear', axis=0, limit_direction='both')
    df_cleaned = df_cleaned.round(0).astype(int)
    #print(df_cleaned)
    return df_cleaned,invalid_indexes

def remove_outliers(data):
    chunk_size = 300
    data_copy = data.copy()

    for i in range(0, len(data), chunk_size):
        # Define the chunk
        chunk = data_copy[i:i + chunk_size]
        
        # Calculate Q1 and Q3 manually
        sorted_chunk = np.sort(chunk)
        n = len(sorted_chunk)
        Q1 = sorted_chunk[int(0.25 * n)]  # 25th percentile
        Q3 = sorted_chunk[int(0.75 * n)]  # 75th percentile
        
        # Calculate IQR
        IQR = Q3 - Q1
        
        # Define outlier thresholds
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        # Find the indices of the outliers
        outliers_indices = np.where((chunk < lower_bound) | (chunk > upper_bound))[0]
        
        # Replace outliers while handling consecutive outliers
        for idx in outliers_indices:
            if idx == 0:
                # If the first element is an outlier, use the next valid value
                if idx + 1 not in outliers_indices:
                    chunk[idx] = chunk[idx + 1]
            elif idx == len(chunk) - 1:
                # If the last element is an outlier, use the previous valid value
                if idx - 1 not in outliers_indices:
                    chunk[idx] = chunk[idx - 1]
            else:
                # Check if neighbors are valid (not outliers)
                if (idx - 1 not in outliers_indices) and (idx + 1 not in outliers_indices):
                    # Replace with the average of neighbors if both are valid
                    chunk[idx] = (chunk[idx - 1] + chunk[idx + 1]) / 2
                elif idx - 1 not in outliers_indices:
                    # If only the previous neighbor is valid
                    chunk[idx] = chunk[idx - 1]
                elif idx + 1 not in outliers_indices:
                    # If only the next neighbor is valid
                    chunk[idx] = chunk[idx + 1]

        # Update the original data with the processed chunk
        data_copy[i:i + chunk_size] = chunk

    return data_copy

def quantized_value_to_voltage(quantized_value, v_min=-3.3, v_max=3.3, bit_depth=24):
 
    # Number of quantization levels
    num_levels = 2**bit_depth - 1  # Exclude the 0 value for signed integer representation
    
    # Step size (voltage per quantization level)
    step_size = (v_max - v_min) / num_levels
    
    # Convert quantized value back to voltage
    voltage = quantized_value * step_size + v_min
    
    return voltage*1e3

# Signal Processing Function definitions
def adt_findrpeaks(ecg_signal, threshold_ratio=0.45, refractory_period = 150, integration_window =35):
    # Differentiation
    differentiated_signal = np.diff(ecg_signal)

    # Squaring
    squared_signal = differentiated_signal ** 2
    
    window_size = integration_window*2

    window = windows.flattop(window_size)

    # Integration
    # integrated_signal = np.convolve(squared_signal, np.ones(integration_window)/integration_window, mode='same')
    # integrated_signal = np.convolve(squared_signal, window, mode='same')
    
    # Integration
    integrated_signal = np.convolve(squared_signal, np.ones(integration_window)/integration_window, mode='same')

    # Calculate adaptive thresholds
    high_threshold = threshold_ratio * np.max(integrated_signal)

    # QRS Detection
    r_indices = []
    in_refractory_period = False

    for i, value in enumerate(integrated_signal):
        if value > high_threshold and not in_refractory_period:
            r_indices.append(i)
            in_refractory_period = True

        if in_refractory_period and i - r_indices[-1] >= refractory_period:
            in_refractory_period = False
            
    return r_indices, integrated_signal, high_threshold

def correct_sign(signal):
    #signal should be a numpy array
    peak = np.max(signal)
    trough = np.min(signal)
    if np.abs(peak)< np.abs(trough):
        return -1*signal
    else:
        return signal

def make_array(variable_length_array, n):
            # Initialize the fixed-length array filled with -1
            fixed_array = [-1] * n

            # Copy elements from the original array into the fixed-length array
            for i in range(min(len(variable_length_array), n)):
                fixed_array[i] = variable_length_array[i]

            return fixed_array

def get_hrlis(signal,end_f, threshold_ratio = 0.7, refractory_period=100):
    
    pos_prev = end_f-3000
    r_indices_1,integrated,  _ = adt_findrpeaks(signal, threshold_ratio = threshold_ratio, refractory_period=refractory_period)
    r_indices = [pos_prev] + r_indices_1

 


    delta_lis = []
    num_vals = len(r_indices)-1
    
    for i in range(1,num_vals):
        T1 = 1 / (r_indices[i] - r_indices[i-1])
        T2 = 1 / (r_indices[i+1] - r_indices[i])
        delta_t = ((T1 + T2)/2)
        delta_lis.append(delta_t)

    hr_bpm = [int(30000*x) for x in delta_lis]

    hr_vals = hr_bpm.copy()

    #My stuff starts here
    for val in hr_vals:
         if val>180 or val <110:
              hr_vals.remove(val)

    end_pos= r_indices[-1]
    
    return hr_bpm, r_indices, np.mean(np.array(hr_vals)), np.std(np.array(hr_vals)), hr_vals, integrated, end_pos

def get_hrlis_mat(signal, threshold_ratio, refractory_period):
    
    r_indices= adt_findrpeaks(signal, threshold_ratio = threshold_ratio, refractory_period=refractory_period)
    delta_lis = []

    for i in range(1,(len(r_indices))):
        delta_lis.append(r_indices[i] - r_indices[i-1])

    delta_t = [x*dt for x in delta_lis]
    hr_bpm = [int(60/x) for x in delta_t]

    time_indices = [int(r*1000/500) for r in r_indices[1:]]                      
    median = np.median(hr_bpm)
    #hr_bpm = make_array(hr_bpm, 17)
    #time_indices = make_array(time_indices, 17)
    # print('mHRtime =', time_indices)
    # print('mHR = ', hr_bpm)
    
    return hr_bpm, time_indices, r_indices


def missed_peaks(fhr_indices, fhr_bpm, mhr_indices):
    # Initialize the new indices and bpm lists for the adjusted fHR values and indices
    fhr_indices_new = []
    fhr_bpm_new = []
    initial = fhr_indices[0]
    if initial > 400:
        peak1 = [val for val in mhr_indices if 0 < val < initial] # Find the maternal peaks in the range of the gap
        for peak in peak1:
            centre = (initial) // 2
            left_new, right_new = centre - 25, centre + 25 # Define the new left and right indices for the QRS region around the maternal peak

            if left_new < peak < right_new: # If the maternal peak is in the centre of the QRS region, append the indices and bpm values
                fhr_indices_new.extend([0, peak])
                fhr_bpm_new.extend([60/(peak-0)/dt, 60/(initial-peak)/dt])
    else:
        # Ensure consistent handling of fhr_bpm_new
        fhr_bpm_new = []

    for i in range(1, len(fhr_indices)):
        left, right = fhr_indices[i-1], fhr_indices[i]

        if right - left < 300: # If the gap between two peaks is normal append to the new list
            fhr_indices_new.append(left)
            if i-1 < len(fhr_bpm):
                fhr_bpm_new.append(fhr_bpm[i-1])

        else:
            centre = (left + right) // 2
            left_new, right_new = centre - 50, centre + 50 # Define the new left and right indices for the QRS region around the maternal peak

            for val in mhr_indices:
                if left_new < val < right_new:
                    peak = val
                    if left_new < peak < right_new: # If the maternal peak is in the centre of the QRS region, append the indices and bpm values
                        fhr_indices_new.append(left)
                        fhr_indices_new.append(peak)
                        
                        # Add bounds checking before appending to fhr_bpm_new
                        if i-1 < len(fhr_bpm):
                            fhr_bpm_new.append(60/(peak-left)/dt)
                            fhr_bpm_new.append(60/(right-peak)/dt)

    # Ensure the last index is included
    if len(fhr_indices) > 1:
        last_index = fhr_indices[-1]
        fhr_indices_new.append(last_index)
        # if len(fhr_bpm) > len(fhr_indices_new) - 1:
        #    fhr_bpm_new.append(fhr_bpm[-1])

    # Convert the fhr values to integers
    fhr_bpm_new = [int(x) for x in fhr_bpm_new]

    fhr_bpm_int = [int(x) for x in fhr_bpm]
    # Print the initial and final indices and bpm values
    # print("Initial indices: ", len(fhr_indices), fhr_indices)
    # print("Initial bpm: ", len(fhr_bpm_int),fhr_bpm_int)
    # print("Overlap adjusted indices: ", len(fhr_indices_new), fhr_indices_new)
    # print("Overlap adjusted bpm: ", len(fhr_bpm_new), fhr_bpm_new)
    
    return fhr_indices_new, fhr_bpm_new


def missed_peaks(fhr_indices, fhr_bpm, mhr_indices):
    # Initialize the new indices and bpm lists for the adjusted fHR values and indices
    fhr_indices_new = []
    fhr_bpm_new = []
    initial = fhr_indices[0]
    if initial > 400:
        peak1 = [val for val in mhr_indices if 0 < val < initial] # Find the maternal peaks in the range of the gap
        for peak in peak1:
            centre = (initial) // 2
            left_new, right_new = centre - 25, centre + 25 # Define the new left and right indices for the QRS region around the maternal peak

            if left_new < peak < right_new: # If the maternal peak is in the centre of the QRS region, append the indices and bpm values
                fhr_indices_new.extend([0, peak])
                fhr_bpm_new.extend([60/(peak-0)/dt, 60/(initial-peak)/dt])
    else:
        # Ensure consistent handling of fhr_bpm_new
        fhr_bpm_new = []

    for i in range(1, len(fhr_indices)):
        left, right = fhr_indices[i-1], fhr_indices[i]

        if right - left < 300: # If the gap between two peaks is normal append to the new list
            fhr_indices_new.append(left)
            if i-1 < len(fhr_bpm):
                fhr_bpm_new.append(fhr_bpm[i-1])

        else:
            centre = (left + right) // 2
            left_new, right_new = centre - 50, centre + 50 # Define the new left and right indices for the QRS region around the maternal peak

            for val in mhr_indices:
                if left_new < val < right_new:
                    peak = val
                    if left_new < peak < right_new: # If the maternal peak is in the centre of the QRS region, append the indices and bpm values
                        fhr_indices_new.append(left)
                        fhr_indices_new.append(peak)
                        
                        # Add bounds checking before appending to fhr_bpm_new
                        if i-1 < len(fhr_bpm):
                            fhr_bpm_new.append(60/(peak-left)/dt)
                            fhr_bpm_new.append(60/(right-peak)/dt)

    # Ensure the last index is included
    if len(fhr_indices) > 1:
        last_index = fhr_indices[-1]
        fhr_indices_new.append(last_index)
        # if len(fhr_bpm) > len(fhr_indices_new) - 1:
        #    fhr_bpm_new.append(fhr_bpm[-1])

    # Convert the fhr values to integers
    fhr_bpm_new = [int(x) for x in fhr_bpm_new]

    fhr_bpm_int = [int(x) for x in fhr_bpm]
    # Print the initial and final indices and bpm values
    # print("Initial indices: ", len(fhr_indices), fhr_indices)
    # print("Initial bpm: ", len(fhr_bpm_int),fhr_bpm_int)
    # print("Overlap adjusted indices: ", len(fhr_indices_new), fhr_indices_new)
    # print("Overlap adjusted bpm: ", len(fhr_bpm_new), fhr_bpm_new)
    
    return fhr_indices_new, fhr_bpm_new


def missed_thresh(fhr_indices, fhr_signal, median):
    # Initialize the new indices list for the adjusted fHR values and indices
    hr_bpm = []
    fhr_indices_new = []
    if fhr_indices[0] > 400:
        extra_indices, _, _ = adt_findrpeaks(fhr_signal[:fhr_indices[0]], threshold_ratio=0.15, refractory_period=160)
        fhr_indices_new = [val for val in extra_indices]
    
    for i in range(1, len(fhr_indices)):
        left, right = fhr_indices[i-1], fhr_indices[i] # Define the left and right regions of the gap

        if right - left > 400: # If the gap between two peaks is too large, find the peaks within the gap with lower thresholding
            if left < 0:
                left = 0
            extra_indices, _, _ = adt_findrpeaks(fhr_signal[left+1:right-1], threshold_ratio=0.15, refractory_period=160)
            fhr_indices_new.extend(val+left for val in extra_indices)
        else:
            fhr_indices_new.append(left)
    
    # Ensure the last index is included
    fhr_indices_new.append(fhr_indices[-1])
    fhr_indices_new = np.insert(fhr_indices_new, 0, 0)

    delta_lis = [fhr_indices_new[i] - fhr_indices_new[i-1] for i in range(1, len(fhr_indices_new))]
    delta_t = [x*dt for x in delta_lis]

    upper_thresh = (median + 35)
    lower_thresh = (median - 35)

    up = 60/upper_thresh 
    low = 60/lower_thresh

    # Calculate BPM values for all indices, including the last one
    hr_bpm = [int(60/x) for x in delta_t if x != 0]
    
    # Filter out indices not within the desired range
    valid_indices = [i for i, x in enumerate(delta_t) if up <= x <= low and 110 <= hr_bpm[i] <= 180]

    fhr_indices_new = [fhr_indices_new[i+1] for i in valid_indices]
    
    # Filter hr_bpm based on valid_indices
    hr_bpm = [hr_bpm[i] for i in valid_indices]
    return fhr_indices_new, hr_bpm


def peak_separation_ie(residual_signal, mhr_indices_adjusted):
    main_ie = np.zeros(len(residual_signal))
    qrs_width = 30  # Adjust this value based on the width of the QRS complex
    alpha,beta = 1.6, 0.1   #1.2, 0.5

    for idx in mhr_indices_adjusted:
        if idx - int(alpha*qrs_width) >= 0 and idx + int(beta*qrs_width) < len(residual_signal):
            main_ie[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)] = residual_signal[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)]
        elif idx - int(alpha*qrs_width) < 0 :
            main_ie[0: idx + int(beta*qrs_width)] = residual_signal[0: idx + int(beta*qrs_width)]
        else:
            main_ie[idx - int(alpha*qrs_width): len(residual_signal)] = residual_signal[idx - int(alpha*qrs_width): len(residual_signal)]

    rms_values_ie = []

    for idx in mhr_indices_adjusted:
        if idx - int(alpha*qrs_width) >= 0 and idx + int(beta*qrs_width) < len(residual_signal):
            region = residual_signal[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)]
        elif idx - int(alpha*qrs_width) < 0:
            region = residual_signal[0: idx + int(beta*qrs_width)]
        else:
            region = residual_signal[idx - int(alpha*qrs_width): len(residual_signal)]
        
        rms = np.sqrt(np.mean(region**2))
        rms_values_ie.append(rms)

    return rms_values_ie  




def process_of_code(signal, extra, a, last_foetal, last_maternal):
    # Extract the ECG signal columns

        
        ecg_signal_noisy = signal
       
        if len(extra)!=0:
            ecg_signal_noisy = np.concatenate(( extra,ecg_signal_noisy), axis=0)
        # # Extract the Acoustic signal columns
        # top_left = as1s
        # top_right = as2s
        # bottom_left = as3s
        # bottom_right = as4s
                
        #Removing outliers
      
        try:
            # print(ecg_signal_noisy[2000])
            # print(ecg_signal_noisy[-1])
            # print(len(ecg_signal_noisy))
            ecg_signal_noisy = remove_outliers(ecg_signal_noisy)
            ecg_signal_noisy = quantized_value_to_voltage(ecg_signal_noisy)

            
            #select a portion of the stable part of the ecg
            ecg_signal = lfilter(b2,[1], lfilter(b1,[1],ecg_signal_noisy))
            ecg_signal = lfilter(b3, a3, ecg_signal)[2000:]

            signal = ecg_signal
            
            #print()
        except IndexError as e:
            print(f"Index error: {e}")
              
        except ValueError as e:
            print(f"Value error: {e}")
              
        finally:
            pass



        
      
        maternal_bpm,maternal_indices,_, _, _, _ ,end_maternal= get_hrlis(signal,last_maternal,threshold_ratio=0.4, refractory_period=160)
        # print(maternal_bpm)
        r_indices_ori, integrated_signal, ht = adt_findrpeaks(signal)
        # print(r_indices_ori)
        
        # maternal_bpm = [round(value) for value in maternal_bpm]

        # get the maternal peaks and convert to bpm
        delta_lis = []
        dt = 1/fs
        for i in range(1,(len(r_indices_ori))):
            delta_lis.append(r_indices_ori[i] - r_indices_ori[i-1])

        delta_t = [x*dt for x in delta_lis]
        hr_bpm_maternal = [60/x for x in delta_t]
        #print(hr_bpm_maternal)
        maternal_mean = np.mean(np.array(hr_bpm_maternal))
        maternal_std = np.std(np.array(hr_bpm_maternal))
        
       
       # Extract the main ECG signal using QRS complex locations
        main_signal = np.zeros(len(signal))
        qrs_width = 24  # Adjust this value based on the width of the QRS complex
        alpha,beta = 0.65, 1.5

        for idx in r_indices_ori:
            if idx - int(alpha*qrs_width) >= 0 and idx + int(beta*qrs_width) < len(signal):
                main_signal[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)] = signal[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)]
            elif idx - int(alpha*qrs_width) < 0 :
                main_signal[0: idx + int(beta*qrs_width)] = signal[0: idx + int(beta*qrs_width)]
            else:
                main_signal[idx - int(alpha*qrs_width): len(signal)] = signal[idx - int(alpha*qrs_width): len(signal)]


        rms_values_main = []

        for idx in r_indices_ori:
            if idx - int(alpha*qrs_width) >= 0 and idx + int(beta*qrs_width) < len(signal):
                region_m = signal[idx - int(alpha*qrs_width): idx + int(beta*qrs_width)]
            elif idx - int(alpha*qrs_width) < 0:
                region_m = signal[0: idx + int(beta*qrs_width)]
            else:
                region_m = signal[idx - int(alpha*qrs_width): len(signal)]
            
            rms_main = np.sqrt(np.mean(region_m**2))
            rms_values_main.append(rms_main)
        
        residual_signal = signal - main_signal

        # Interpolate zero values in residual_signal_1 using adjacent values from t_wave
        zero_indices = np.where(residual_signal == 0)[0]  # Find indices where residual_signal_1 is zero

        for idx in zero_indices:
            left_idx = idx - 1
            right_idx = idx + 1

            # Find nearest non-zero values in t_wave for interpolation
            while left_idx >= 0 and residual_signal[left_idx] == 0:
                left_idx -= 1
            while right_idx < len(residual_signal) and residual_signal[right_idx] == 0:
                right_idx += 1

            # Check bounds and interpolate using numpy.interp
            if left_idx >= 0 and right_idx < len(residual_signal):
                residual_signal[idx] = np.interp(idx, [left_idx, right_idx], [residual_signal[left_idx], residual_signal[right_idx]])

        residual_with_zeros = np.copy(residual_signal)
        main_with_zeros = np.copy(main_signal)

        resnon_zero_elements = residual_signal[residual_signal != 0]
        res_mean = np.mean(resnon_zero_elements)

        main_signal[main_signal == 0] = res_mean
        

        # De-average and whiten the data

        signal_1 = main_signal
        signal_2 = residual_signal 
        signal_3 = signal 

        

        # three signals from 2 sources
        data = np.vstack((signal_1, signal_2, signal_3))

        data_mean = np.mean(data, axis=1)
        data_centered = data - data_mean[:, np.newaxis]

       

        # Calculate the covariance matrix and perform eigenvalue decomposition
        cov_matrix = np.cov(data_centered)
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Apply ICA to separate the main signal from the residual
        # Whiteing is done via the function itself
        ica = FastICA(n_components=2, whiten = "arbitrary-variance", whiten_solver="eigh")
        ica.fit(data.T)

        # Get the independent components
        independent_components = ica.transform(data.T)

        # Separate the main signal and the residual using the independent components
        # separated_signal_1_original = independent_components[:, 0]#[200:]
        # separated_signal_2_original = independent_components[:, 1]#[200:]

        separated_signal_1 = correct_sign(independent_components[:, 0])[50:2950]
        separated_signal_2 = correct_sign(independent_components[:, 1])[50:2950]

        # separated_signal_1 = correct_sign(separated_signal_1_original)
        # separated_signal_2 = correct_sign(separated_signal_2_original)

        

        # Removing the ends of the signal because the high frequency edges can affect the entire calculation
        # end_pos = len(signal)
        # separated_signal_1 = separated_signal_1[250:end_pos-250]
        # separated_signal_2 = separated_signal_2[250:end_pos-250]

        
        
       
        hr_bpm_1,r_indices_1,hr_mean1, hr_std1, hr_bpm_new_1, integrated_1,end_pos_1  = get_hrlis(separated_signal_1,last_foetal,threshold_ratio=0.4, refractory_period=160)
        r_indices_1 = [x+18 for x in r_indices_1]
        ent1 = ent.sample_entropy(separated_signal_1, 1)
        # print("Sample entropy = ", ent.sample_entropy(separated_signal_1, 1))
        

        hr_bpm_2, r_indices_2, hr_mean2, hr_std2, hr_bpm_new_2, integrated_2,end_pos_2  = get_hrlis(separated_signal_2,last_foetal, threshold_ratio=0.4, refractory_period=160)
        r_indices_2 = [x+18 for x in r_indices_2]
        ent2 = ent.sample_entropy(separated_signal_2, 1) 
        # print("Sample entropy = ", ent.sample_entropy(separated_signal_2, 1))
        


        
        # Perform function on the signal with maximum entropy
        if ent1 > ent2:
            fhr_bpm = hr_bpm_1
            fhr_indices = r_indices_1
            mhr_bpm = hr_bpm_new_2
            mhr_indices = r_indices_2
            f_signal = separated_signal_1
            m_signal = separated_signal_2
            f_integrated = integrated_1
            end_pos = end_pos_1

        else:
            fhr_bpm = hr_bpm_2
            fhr_indices = r_indices_2
            mhr_bpm = hr_bpm_new_1
            mhr_indices = r_indices_1
            f_signal = separated_signal_2
            m_signal = separated_signal_1
            f_integrated = integrated_2
            end_pos = end_pos_2
                
        
          
        fhr_indices_new, fhr_bpm_new = missed_peaks(fhr_indices, fhr_bpm, mhr_indices)
        median = np.median(fhr_bpm_new) 
        
        
        try:
            fhr_indices_final, fhr_bpm_final = missed_thresh(fhr_indices_new, f_signal, median)
        except IndexError as error:
            fhr_indices_final=[]
            fhr_bpm_final=[]
            print(error)
        finally:
            pass    
        fhr_indices_vals =[x + a  for x in fhr_indices_final[0:]]
        final_times = [round(x*dt, 1) for x in fhr_indices_vals]

        maternal_indices = maternal_indices[1:]
        #Change the maternal Indices
        maternal_indices_vals = [x + a  for x in maternal_indices[1:]]
        final_times_maternal  = [round(x*dt, 1) for x in maternal_indices_vals]

        mhr_indices_adjusted = [x + 140 for x in maternal_indices]
        rms_values_isoelectric = peak_separation_ie(residual_signal, mhr_indices_adjusted)       

        # print("Final times fhr: ",len(final_times), final_times)
        # print("Final bpm:       ",len(fhr_bpm_final), fhr_bpm_final)
        # print("Indices final:   ",len(fhr_indices_final), fhr_indices_final)
        # print("   ")
        # print("Final times mhr: ",len( maternal_indices), final_times_maternal)
        # print("mhr bpm:         ",len(maternal_bpm), maternal_bpm)
        # print("mhr Indices:     ",len(maternal_indices),maternal_indices)

        #print("********************************************************************")
        return(final_times,fhr_bpm_final,fhr_indices_final,final_times_maternal,maternal_bpm,maternal_indices,end_pos,end_maternal, rms_values_main, rms_values_isoelectric)

        # mhr = np.median(mhr_bpm)
        # fhr = np.median(fhr_bpm)
    
        # temp_ar = [0]*32
        # try:
        #     temp_ar[4] = int(mhr)
        #     temp_ar[8] = int(fhr)
        # except:
        #     pass
        #temp_ar[11] = ((fhr>>22)&0xFF)
        # print(temp_ar)
        #boink(temp_ar)



def main():
    columns = ['A','B','C','D']
    file_path = 'data/2025-02-28/21_ECG_WCTG.csv'
    df = pd.read_csv(file_path, header=None, names=columns)

    last_foetal_B = 0
    last_maternal_B = 0

    last_foetal_D = 0
    last_maternal_D = 0

    last_foetal_A = 0
    last_maternal_A = 0

    last_foetal_C = 0
    last_maternal_C = 0

    total_FHR_points = 0
    total_MHR_points = 0
    batch_num = 1

    total_fhr_var = []
    total_time_var = []

    toatl_mhr = []
    total_mhr_time=[]

    extra_A,extra_B,extra_C,extra_D = [],[],[],[]
    final_time_fhr,final_fhr,final_time_mhr,final_mhr = [],[],[],[]

    best_ECG = None
    extra=[]

    try:
        while True:
                # Process data in batches of 3000 samples
                start_index = (batch_num - 1) * 3000
                end_index = batch_num * 3000
                batch_df = df[start_index:end_index]


                print("##################################################################\n")
                print(f'Time slots {batch_num}')

            # if (batch_num%10==1 or best_ECG==None ):
               
                column_D = batch_df['D']
                column_B = batch_df['B']
                column_C = batch_df['C']
                column_A = batch_df['A']

                # Calculate thresholds for each column
                threshold_A = calculate_threshold(column_A)
                threshold_B = calculate_threshold(column_B)
                threshold_C = calculate_threshold(column_C)
                threshold_D = calculate_threshold(column_D)

                cleaned_df ,invalid_indexes= clean_invalid_blocks(batch_df, threshold_A ,threshold_B,threshold_C,threshold_D  )
                
                ecg_signal_noisy_A = cleaned_df['A']
                ecg_signal_noisy_B = cleaned_df['B']
                ecg_signal_noisy_C = cleaned_df['C']
                ecg_signal_noisy_D = cleaned_df['D']
                

                ecg_signal_noisy_A = ecg_signal_noisy_A.to_numpy()
                ecg_signal_noisy_B = ecg_signal_noisy_B.to_numpy()
                ecg_signal_noisy_C = ecg_signal_noisy_C.to_numpy()
                ecg_signal_noisy_D = ecg_signal_noisy_D.to_numpy()
                
            
                # if start_index >= len(ecg_signal_noisy_B):
                #     break  # Exit loop if start index exceeds data length              

                ras_B = ecg_signal_noisy_B
                ras_D = ecg_signal_noisy_D
                ras_A = ecg_signal_noisy_A
                ras_C = ecg_signal_noisy_C
                
                if len(ras_B) < 3000:
                    break
                
                time_B, fhr_B, _, time_m_B, mhr_B, _ ,end_fetal_B,end_maternal_B,rms_main_B, rms_iso_B= process_of_code(ras_B, extra_B, start_index,last_foetal_B, last_maternal_B)
                time_D, fhr_D, _, time_m_D,mhr_D, _ ,end_fetal_D,end_maternal_D,rms_main_D, rms_iso_D= process_of_code(ras_D, extra_D, start_index,last_foetal_D, last_maternal_D)
                time_A, fhr_A, _, time_m_A, mhr_A, _ ,end_fetal_A,end_maternal_A,rms_main_A, rms_iso_A= process_of_code(ras_A, extra_A, start_index,last_foetal_A, last_maternal_A)
                time_C, fhr_C, _, time_m_C,mhr_C, _ ,end_fetal_C,end_maternal_C,rms_main_C, rms_iso_C= process_of_code(ras_C, extra_C, start_index,last_foetal_C, last_maternal_C)


                final_time_fhr_BD = time_B if len(time_B)>=len(time_D) else time_D
                final_time_fhr_AC = time_A if len(time_A)>=len(time_C) else time_C
                final_time_fhr = final_time_fhr_AC if len(final_time_fhr_AC)>=len(final_time_fhr_BD) else final_time_fhr_BD
                
                final_fhr_BD = fhr_B if len(time_B)>=len(time_D) else fhr_D
                final_fhr_AC = fhr_A if len(time_A)>=len(time_C) else fhr_C
                final_fhr = final_fhr_AC if len(final_time_fhr_AC)>=len(final_time_fhr_BD) else final_fhr_BD



                final_time_mhr_BD = time_m_D if len(time_D) >= len(time_B) else time_m_B
                final_time_mhr_AC = time_m_A if len(time_A) >= len(time_C) else time_m_C
                final_time_mhr = final_time_mhr_AC if len(final_time_fhr_AC) >= len(final_time_fhr_BD) else final_time_mhr_BD

                final_mhr_BD = mhr_D if len(time_D) >= len(time_B) else mhr_B
                final_mhr_AC = mhr_A if len(time_A) >= len(time_C) else mhr_C
                final_mhr = final_mhr_AC if len(final_time_fhr_AC) >= len(final_time_fhr_BD) else final_mhr_BD

                
                if len(time_D) == 0 and len(time_B) == 0 and len(time_A) == 0 and len(time_C):
                    best_ECG = None
                else:
                    if len(time_D) >= max(len(time_B), len(time_C), len(time_A)):
                        best_ECG = "TOP"
                    elif len(time_B) >= max(len(time_D), len(time_C), len(time_A)):
                        best_ECG = "BOTTOM"
                    elif len(time_C) >= max(len(time_D), len(time_B), len(time_A)):
                        best_ECG = "LEFT"
                    elif len(time_A) >= max(len(time_D), len(time_B), len(time_C)):
                        best_ECG = "RIGHT"

                    # end_fetal = end_fetal_D if len(time_D) >= len(time_B)  else end_fetal_B
                    # end_maternal = end_maternal_D if len(time_D) >= len(time_B)  else end_maternal_B


                extra_B = ras_B[-2000:] #len =2000
                extra_D = ras_D[-2000:] 
                extra_A = ras_A[-2000:] #len =2000
                extra_C = ras_C[-2000:] 

                last_foetal_B = end_fetal_B
                last_maternal_B = end_maternal_B

                last_foetal_D = end_fetal_D
                last_maternal_D = end_maternal_D 

                last_foetal_A = end_fetal_A
                last_maternal_A = end_maternal_A

                last_foetal_C = end_fetal_C
                last_maternal_C = end_maternal_C

                for i in range(0, len(final_fhr)):
                    if i == 0:
                        final_fhr[i] = final_fhr[i]

                    else:
                        final_fhr[i] = int((final_fhr[i-1]+final_fhr[i])/2)

                ##Adding for new laptop with new version

                final_time_fhr = [float(x) for x in final_time_fhr]

                total_FHR_points += len(final_time_fhr)   
                total_fhr_var.extend(final_fhr) 
                total_time_var.extend(final_time_fhr)  

                total_MHR_points+=len(final_time_mhr)
                total_mhr_time.extend(final_time_mhr)
                toatl_mhr.extend(final_mhr)

                # print(f"No of FHR in TOP sensor = {len(time_D)} ")
                # print(f"No of FHR in BOTTOM sensor = {len(time_B)} ")
                # print(f"No of FHR in RIGHT sensor = {len(time_A)} ")
                # print(f"No of FHR in LEFT sensor = {len(time_C)} ")

                                # Sort the RMS values
                rms_main_B_sorted = sorted(rms_main_B)
                rms_iso_B_sorted = sorted(rms_iso_B)
                rms_main_D_sorted = sorted(rms_main_D)
                rms_iso_D_sorted = sorted(rms_iso_D)

                rms_main_A_sorted = sorted(rms_main_A)
                rms_iso_A_sorted = sorted(rms_iso_A)
                rms_main_C_sorted = sorted(rms_main_C)
                rms_iso_C_sorted = sorted(rms_iso_C)

                # Filter out the 2 max and 2 min values
                rms_main_B_filtered = rms_main_B_sorted[2:-2]
                rms_iso_B_filtered = rms_iso_B_sorted[2:-2]
                rms_main_D_filtered = rms_main_D_sorted[2:-2]
                rms_iso_D_filtered = rms_iso_D_sorted[2:-2]

                rms_main_A_filtered = rms_main_A_sorted[2:-2]
                rms_iso_A_filtered = rms_iso_A_sorted[2:-2]
                rms_main_C_filtered = rms_main_C_sorted[2:-2]
                rms_iso_C_filtered = rms_iso_C_sorted[2:-2]

                # Calculate the average of the filtered values
                avg_rms_main_B = np.mean(rms_main_B_filtered)
                avg_rms_iso_B = np.mean(rms_iso_B_filtered)
                avg_rms_main_D = np.mean(rms_main_D_filtered)
                avg_rms_iso_D = np.mean(rms_iso_D_filtered)

                # Calculate the average of the filtered values
                avg_rms_main_A = np.mean(rms_main_A_filtered)
                avg_rms_iso_A = np.mean(rms_iso_A_filtered)
                avg_rms_main_C = np.mean(rms_main_C_filtered)
                avg_rms_iso_C = np.mean(rms_iso_C_filtered)

                Ratio_B = avg_rms_main_B/avg_rms_iso_B
                Ratio_D = avg_rms_main_D/avg_rms_iso_D
                Ratio_A = avg_rms_main_A/avg_rms_iso_A
                Ratio_C = avg_rms_main_C/avg_rms_iso_C

                print(f"Ratio bottom sensor = {Ratio_B}")
                print(f"Ratio top sensor    = {Ratio_D}")
                print(f"Ratio right sensor  = {Ratio_A}")
                print(f"Ratio left sensor   = {Ratio_C}")

                print()

                print(f"Best ECG: {best_ECG}")
                print()
                print(f"Final_Time_FHR: {final_time_fhr}")  
                print(f"Final_FHR: {final_fhr}")
                    
                print()          
                print(f"Final_Time_MHR: {final_time_mhr}") 
                print(f"Final_MHR: {final_mhr}")

                file_name = "ICA for ALL sensors  2025-02-28- ECG_21 bilinear 2 _60Hz.txt"
                with open(file_name, "a") as file:
                    file.write( f"##################################################################\n")
                    file.write(f"\n")
                    file.write(f'Time slots {batch_num}\n')
                    file.write(f"Best ECG: {best_ECG}\n")
                    
                    file.write(f"\n")
                    file.write(f"Ratio bottom sensor = {round(Ratio_B, 2)}\n")
                    file.write(f"Ratio top    sensor = {round(Ratio_D, 2)}\n")
                    file.write(f"Ratio right  sensor = {round(Ratio_A, 2)}\n")
                    file.write(f"Ratio left   sensor = {round(Ratio_C, 2)}\n")

                    file.write(f"\n")
                    file.write(f"Final_Time_FHR: {final_time_fhr}\n")
                    file.write(f"Final_FHR: {final_fhr}\n")
                    file.write(f"\n")
                    file.write(f"Final_Time_MHR: {final_time_mhr}\n")
                    file.write(f"Final_MHR: {final_mhr}\n")
                    file.write(f"\n")
                    



                # if batch_num==1:
                #     break
                        
                batch_num += 1
                # print("Total FHR = ",total_FHR_points)



        print()
        print("Total_FHR_points= ",total_FHR_points)
        print(f"Total_FHR = {total_fhr_var}")
        print()
        print(f"Total_FHR_Time = {total_time_var}")
        print()
        print("Total_MHR_points= ",total_MHR_points)
        print(f"Total_MHR={toatl_mhr}")
        print()
        print(f"Total_MHR_Time={total_mhr_time}")

        

    except KeyboardInterrupt:
        print("Process interrupted by the user.")
    
    except Exception as e:
        
        print(f"An error occurred: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()