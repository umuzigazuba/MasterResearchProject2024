# %% 

from antares_client.search import get_by_ztf_object_id
import fulu
from astropy.coordinates import SkyCoord
from dustmaps.sfd import SFDQuery
import extinction
from sklearn.gaussian_process.kernels import (RBF, Matern, 
      WhiteKernel, ConstantKernel as C)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os

plt.rcParams["text.usetex"] = True

# %%

### ZTF ###

# Generate data
def retrieve_ztf_data(ztf_id):

    data = get_by_ztf_object_id(ztf_id)

    ra = data.ra
    dec = data.dec

    valid_data_r = np.where((data.lightcurve["ant_passband"].to_numpy() == "R") & (~np.isnan(data.lightcurve["ant_mag"].to_numpy())))[0]

    if len(valid_data_r != 0):
        time_r = data.lightcurve["ant_mjd"].to_numpy()[valid_data_r]
        mag_r = data.lightcurve["ant_mag"].to_numpy()[valid_data_r]
        magerr_r = data.lightcurve["ant_magerr"].to_numpy()[valid_data_r]
        
    else:
        time_r = np.array([])
        mag_r = np.array([])
        magerr_r = np.array([])

    valid_data_g = np.where((data.lightcurve["ant_passband"].to_numpy() == "g") & (~np.isnan(data.lightcurve["ant_mag"].to_numpy())))[0]

    if len(valid_data_g != 0):
        time_g = data.lightcurve["ant_mjd"].to_numpy()[valid_data_g]
        mag_g = data.lightcurve["ant_mag"].to_numpy()[valid_data_g]
        magerr_g = data.lightcurve["ant_magerr"].to_numpy()[valid_data_g]
        
    else:
        time_g = np.array([])
        mag_g = np.array([])
        magerr_g = np.array([])
    
    return ra, dec, time_r, mag_r, magerr_r, time_g, mag_g, magerr_g

# Conversion
def ztf_magnitude_to_micro_flux(magnitude, magnitude_error):

    flux = np.power(10, -0.4 * (magnitude - 23.9))
    flux_error = 0.4 * np.log(10) * magnitude_error * flux
    return flux, flux_error

def ztf_micro_flux_to_magnitude(flux):

    magnitude = -2.5 * np.log10(flux) + 23.9
    return magnitude

# Load data saved in directory
def load_ztf_data(ztf_id):

    time = []
    flux = []
    fluxerr = []
    filters = []

    if os.path.isdir(f"Data/ZTF_data/{ztf_id}/r/"):
        ztf_data_r = np.load(f"Data/ZTF_data/{ztf_id}/r/.npy")

        time.extend(ztf_data_r[0])
        flux.extend(ztf_data_r[1])
        fluxerr.extend(ztf_data_r[2])
        filters.extend(["r"] * len(ztf_data_r[0]))

    if os.path.isdir(f"Data/ZTF_data/{ztf_id}/g/"):
        ztf_data_g = np.load(f"Data/ZTF_data/{ztf_id}/g/.npy")

        time.extend(ztf_data_g[0])
        flux.extend(ztf_data_g[1])
        fluxerr.extend(ztf_data_g[2])
        filters.extend(["g"] * len(ztf_data_g[0]))

    return np.array(time), np.array(flux), np.array(fluxerr), np.array(filters)

# Plot data
def plot_ztf_data(ztf_id, time, flux, fluxerr, filters, save_fig = False):

    if "r" in filters:
        r_values = np.where(filters == "r")
        plt.errorbar(time[r_values], flux[r_values], yerr = fluxerr[r_values], fmt = "o", markersize = 4, capsize = 2, color = "tab:blue", label = "Band: r")

    if "g" in filters:
        g_values = np.where(filters == "g")
        plt.errorbar(time[g_values], flux[g_values], yerr = fluxerr[g_values], fmt = "o", markersize = 4, capsize = 2, color = "tab:orange", label = "Band: g")

    plt.xlabel("Modified Julian Date", fontsize = 13)
    plt.ylabel("Flux $(\mu Jy)$", fontsize = 13)
    plt.title(f"Light curve of SN {ztf_id}.")
    plt.grid(alpha = 0.3)
    plt.legend()
    if save_fig:
        plt.savefig(f"Plots/ZTF_lightcurves_plots/ZTF_data_{ztf_id}", dpi = 300)
        plt.close()
    else:
        plt.show()

# %%

### ATLAS ###

# Generate data
def retrieve_atlas_data(atlas_id):

    # Load stacked and cleaned data 
    atlas_data =  np.loadtxt(f"Data/ATLAS_forced_photometry_data/cleaned_and_stacked/{atlas_id}_atlas_fp_stacked_2_days.txt", delimiter = ",", dtype = str)

    time = atlas_data[1:, 0].astype(np.float32)
    flux = atlas_data[1:, 1].astype(np.float32)
    fluxerr = atlas_data[1:, 2].astype(np.float32)
    filter = atlas_data[1:, 3].astype(str)

    return time, flux, fluxerr, filter

def remove_noisy_data(time, flux, fluxerr, filter):

    # Identify noisy observations
    delete_flux = np.where(flux < - 100)
    delete_flux_error = np.where(fluxerr > 40)
    delete_indices = np.union1d(delete_flux, delete_flux_error)

    time = np.delete(time, delete_indices)
    flux = np.delete(flux, delete_indices)
    fluxerr = np.delete(fluxerr, delete_indices)
    filter = np.delete(filter, delete_indices)

    return time, flux, fluxerr, filter

# Baseline subtraction
    # Has to be after cleaning because the peak needs to be determined
    # Often highest value has large error and is probably background noise

def find_baseline(time, flux, filter_f1, filter_f2):

    past_and_future_epochs = {"Past Future f1":[], "Past Future f2":[], "First SN epoch f1":[], "Last SN epoch f1":[], "First SN epoch f2":[], "Last SN epoch f2":[]}

    # Past
    for filter_number, filter_idx in enumerate([filter_f1, filter_f2]):

        time_filter, flux_filter = time[filter_idx], flux[filter_idx]

        peak_idx = np.argmax(flux_filter)
        num_to_cut = 0
        
        # Check if there is pre-peak data 
        if peak_idx == 0:
            past_and_future_epochs[f"First SN epoch f{filter_number + 1}"] = 0
            continue

        # Slope at which the data is no longer constant
        m_cutoff = 0.2 * np.abs((flux_filter[0] - flux_filter[peak_idx]) / (time_filter[0] - time_filter[peak_idx]))

        #Calculate the slope of all data before the peak
        for cut_idx in range(1, peak_idx):

            m = np.abs((flux_filter[0] - flux_filter[cut_idx]) / (time_filter[0] - time_filter[cut_idx]))

            if m < m_cutoff:
                num_to_cut = cut_idx

        if num_to_cut > 0:
            past_and_future_epochs[f"Past Future f{filter_number + 1}"].extend(np.arange(num_to_cut + 1))
            past_and_future_epochs[f"First SN epoch f{filter_number + 1}"] = num_to_cut + 1

        # There is no pre-supernova data
        else:
            past_and_future_epochs[f"First SN epoch f{filter_number + 1}"] = 0

    # Future
    for filter_number, filter_idx in enumerate([filter_f1, filter_f2]):

        time_filter, flux_filter = time[filter_idx], flux[filter_idx]

        peak_idx = np.argmax(flux_filter)
        first_post_peak_idx = len(flux_filter) - np.argmax(flux_filter)
        num_to_cut = 0
        
        # Check if there is post-peak data 
        if peak_idx == len(flux_filter) - 1:
            past_and_future_epochs[f"Last SN epoch f{filter_number + 1}"] = len(flux_filter) - 1
            continue

        # Slope at which the data is no longer constant
        m_cutoff = 0.1 * np.abs((flux_filter[-1] - flux_filter[peak_idx]) / (time_filter[-1] - time_filter[peak_idx]))

        #Calculate the slope of all data before the peak
        for cut_idx in range(2, first_post_peak_idx):
            
            cut_idx *= -1
            m = np.abs((flux_filter[-1] - flux_filter[cut_idx]) / (time_filter[-1] - time_filter[cut_idx]))

            if m < m_cutoff:
                num_to_cut = cut_idx

        if np.abs(num_to_cut) > 0:
            past_and_future_epochs[f"Past Future f{filter_number + 1}"].extend(np.arange(len(flux_filter) + num_to_cut, len(flux_filter)))
            past_and_future_epochs[f"Last SN epoch f{filter_number + 1}"] = len(flux_filter) + num_to_cut - 1

        # There is no post-supernova data
        else:
            past_and_future_epochs[f"Last SN epoch f{filter_number + 1}"] = len(flux_filter) - 1
    
    return past_and_future_epochs

def subtract_baseline(flux, filter_f1, filter_f2, past_and_future_epochs):

    if len(past_and_future_epochs["Past Future f1"]) != 0:

        average_flux_baseline_f1 = np.mean(flux[past_and_future_epochs["Past Future f1"]])

        flux[filter_f1] -= average_flux_baseline_f1

    if len(past_and_future_epochs["Past Future f2"]) != 0:

        average_flux_baseline_f2 = np.mean(flux[past_and_future_epochs["Past Future f2"]])

        flux[filter_f2] -= average_flux_baseline_f2

    return flux

# Conversion
def atlas_micro_flux_to_magnitude(flux, flux_error):

    magnitude = -2.5 * np.log10(flux) + 23.9
    magnitude_error = np.abs(-2.5 * (flux_error / (flux * np.log(10))))

    return magnitude, magnitude_error

# Load data saved in directory
def load_atlas_data(atlas_id):

    time = []
    flux = []
    fluxerr = []
    filters = []

    if os.path.isdir(f"Data/ATLAS_data/forced_photometry/{atlas_id}/o/"):
        atlas_data_o = np.load(f"Data/ATLAS_data/forced_photometry/{atlas_id}/o/.npy")

        time.extend(atlas_data_o[0])
        flux.extend(atlas_data_o[1])
        fluxerr.extend(atlas_data_o[2])
        filters.extend(["o"] * len(atlas_data_o[0]))

    if os.path.isdir(f"Data/ATLAS_data/forced_photometry/{atlas_id}/c/"):
        atlas_data_c = np.load(f"Data/ATLAS_data/forced_photometry/{atlas_id}/c/.npy")

        time.extend(atlas_data_c[0])
        flux.extend(atlas_data_c[1])
        fluxerr.extend(atlas_data_c[2])
        filters.extend(["c"] * len(atlas_data_c[0]))

    return np.array(time), np.array(flux), np.array(fluxerr), np.array(filters)

# Plot data
def plot_atlas_data(atlas_id, time_c, flux_c, fluxerr_c, time_o, flux_o, fluxerr_o, save_fig = False):

    if len(time_o) != 0:
        plt.errorbar(time_o, flux_o, yerr = fluxerr_o, fmt = "o", markersize = 4, capsize = 2, color = "tab:blue", label = "Band: o")

    if len(time_c) != 0:
        plt.errorbar(time_c, flux_c, yerr = fluxerr_c, fmt = "o", markersize = 4, capsize = 2, color = "tab:orange", label = "Band: c")

    plt.xlabel("Modified Julian Date", fontsize = 13)
    plt.ylabel("Flux $(\mu Jy)$", fontsize = 13)
    plt.title(f"Light curve of SN {atlas_id}.")
    plt.grid(alpha = 0.3)
    plt.legend()
    if save_fig:
        plt.savefig(f"Plots/ATLAS_lightcurves_plots/forced_photometry/ATLAS_data_{atlas_id}", dpi = 300)
        plt.close()
    else:
        plt.show()

# %%

### Light curve approximation ###

def data_augmentation(survey, time, flux, fluxerr, filters, augmentation_type):

    if survey == "ZTF":
        passband2lam = {'r': np.log10(6366.38), 'g': np.log10(4746.48)}

    elif survey == "ATLAS":
        passband2lam = {'o': np.log10(6629.82), 'c': np.log10(5182.42)}
    
    else:
        print("ERROR: the options for survey are \"ZTF\" and \"ATLAS\".")
        return None
    
    passbands = filters
    if augmentation_type == "GP":
        augmentation = fulu.GaussianProcessesAugmentation(passband2lam, C(1.0)*Matern() * RBF([1, 1]) + Matern() + WhiteKernel())

    elif augmentation_type == "MLP":
        augmentation = fulu.MLPRegressionAugmentation(passband2lam)
    
    elif augmentation_type == "NF":
        augmentation = fulu.NormalizingFlowAugmentation(passband2lam)
    
    elif augmentation_type == "BNN":
        augmentation = fulu.BayesianNetAugmentation(passband2lam)
    
    else:
        print("ERROR: the options for augmentation_type are \"GP\", \"MLP\", \"NF\"and \"BNN\".")
        return None

    augmentation.fit(time, flux, fluxerr, passbands)

    return passbands, passband2lam, augmentation

def plot_data_augmentation(SN_id, passbands, passband2lam, augmentation_type, time, flux,
                           fluxerr, time_aug, flux_aug, flux_err_aug, passband_aug, ax): 

    plot = fulu.LcPlotter(passband2lam)
    plot.plot_one_graph_all(t = time, flux = flux, flux_err = fluxerr, passbands = passbands,
                            t_approx = time_aug, flux_approx = flux_aug,
                            flux_err_approx = flux_err_aug, passband_approx = passband_aug, ax = ax,
                            title = f"Augmented light curve of SN {SN_id} using {augmentation_type}.")

# %%

### Data processing ###

## Small light curves + light curve clipping: 


def get_magnitude_extinction(magnitude, ra, dec, wavelength):

    
    sfd = SFDQuery()
    coordinates = SkyCoord(ra, dec, frame = "icrs", unit = "deg")

    MW_EBV = sfd(coordinates)
    Av = 2.742 * MW_EBV

    wavelength = 1.0 / (0.0001 * np.array([wavelength]))

    delta_mag = extinction.fm07(wavelength, Av, unit = "invum")

    return magnitude - delta_mag

def OLD_data_processing(survey, SN_names):

    r_wavelength = 6173.23
    g_wavelength = 4741.64

    for SN_id in SN_names:

        print(SN_id)

        if survey == "ZTF":
            filter_1 = "r"
            filter_2 = "g"

            try:
                ra, dec, time_f1, mag_f1, magerr_f1, time_f2, mag_f2, magerr_f2 = retrieve_ztf_data(SN_id)
            
            except AttributeError:
                print("Coud not find", SN_id)
                continue

            mag_f1 = get_magnitude_extinction(mag_f1, ra, dec, r_wavelength)
            mag_f2 = get_magnitude_extinction(mag_f2, ra, dec, g_wavelength)

            flux_f1, fluxerr_f1 = ztf_magnitude_to_micro_flux(mag_f1, magerr_f1)
            flux_f2, fluxerr_f2 = ztf_magnitude_to_micro_flux(mag_f2, magerr_f2)

        elif survey == "ATLAS":
            filter_1 = "o"
            filter_2 = "c"

            time_f1, flux_f1, fluxerr_f1 = retrieve_atlas_data(SN_id, discovery_dates, "o")
            time_f2, flux_f2, fluxerr_f2 = retrieve_atlas_data(SN_id, discovery_dates, "c")

        # Light curve clipping 
        
        if len(time_f2) != 0:
            peak_idx_f2 =  0

            if len(time_f2) > 5:
                while (flux_f2[peak_idx_f2] < flux_f2[peak_idx_f2 + 1 : peak_idx_f2 + 3]).all():
                    peak_idx_f2 += 1
            else:
                peak_idx_f2 = np.argmax(flux_f2)

            end_idx_f2 = len(time_f2) - peak_idx_f2
            pts_to_delete_f2 = 0

            if peak_idx_f2 != len(time_f2) - 1:

                peak_slope_f2 = (flux_f2[-1] - flux_f2[peak_idx_f2])/(time_f2[-1] - time_f2[peak_idx_f2])

                for idx in range(2, end_idx_f2):

                    last_idx_f2 = -1 * idx
                    slope_f2 = (flux_f2[last_idx_f2] - flux_f2[-1])/(time_f2[last_idx_f2] - time_f2[-1])

                    if np.abs(slope_f2) < 0.2 * np.abs(peak_slope_f2):
                        pts_to_delete_f2 = idx

                if pts_to_delete_f2 > 0:

                    time_f2 = time_f2[: -pts_to_delete_f2]
                    flux_f2 = flux_f2[: -pts_to_delete_f2]
                    fluxerr_f2 = fluxerr_f2[: -pts_to_delete_f2]
        
        if len(time_f1) != 0:
            peak_idx_f1 =  0

            if len(time_f1) > 5:
                while (flux_f1[peak_idx_f1] < flux_f1[peak_idx_f1 + 1 : peak_idx_f1 + 3]).all():
                    peak_idx_f1 += 1
            else:
                peak_idx_f1 = np.argmax(flux_f1)

            end_idx_f1 = len(time_f1) - peak_idx_f1
            pts_to_delete_f1 = 0

            if peak_idx_f1 != len(time_f1) - 1:

                peak_slope_f1 = (flux_f1[-1] - flux_f1[peak_idx_f1])/(time_f1[-1] - time_f1[peak_idx_f1])

                for idx in range(2, end_idx_f1):

                    last_idx_f1 = -1 * idx
                    slope_f1 = (flux_f1[last_idx_f1] - flux_f1[-1])/(time_f1[last_idx_f1] - time_f1[-1])

                    if np.abs(slope_f1) < 0.2 * np.abs(peak_slope_f1):
                        pts_to_delete_f1 = idx

                if pts_to_delete_f1 > 0:

                    time_f1 = time_f1[: -pts_to_delete_f1]
                    flux_f1 = flux_f1[: -pts_to_delete_f1]
                    fluxerr_f1 = fluxerr_f1[: -pts_to_delete_f1]

        # Signal-to-noise and Brightness variability
        if len(time_f2) != 0:
            SNR_f2 = flux_f2 / fluxerr_f2
            good_SNR_f2 = np.where(SNR_f2 > 3)[0]

            max_flux_f2 = np.max(flux_f2) - np.min(flux_f2)
            mean_fluxerr_f2 = np.mean(fluxerr_f2)

            std_flux_f2 = np.std(flux_f2)

            if (((len(good_SNR_f2) or len(time_f2)) < 5) or (max_flux_f2 < 3. * mean_fluxerr_f2)) or (std_flux_f2 < mean_fluxerr_f2):
                time_f2 = []
                flux_f2 = []
                fluxerr_f2 = []

        if len(time_f1) != 0:
            SNR_f1 = flux_f1 / fluxerr_f1
            good_SNR_f1 = np.where(SNR_f1 > 3)[0]

            max_flux_f1 = np.max(flux_f1) - np.min(flux_f1)
            mean_fluxerr_f1 = np.mean(fluxerr_f1)

            std_flux_f1 = np.std(flux_f1)

            if (((len(good_SNR_f1) or len(time_f1)) < 5) or (max_flux_f1 < 3. * mean_fluxerr_f1)) or (std_flux_f1 < mean_fluxerr_f1):
                time_f1 = []
                flux_f1 = []
                fluxerr_f1 = []

        if len(time_f2) > 0 or len(time_f1) > 0:
            if survey == "ZTF":
                OLD_plot_ztf_data(SN_id, time_f2, flux_f2, fluxerr_f2, time_f1, flux_f1, fluxerr_f1, save_fig = True)

            elif survey == "ATLAS":
                plot_atlas_data(SN_id, time_f2, flux_f2, fluxerr_f2, time_f1, flux_f1, fluxerr_f1, save_fig = True)

        if len(time_f2) > 0:

            SN_data_f2 = np.stack((time_f2, flux_f2, fluxerr_f2))

            os.makedirs(f"Data/{survey}_data/{SN_id}/{filter_2}/", exist_ok = True)
            np.save(f"Data/{survey}_data/{SN_id}/{filter_2}/", SN_data_f2)

        if len(time_f1) > 0:
            SN_data_f1 = np.stack((time_f1, flux_f1, fluxerr_f1))

            os.makedirs(f"Data/{survey}_data/{SN_id}/{filter_1}/", exist_ok = True)
            np.save(f"Data/{survey}_data/{SN_id}/{filter_1}/", SN_data_f1)

def data_processing_atlas(SN_names):

    for SN_id in SN_names:

        data = pd.read_csv(f"Data/ATLAS_data/forced_photometry/{SN_id}.csv")

        time = data["MJD"].to_numpy()
        flux = data["uJy"].to_numpy()
        fluxerr = data["duJy"].to_numpy()
        filter = data["F"].to_numpy()

        # Remove noisy observations
        delete_red_chi = np.where((data["chi/N"] < 0.5) | (data["chi/N"] > 3))
        delete_flux = np.where(data["uJy"] < - 100)
        delete_sky_mag_o = np.where((data["F"] == "o") & (data["Sky"] < 18))
        delete_sky_mag_c = np.where((data["F"] == "c") & (data["Sky"] < 18.5))
        delete_flux_error = np.where(data["duJy"] > 40)

        delete_indices = np.union1d(
            delete_red_chi,
            np.union1d(
                delete_flux,
                np.union1d(
                    delete_sky_mag_o,
                    np.union1d(delete_sky_mag_c, delete_flux_error)
                )
            )
        )

        time = np.delete(time, delete_indices)
        flux = np.delete(flux, delete_indices)
        fluxerr = np.delete(fluxerr, delete_indices)
        filter = np.delete(filter, delete_indices)

        filter_o = np.where(filter == "o")
        filter_c = np.where(filter == "c")

        time_o = time[filter_o]
        flux_o = flux[filter_o]
        fluxerr_o = fluxerr[filter_o]

        time_c = time[filter_c]
        flux_c = flux[filter_c]
        fluxerr_c = fluxerr[filter_c]

        # Light curve clipping 
        
        if len(time_o) != 0:
            peak_idx_o =  0

            if len(time_o) > 5:
                while (flux_o[peak_idx_o] < flux_o[peak_idx_o + 1 : peak_idx_o + 3]).all():
                    peak_idx_o += 1
            else:
                peak_idx_o = np.argmax(flux_o)

            end_idx_o = len(time_o) - peak_idx_o
            pts_to_delete_o = 0

            if peak_idx_o != len(time_o) - 1:

                peak_slope_o = (flux_o[-1] - flux_o[peak_idx_o])/(time_o[-1] - time_o[peak_idx_o])

                for idx in range(2, end_idx_o):

                    last_idx_o = -1 * idx
                    slope_o = (flux_o[last_idx_o] - flux_o[-1])/(time_o[last_idx_o] - time_o[-1])

                    if np.abs(slope_o) < 0.2 * np.abs(peak_slope_o):
                        pts_to_delete_o = idx

                if pts_to_delete_o > 0:

                    time_o = time_o[: -pts_to_delete_o]
                    flux_o = flux_o[: -pts_to_delete_o]
                    fluxerr_o = fluxerr_o[: -pts_to_delete_o]

        if len(time_c) != 0:
            peak_idx_c =  0

            if len(time_c) > 5:
                while (flux_c[peak_idx_c] < flux_c[peak_idx_c + 1 : peak_idx_c + 3]).all():
                    peak_idx_c += 1
            else:
                peak_idx_c = np.argmax(flux_c)

            end_idx_c = len(time_c) - peak_idx_c
            pts_to_delete_c = 0

            if peak_idx_c != len(time_c) - 1:

                peak_slope_c = (flux_c[-1] - flux_c[peak_idx_c])/(time_c[-1] - time_c[peak_idx_c])

                for idx in range(2, end_idx_c):

                    last_idx_c = -1 * idx
                    slope_c = (flux_c[last_idx_c] - flux_c[-1])/(time_c[last_idx_c] - time_c[-1])

                    if np.abs(slope_c) < 0.2 * np.abs(peak_slope_c):
                        pts_to_delete_c = idx

                if pts_to_delete_c > 0:

                    time_c = time_c[: -pts_to_delete_c]
                    flux_c = flux_c[: -pts_to_delete_c]
                    fluxerr_c = fluxerr_c[: -pts_to_delete_c]

        if len(time[filter_o]) > 0:
            SN_data_o = np.stack((time[filter_o], flux[filter_o], fluxerr[filter_o]))

            os.makedirs(f"Data/ATLAS_data/forced_photometry/{SN_id}/o/", exist_ok = True)
            np.save(f"Data/ATLAS_data/forced_photometry/{SN_id}/o/", SN_data_o)

        if len(time[filter_c]) > 0:
            SN_data_c = np.stack((time[filter_c], flux[filter_c], fluxerr[filter_c]))

            os.makedirs(f"Data/ATLAS_data/forced_photometry/{SN_id}/c/", exist_ok = True)
            np.save(f"Data/ATLAS_data/forced_photometry/{SN_id}/c/", SN_data_c)

        plot_atlas_data(SN_id, time[filter_c], flux[filter_c], fluxerr[filter_c], \
                        time[filter_o], flux[filter_o], fluxerr[filter_o], save_fig = True)
        
# %%

def test():

    # ZTF data

    ztf_id_sn_Ia_CSM= np.loadtxt("Data/ZTF_ID_SNe_Ia_CSM", delimiter = ",", dtype = "str")
    ztf_id_sn_IIn= np.loadtxt("Data/ZTF_ID_SNe_IIn", delimiter = ",", dtype = "str")
            
    ztf_id = np.concatenate((ztf_id_sn_Ia_CSM, ztf_id_sn_IIn))
    ztf_types = np.concatenate((np.zeros(len(ztf_id_sn_Ia_CSM)), np.ones(len(ztf_id_sn_IIn))))

    # ATLAS data

    atlas_id_sn_Ia_CSM = np.loadtxt("Data/ATLAS_ID_SNe_Ia_CSM", delimiter = ",", dtype = "str")
    atlas_id_sn_IIn = np.loadtxt("Data/ATLAS_ID_SNe_IIn", delimiter = ",", dtype = "str")

    atlas_id = np.concatenate((atlas_id_sn_Ia_CSM, atlas_id_sn_IIn))
    atlas_types = np.concatenate((np.zeros(len(atlas_id_sn_Ia_CSM)), np.ones(len(atlas_id_sn_IIn))))
    discovery_dates = np.loadtxt("Data/OLD_ATLAS_data/sninfo.txt", skiprows = 1, usecols = (0, 3), dtype = "str")

    # ZTF 
    # for SN_id in ztf_id:

    #     time_g, mag_g, magerr_g = retrieve_ztf_data(SN_id, "g")
    #     time_r, mag_r, magerr_r = retrieve_ztf_data(SN_id, "R")

    #     flux_g, fluxerr_g = ztf_magnitude_to_micro_flux(mag_g, magerr_g)
    #     flux_r, fluxerr_r = ztf_magnitude_to_micro_flux(mag_r, magerr_r)

        # plot_ztf_data(SN_id, time_g, flux_g, fluxerr_g, time_r, flux_r, fluxerr_r, save_fig = True)

    # ATLAS
    time_c, flux_c, fluxerr_c = retrieve_atlas_data("SN_IIn", atlas_id_sn_Ia_CSM[3], discovery_dates, "c")
    time_o, flux_o, fluxerr_o = retrieve_atlas_data("SN_IIn", atlas_id_sn_Ia_CSM[3], discovery_dates, "o")

    plot_atlas_data(atlas_id_sn_Ia_CSM[3], time_c, flux_c, fluxerr_c, time_o, flux_o, fluxerr_o)

    # Data augmentation
    # time, flux, fluxerr, passbands, passband2lam, augmentation = data_augmentation("ATLAS", time_c, flux_c, fluxerr_c,
    #                                                                             time_o, flux_o, fluxerr_o, "MLP")

    # approx_peak_idx = np.argmax(flux)
    # approx_peak_time = time[approx_peak_idx]

    # time_aug, flux_aug, flux_err_aug, passband_aug = augmentation.augmentation(approx_peak_time - 100, approx_peak_time + 250, n_obs = 1000)

    # plot_data_augmentation(atlas_id_sn_Ia_CSM[1], passbands, passband2lam, "MLP",
    #                     time, flux, fluxerr, time_aug, flux_aug, flux_err_aug, passband_aug)
    
    # time, flux, fluxerr, passbands, passband2lam, augmentation = data_augmentation("ATLAS", time_c, flux_c, fluxerr_c,
    #                                                                             time_o, flux_o, fluxerr_o, "GP")

    # approx_peak_idx = np.argmax(flux)
    # approx_peak_time = time[approx_peak_idx]

    # time_aug, flux_aug, flux_err_aug, passband_aug = augmentation.augmentation(time.min(), time.max(), n_obs = 1000)

    # plot_data_augmentation("2020ywx", passbands, passband2lam, "GP",
    #                     time, flux, fluxerr, time_aug, flux_aug, flux_err_aug, passband_aug)
    
    # time, flux, fluxerr, passbands, passband2lam, augmentation = data_augmentation("ZTF", time_g, flux_g, fluxerr_g,
    #                                                                             time_r, flux_r, fluxerr_r, "GP")

    # approx_peak_idx = np.argmax(flux)
    # approx_peak_time = time[approx_peak_idx]

    # time_aug, flux_aug, flux_err_aug, passband_aug = augmentation.augmentation(approx_peak_time - 100, approx_peak_time + 250, n_obs = 1000)

    # plot_data_augmentation(ztf_id[1], passbands, passband2lam, "GP",
    #                     time, flux, fluxerr, time_aug, flux_aug, flux_err_aug, passband_aug)
    
    # time, flux, fluxerr, passbands, passband2lam, augmentation = data_augmentation("ZTF", time_g, flux_g, fluxerr_g,
    #                                                                             time_r, flux_r, fluxerr_r, "NF")

    # approx_peak_idx = np.argmax(flux)
    # approx_peak_time = time[approx_peak_idx]

    # time_aug, flux_aug, flux_err_aug, passband_aug = augmentation.augmentation(approx_peak_time - 100, approx_peak_time + 250, n_obs = 1000)

    # plot_data_augmentation(ztf_id[1], passbands, passband2lam, "NF",
    #                     time, flux, fluxerr, time_aug, flux_aug, flux_err_aug, passband_aug)

# %%
    
if __name__ == '__main__':
    # test()
    data_processing_atlas(atlas_id)
    
# %%

# # Define the array of elements (directory names)
# input_file = pd.read_csv(f"Data/tns_search (13).csv").to_numpy()
# SN_name = np.copy(input_file[:, 1])

# # Define the path to the text file where the directory names will be stored
# output_file = 'Data/ATLAS_ID_SNe_IIn'

# # Open the file in append mode
# with open(output_file, 'a') as file:
#     # Loop through each element in the array
#     for SN_id in SN_name:
#         # # Check if the directory exists
#         # if os.path.isdir(f"Data/ZTF_data/{SN_id}"):
#         #     # If it exists, write the directory name to the text file
#         file.write(SN_id + '\n')

# def OLD_retrieve_atlas_data(atlas_id, discovery_dates, passband):

#     data = np.loadtxt(f"Data/OLD_ATLAS_data/{atlas_id}/{atlas_id}.{passband}.1.00days.lc.txt", skiprows = 1, usecols = (0, 2, 3))
#     valid_data_idx = np.where((~np.isnan(data[:, 0])) & (data[:, 2] < 50))
#     valid_data = data[valid_data_idx]

#     start_date_idx = np.where(discovery_dates[:, 0] == atlas_id)
#     start_date = float(discovery_dates[start_date_idx, 1][0, 0])
#     last_date = valid_data[-1, 0]

#     if start_date + 300 > last_date:
#         end_date = last_date
#     else:
#         end_date = start_date + 300
        
#     SN_dates = np.where((valid_data[:, 0] >= start_date) & (valid_data[:, 0] <= end_date))

#     if len(SN_dates[0] != 0):
#         time = valid_data[SN_dates, 0]
#         flux = valid_data[SN_dates, 1]
#         fluxerr = valid_data[SN_dates, 2]
            
#         return time[0], flux[0], fluxerr[0]
    
#     return [], [], []

# def OLD_plot_ztf_data(ztf_id, time_g, flux_g, fluxerr_g, time_r, flux_r, fluxerr_r, save_fig = False):

#     if len(time_r) != 0:
#         plt.errorbar(time_r, flux_r, yerr = fluxerr_r, fmt = "o", markersize = 4, capsize = 2, color = "tab:blue", label = "Band: r")

#     if len(time_g) != 0:
#         plt.errorbar(time_g, flux_g, yerr = fluxerr_g, fmt = "o", markersize = 4, capsize = 2, color = "tab:orange", label = "Band: g")

#     plt.xlabel("Modified Julian Date", fontsize = 13)
#     plt.ylabel("Flux $(\mu Jy)$", fontsize = 13)
#     plt.title(f"Light curve of SN {ztf_id}.")
#     plt.grid(alpha = 0.3)
#     plt.legend()
#     if save_fig:
#         plt.savefig(f"Plots/ZTF_lightcurves_plots/ZTF_data_{ztf_id}", dpi = 300)
#         plt.close()
#     else:
#         plt.show()