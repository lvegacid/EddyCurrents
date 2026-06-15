# -*- coding: utf-8 -*-
"""
Created on Mon Mar  2 18:04:34 2026

@author: cidve
"""

# analysis/measured_analysis.py

import os
import csv
import importlib.util
import numpy as np

# use Agg backend for all plotting; the GUI will handle image display
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scipy import signal
from .sequence_analysis import sequenceAnalysis
from .table_manager import update_t0_table


COLORS = {
    'x': 'royalblue',
    'y': 'firebrick',
    'z': 'green'
}


_CURVE_METRICS_HELPERS = None


def _load_curve_metrics_helpers():
    global _CURVE_METRICS_HELPERS
    if _CURVE_METRICS_HELPERS is not None:
        return _CURVE_METRICS_HELPERS

    here = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(os.path.dirname(here), "Metrics", "mat_curve_metrics.py")
    if not os.path.exists(module_path):
        raise FileNotFoundError(f"Metrics helper module not found: {module_path}")

    spec = importlib.util.spec_from_file_location("mat_curve_metrics_analysis", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load metrics helper module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CURVE_METRICS_HELPERS = module
    return module


def _peak_to_peak_until_time(x, y, t_end):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if x.size < 2:
        return np.nan

    t_end = float(t_end)
    mask = x <= t_end
    x_cut = x[mask]
    y_cut = y[mask]
    if x_cut.size >= 1 and float(x_cut[-1]) < t_end <= float(x[-1]):
        y_edge = float(np.interp(t_end, x, y))
        y_cut = np.append(y_cut, y_edge)

    if y_cut.size == 0:
        return np.nan
    return float(np.nanmax(y_cut) - np.nanmin(y_cut))


def _rmse_percent_until_time(mm, x_ref, y_ref, x_cmp, y_cmp, t_end):
    rmse = mm.rmse_until_time(x_ref, y_ref, x_cmp, y_cmp, float(t_end))
    p2p = _peak_to_peak_until_time(x_ref, y_ref, float(t_end))
    if np.isfinite(rmse) and np.isfinite(p2p) and p2p > 0:
        return float(100.0 * rmse / p2p)
    return np.nan


def _resolve_measurement_folder(base_path, setup, phantom_position):
    setup_name = str(setup or "").strip()
    phantom_name = str(phantom_position or "").strip()

    candidates = [
        os.path.join(base_path, setup_name, phantom_name),
    ]

    base_tail = os.path.basename(os.path.normpath(base_path)).lower()
    if base_tail == setup_name.lower():
        candidates.append(os.path.join(base_path, phantom_name))

    setup_path = os.path.join(base_path, setup_name)
    if os.path.basename(os.path.normpath(setup_path)).lower() == phantom_name.lower():
        candidates.append(setup_path)

    seen = set()
    ordered = []
    for p in candidates:
        p_norm = os.path.normpath(p)
        if p_norm not in seen:
            seen.add(p_norm)
            ordered.append(p_norm)

    for p in ordered:
        if os.path.isdir(p):
            return p

    raise FileNotFoundError(
        "Measurement folder not found. Tried paths:\n" + "\n".join(ordered)
    )


def run_measured_analysis(
    base_path,
    setup,
    phantom_position,
    gradient_selected,
    nDelay_selected,
    apply_filter=False,
    beprefilter_cutoff=0.08,
    beprefilter_order=4,
    save_plot=True
):

    mm = _load_curve_metrics_helpers()
    metric_windows_ms = [1.0, 3.0, 5.0, 10.0]

    data_by_axis = {'x': [], 'y': [], 'z': []}

    folder_path = _resolve_measurement_folder(base_path, setup, phantom_position)

    for fname in os.listdir(folder_path):

        if not fname.endswith(".mat") or fname.startswith("FID"):
            continue

        file_path = os.path.join(folder_path, fname)

        try:
            Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = \
                sequenceAnalysis(file_path)



            g = g_axis.lower()

            BePrefilter = None
            # Always compute prefiltered data for table columns.
            # The GUI filter toggle only controls whether filtered curves are plotted.
            compute_prefilter_for_table = True
            if compute_prefilter_for_table:
                gammaB = 42.577e6
                timeFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)
                BePrefilter = np.full_like(Be, np.nan)

                edge_trim = 0
                cutoff = float(np.clip(beprefilter_cutoff, 0.01, 0.49))
                order = int(beprefilter_order)
                sos = signal.butter(order, cutoff, output='sos')

                for n in range(nDelays):
                    fid_n = np.squeeze(fidsmap[n, :, :])
                    phase_pos_grad = np.unwrap(np.angle(fid_n[1, :]))
                    phase_neg_grad = np.unwrap(np.angle(fid_n[2, :]))

                    try:
                        filt_pos = signal.sosfiltfilt(sos, phase_pos_grad)
                        filt_neg = signal.sosfiltfilt(sos, phase_neg_grad)
                    except ValueError:
                        filt_pos = signal.sosfilt(sos, phase_pos_grad)
                        filt_neg = signal.sosfilt(sos, phase_neg_grad)

                    filt_diff = filt_pos - filt_neg

                    be_pref_n = (1 / (4 * np.pi * gammaB)) * \
                        np.gradient(filt_diff, timeFID * 1e-3) * 1e6

                    if edge_trim > 0 and nReadouts > 2 * edge_trim:
                        be_pref_n[:edge_trim] = np.nan
                        be_pref_n[-edge_trim:] = np.nan

                    BePrefilter[n, :] = be_pref_n

            if g in data_by_axis:
                data_by_axis[g].append({
                    'tiempo': tiempo,
                    'Beddy': Be,
                    'BeddyFitted': BeddyFitted,
                    'BePrefilter': BePrefilter,
                    'deadTime': deadTime,
                    'acqTime': acqTime
                })

        except Exception as e:
            print(f"Error in {fname}: {e}")

    if gradient_selected == "All":
        grad_list = ['x', 'y', 'z']
    else:
        grad_list = [gradient_selected[-1].lower()]

    if nDelay_selected == "All":
        nDelay_selected = "all"
    else:
        nDelay_selected = int(nDelay_selected)

    plt.figure(figsize=(10, 6))

    any_legend = False
    prefilter_legend_added = False
    metric_raw_segments = []
    metric_pref_segments = []
    for G in grad_list:

        if not data_by_axis[G]:
            continue

        color = COLORS[G]
        B0_all = []
        B0_fitted_all = []
        B0_prefilter_all = []
        B_integrated_all = []
        B_integrated_1ms_all = []
        B_integrated_3ms_all = []
        B_integrated_5ms_all = []
        B_integrated_10ms_all = []
        metric_acc = {}

        def _acc_metric(name, value):
            metric_acc.setdefault(name, []).append(value)

        prefilter_text_added = False
        # ensure legend entry is added only once per gradient
        legend_added = False

        for data in data_by_axis[G]:

            tiempo = data['tiempo']
            Beddy = data['Beddy']
            BeddyFitted = data['BeddyFitted']
            BePrefilter = data.get('BePrefilter')
            deadTime = data['deadTime']
            acqTime = data['acqTime']

            nDelays = Beddy.shape[0]

            n_table = 0

            B0_all.append(float(Beddy[n_table, 0]))
            B0_fitted_all.append(float(BeddyFitted[n_table, 0]))
            if BePrefilter is not None:
                row_pref = BePrefilter[n_table, :]
                valid_idx_table = np.where(np.isfinite(row_pref))[0]
                if valid_idx_table.size > 0:
                    B0_prefilter_all.append(float(row_pref[int(valid_idx_table[0])]))

            # Expanded metric family using the standalone reconstruction logic.
            tiempo_arr = np.asarray(tiempo, dtype=float)
            dead_time = float(deadTime)
            acq_time = float(acqTime)
            recon_ref = mm.reconstruct_continuous_series(
                np.asarray(Beddy, dtype=float),
                tiempo_arr,
                dead_time,
                acq_time,
            )
            x_ref = np.asarray(recon_ref["x_rel"], dtype=float)
            y_ref = np.asarray(recon_ref["y"], dtype=float)

            if x_ref.size >= 2:
                # Raw/Fitted/Prefiltered integrated metrics and RMSE% at 1/3/5/10/all.
                source_curves = {
                    "B_integrated": np.asarray(Beddy, dtype=float),
                    "B_integrated_fitted": np.asarray(BeddyFitted, dtype=float),
                }
                if BePrefilter is not None:
                    source_curves["B_integrated_prefiltered"] = np.asarray(BePrefilter, dtype=float)

                for base_col, source_curve in source_curves.items():
                    recon_src = mm.reconstruct_continuous_series(source_curve, tiempo_arr, dead_time, acq_time)
                    x_src = np.asarray(recon_src["x_rel"], dtype=float)
                    y_src = np.asarray(recon_src["y"], dtype=float)
                    if x_src.size < 2:
                        continue

                    t_all = float(x_ref[-1])
                    val_all = mm.integrate_until_time(x_src, np.abs(y_src), t_all, "trapz")
                    rmse_pct_all = _rmse_percent_until_time(mm, x_ref, y_ref, x_src, y_src, t_all)
                    _acc_metric(base_col, val_all)
                    _acc_metric(f"{base_col}_RMSE%", rmse_pct_all)

                    if base_col == "B_integrated":
                        B_integrated_all.append(val_all)

                    for w in metric_windows_ms:
                        val_w = mm.integrate_until_time(x_src, np.abs(y_src), float(w), "trapz")
                        rmse_pct_w = _rmse_percent_until_time(mm, x_ref, y_ref, x_src, y_src, float(w))
                        tag = f"{int(w)}ms"
                        _acc_metric(f"{base_col}_{tag}", val_w)
                        _acc_metric(f"{base_col}_{tag}_RMSE%", rmse_pct_w)

                        if base_col == "B_integrated":
                            if int(w) == 1:
                                B_integrated_1ms_all.append(val_w)
                            elif int(w) == 3:
                                B_integrated_3ms_all.append(val_w)
                            elif int(w) == 5:
                                B_integrated_5ms_all.append(val_w)
                            elif int(w) == 10:
                                B_integrated_10ms_all.append(val_w)

                # Exponential fit order 1 and 2 metrics at 1/3/5/10/all.
                fit_out = mm.fit_exponentials_orders(x_ref, y_ref, [1, 2])
                fits = [f for f in fit_out.get("fits", []) if f.get("success", False)]
                fit_by_order = {int(f.get("order", 0)): f for f in fits}

                for order in [1, 2]:
                    fit = fit_by_order.get(order)
                    base_col = f"B_integrated_exp_fit{order}"
                    if fit is None:
                        _acc_metric(base_col, np.nan)
                        _acc_metric(f"{base_col}_RMSE%", np.nan)
                        for w in metric_windows_ms:
                            tag = f"{int(w)}ms"
                            _acc_metric(f"{base_col}_{tag}", np.nan)
                            _acc_metric(f"{base_col}_{tag}_RMSE%", np.nan)
                        for i in range(1, order + 1):
                            _acc_metric(f"exp_fit{order}_A{i}", np.nan)
                            _acc_metric(f"exp_fit{order}_tau{i}", np.nan)
                        continue

                    x_fit = np.asarray(fit["x"], dtype=float)
                    y_fit = np.asarray(fit["y_fit"], dtype=float)
                    t_all = float(x_ref[-1])

                    val_all = mm.integrate_until_time(x_fit, np.abs(y_fit), t_all, "trapz")
                    rmse_pct_all = _rmse_percent_until_time(mm, x_ref, y_ref, x_fit, y_fit, t_all)
                    _acc_metric(base_col, val_all)
                    _acc_metric(f"{base_col}_RMSE%", rmse_pct_all)

                    for w in metric_windows_ms:
                        val_w = mm.integrate_until_time(x_fit, np.abs(y_fit), float(w), "trapz")
                        rmse_pct_w = _rmse_percent_until_time(mm, x_ref, y_ref, x_fit, y_fit, float(w))
                        tag = f"{int(w)}ms"
                        _acc_metric(f"{base_col}_{tag}", val_w)
                        _acc_metric(f"{base_col}_{tag}_RMSE%", rmse_pct_w)

                    coeffs = fit.get("coefficients", {})
                    for i in range(1, order + 1):
                        _acc_metric(f"exp_fit{order}_A{i}", coeffs.get(f"A{i}", np.nan))
                        _acc_metric(f"exp_fit{order}_tau{i}", coeffs.get(f"tau{i}", np.nan))

            if nDelay_selected == "all" or \
               (isinstance(nDelay_selected, int) and
                nDelay_selected >= nDelays):

                for n in range(nDelays):

                    delay_offset = n * (deadTime + acqTime)
                    tiempo_corr = tiempo + delay_offset

                    if apply_filter and BePrefilter is not None:
                        valid_mask = np.isfinite(BePrefilter[n, :])
                        if np.any(valid_mask):
                            metric_raw_segments.append(Beddy[n, :][valid_mask])
                            metric_pref_segments.append(BePrefilter[n, :][valid_mask])

                        if not prefilter_legend_added:
                            plt.plot(
                                tiempo_corr,
                                BePrefilter[n, :],
                                '--',
                                color='#1f1f1f',
                                alpha=0.9,
                                linewidth=1.0,
                                zorder=10,
                                label='Beddy_Prefiltered'
                            )
                            prefilter_legend_added = True
                            any_legend = True
                        else:
                            plt.plot(
                                tiempo_corr,
                                BePrefilter[n, :],
                                '--',
                                color='#1f1f1f',
                                alpha=0.9,
                                linewidth=1.0,
                                zorder=10
                            )

                    # plot measured data points
                    if not legend_added:
                        plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=5, color=color, alpha=0.4, label=G.upper())
                        legend_added = True
                        any_legend = True
                    else:
                        plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=5, color=color, alpha=0.4)

                    # plot fitted curve
                    plt.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8)
                    
                    # annotate only first point of first nDelay (n=0)
                    if n == 0:
                        y0_measured = Beddy[n, 0]
                        y0_fitted = BeddyFitted[n, 0]
                        x0 = tiempo_corr[0]

                        # measured value in gradient color
                        plt.annotate(f"{y0_measured:.2f}",
                                   (x0, y0_measured),
                                   textcoords="offset points", xytext=(20, 12),
                                   ha='left', fontsize=11, color=color, fontweight='bold')

                        # fitted descriptor inline in gray (slash separates)
                        plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                                   (x0, y0_measured),
                                   textcoords="offset points", xytext=(30, 12),
                                   ha='left', fontsize=11, color='gray', fontweight='bold')

                        if apply_filter and BePrefilter is not None and not prefilter_text_added:
                            valid_idx = np.where(np.isfinite(BePrefilter[n, :]))[0]
                            if valid_idx.size > 0:
                                y_pref = BePrefilter[n, int(valid_idx[0])]
                                plt.annotate(
                                    f"/ {y_pref:.2f}",
                                    (x0, y0_measured),
                                    textcoords="offset points",
                                    xytext=(145, 12),
                                    ha='left',
                                    fontsize=11,
                                    color='#1f1f1f',
                                    fontweight='bold',
                                    zorder=30,
                                    annotation_clip=False
                                )
                                prefilter_text_added = True

            else:

                n = nDelay_selected

                delay_offset = n * (deadTime + acqTime)
                tiempo_corr = tiempo + delay_offset

                if apply_filter and BePrefilter is not None:
                    valid_mask = np.isfinite(BePrefilter[n, :])
                    if np.any(valid_mask):
                        metric_raw_segments.append(Beddy[n, :][valid_mask])
                        metric_pref_segments.append(BePrefilter[n, :][valid_mask])

                    if not prefilter_legend_added:
                        plt.plot(
                            tiempo_corr,
                            BePrefilter[n, :],
                            '--',
                            color='#1f1f1f',
                            alpha=0.9,
                            linewidth=1.0,
                            zorder=10,
                            label='Beddy_Prefiltered'
                        )
                        prefilter_legend_added = True
                        any_legend = True
                    else:
                        plt.plot(
                            tiempo_corr,
                            BePrefilter[n, :],
                            '--',
                            color='#1f1f1f',
                            alpha=0.9,
                            linewidth=1.0,
                            zorder=10
                        )

                # plot measured data points
                if not legend_added:
                    plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=6, color=color, label=G.upper())
                    legend_added = True
                    any_legend = True
                else:
                    plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=6, color=color)

                # plot fitted curve
                plt.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color)
                
                # annotate first point
                y0_measured = Beddy[n, 0]
                y0_fitted = BeddyFitted[n, 0]
                x0 = tiempo_corr[0]

                # measured value
                plt.annotate(f"{y0_measured:.2f}",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(20, 12),
                           ha='left', fontsize=11, color=color, fontweight='bold')

                # fitted value in gray right of measured (slash separates)
                plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(30, 12),
                           ha='left', fontsize=11, color='gray', fontweight='bold')

                if apply_filter and BePrefilter is not None and not prefilter_text_added:
                    valid_idx = np.where(np.isfinite(BePrefilter[n, :]))[0]
                    if valid_idx.size > 0:
                        y_pref = BePrefilter[n, int(valid_idx[0])]
                        plt.annotate(
                            f"/ {y_pref:.2f}",
                            (x0, y0_measured),
                            textcoords="offset points",
                            xytext=(145, 12),
                            ha='left',
                            fontsize=11,
                            color='#1f1f1f',
                            fontweight='bold',
                            zorder=30,
                            annotation_clip=False
                        )
                        prefilter_text_added = True

                # fitted label
                plt.annotate("(fitted)",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(20, -3),
                           ha='left', fontsize=9, color='gray', fontweight='bold')

        update_t0_table(
            base_path,
            setup,
            G.upper(),
            phantom_position,
            B0_all,
            B0_fitted_all,
            B0_prefilter_all if len(B0_prefilter_all) > 0 else None,
            B_integrated_all if len(B_integrated_all) > 0 else None,
            B_integrated_1ms_all if len(B_integrated_1ms_all) > 0 else None,
            B_integrated_5ms_all if len(B_integrated_5ms_all) > 0 else None,
            B_integrated_10ms_all if len(B_integrated_10ms_all) > 0 else None,
            extra_metrics=metric_acc,
        )

    if any_legend:
        plt.legend(fontsize=11)
    plt.title(f"Beddy Measured - {gradient_selected}", fontsize=13)
    if apply_filter:
        cutoff_display = float(np.clip(beprefilter_cutoff, 0.01, 0.49))
        metrics_text = [f"BW order={int(beprefilter_order)}, Wn={cutoff_display:.2f}"]

        if metric_raw_segments and metric_pref_segments:
            raw_all = np.concatenate(metric_raw_segments)
            pref_all = np.concatenate(metric_pref_segments)
            finite_mask = np.isfinite(raw_all) & np.isfinite(pref_all)
            raw_all = raw_all[finite_mask]
            pref_all = pref_all[finite_mask]

            if raw_all.size > 3 and pref_all.size > 3:
                diff_raw = np.diff(raw_all)
                diff_pref = np.diff(pref_all)

                rough_raw = float(np.nanstd(diff_raw))
                rough_pref = float(np.nanstd(diff_pref))
                rms_delta = float(np.sqrt(np.nanmean((pref_all - raw_all) ** 2)))

                if rough_raw > 0:
                    noise_reduction_pct = (1.0 - (rough_pref / rough_raw)) * 100.0
                    metrics_text.append(f"HF noise red.: {noise_reduction_pct:.1f}%")

                if rough_pref > 0:
                    smooth_gain = rough_raw / rough_pref if rough_raw > 0 else np.nan
                    metrics_text.append(f"Smooth gain: {smooth_gain:.2f}x")

                if np.nanstd(raw_all) > 0 and np.nanstd(pref_all) > 0:
                    corr_r = float(np.corrcoef(raw_all, pref_all)[0, 1])
                    metrics_text.append(f"Corr(raw,pref): {corr_r:.3f}")

                metrics_text.append(f"RMS delta: {rms_delta:.3f} µT")

        plt.text(
            0.99,
            0.98,
            "\n".join(metrics_text),
            transform=plt.gca().transAxes,
            ha='right',
            va='top',
            fontsize=8.5,
            color='#1f1f1f',
            bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='0.6', alpha=0.75)
        )
    plt.xlabel("Time (ms)", fontsize=12)
    plt.ylabel("Beddy (µT)", fontsize=12)
    plt.grid(True)
    plt.tight_layout()

    if save_plot:
        save_dir = _resolve_measurement_folder(base_path, setup, phantom_position)
    else:
        import tempfile
        save_dir = tempfile.gettempdir()

    filtered_tag = "_filtered" if apply_filter else ""
    mode_tag = ""
    if apply_filter:
        mode_tag = f"_bw_o{int(beprefilter_order)}_w{int(round(float(np.clip(beprefilter_cutoff, 0.01, 0.49)) * 100)):02d}"
    filename = f"Beddy_measured{filtered_tag}{mode_tag}_Grad_{gradient_selected}_nDelay_{nDelay_selected}.png"

    output_path = os.path.join(save_dir, filename)
    plt.savefig(output_path, dpi=300)
    plt.close()

    return output_path


def extract_filter_metrics_sweep(
    base_path,
    setup,
    phantom_position,
    gradient_selected,
    nDelay_selected,
    cutoff_values,
    order_values
):
    folder_path = _resolve_measurement_folder(base_path, setup, phantom_position)

    if gradient_selected == "All":
        grad_list = ['x', 'y', 'z']
    else:
        grad_list = [gradient_selected[-1].lower()]

    if nDelay_selected == "All":
        ndelay_value = "all"
    else:
        ndelay_value = int(nDelay_selected)

    def _safe_float(value):
        try:
            return float(value)
        except Exception:
            return np.nan

    rows = []

    gammaB = 42.577e6
    cached_series = []

    for fname in os.listdir(folder_path):
        if not fname.endswith(".mat") or fname.startswith("FID"):
            continue

        file_path = os.path.join(folder_path, fname)

        try:
            Be, _, _, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = sequenceAnalysis(file_path)
        except Exception:
            continue

        g = str(g_axis).lower()
        if g not in grad_list:
            continue

        timeFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)

        if ndelay_value == "all" or (isinstance(ndelay_value, int) and ndelay_value >= nDelays):
            ndelay_indices = list(range(nDelays))
        else:
            ndelay_indices = [ndelay_value]

        series_for_file = []
        for n in ndelay_indices:
            if n >= nDelays:
                continue

            fid_n = np.squeeze(fidsmap[n, :, :])
            phase_pos_grad = np.unwrap(np.angle(fid_n[1, :]))
            phase_neg_grad = np.unwrap(np.angle(fid_n[2, :]))
            phase_diff = phase_pos_grad - phase_neg_grad

            series_for_file.append({
                'phase_diff': phase_diff,
                'raw_be': Be[n, :],
                'time_s': timeFID * 1e-3
            })

        if series_for_file:
            cached_series.extend(series_for_file)

    for order in order_values:
        for cutoff in cutoff_values:
            raw_segments = []
            pref_segments = []

            try:
                sos = signal.butter(int(order), float(cutoff), output='sos')
            except Exception:
                continue

            for serie in cached_series:
                phase_diff = serie['phase_diff']
                raw_be = serie['raw_be']
                time_s = serie['time_s']

                try:
                    filt_diff = signal.sosfiltfilt(sos, phase_diff)
                except ValueError:
                    filt_diff = signal.sosfilt(sos, phase_diff)

                be_pref = (1 / (4 * np.pi * gammaB)) * np.gradient(filt_diff, time_s) * 1e6

                valid_mask = np.isfinite(be_pref) & np.isfinite(raw_be)
                if np.any(valid_mask):
                    raw_segments.append(raw_be[valid_mask])
                    pref_segments.append(be_pref[valid_mask])

            noise_reduction_pct = np.nan
            smooth_gain = np.nan
            corr_r = np.nan
            rms_delta = np.nan

            if raw_segments and pref_segments:
                raw_all = np.concatenate(raw_segments)
                pref_all = np.concatenate(pref_segments)
                finite_mask = np.isfinite(raw_all) & np.isfinite(pref_all)
                raw_all = raw_all[finite_mask]
                pref_all = pref_all[finite_mask]

                if raw_all.size > 3 and pref_all.size > 3:
                    diff_raw = np.diff(raw_all)
                    diff_pref = np.diff(pref_all)
                    rough_raw = float(np.nanstd(diff_raw))
                    rough_pref = float(np.nanstd(diff_pref))
                    rms_delta = float(np.sqrt(np.nanmean((pref_all - raw_all) ** 2)))

                    if rough_raw > 0:
                        noise_reduction_pct = (1.0 - (rough_pref / rough_raw)) * 100.0
                    if rough_pref > 0 and rough_raw > 0:
                        smooth_gain = rough_raw / rough_pref
                    if np.nanstd(raw_all) > 0 and np.nanstd(pref_all) > 0:
                        corr_r = float(np.corrcoef(raw_all, pref_all)[0, 1])

            rows.append({
                'Setup': setup,
                'PhantomPosition': phantom_position,
                'Gradient': gradient_selected,
                'nDelay': str(nDelay_selected),
                'FilterType': 'Butterworth',
                'FilterOrder': int(order),
                'CutoffWn': float(cutoff),
                'HFNoiseReductionPct': _safe_float(noise_reduction_pct),
                'SmoothGainX': _safe_float(smooth_gain),
                'CorrRawPref': _safe_float(corr_r),
                'RMSDelta_uT': _safe_float(rms_delta)
            })

    safe_setup = str(setup).replace(' ', '_')
    safe_phantom = str(phantom_position).replace(' ', '_')
    safe_grad = str(gradient_selected).replace(' ', '_')
    safe_ndelay = str(nDelay_selected).replace(' ', '_')

    prefix = f"FilterMetrics_{safe_setup}_{safe_phantom}_{safe_grad}_nDelay_{safe_ndelay}"
    csv_path = os.path.join(folder_path, f"{prefix}.csv")

    if rows:
        noise_vals = np.array([_safe_float(r.get('HFNoiseReductionPct')) for r in rows], dtype=float)
        smooth_vals = np.array([_safe_float(r.get('SmoothGainX')) for r in rows], dtype=float)
        corr_vals = np.array([_safe_float(r.get('CorrRawPref')) for r in rows], dtype=float)
        rms_vals = np.array([_safe_float(r.get('RMSDelta_uT')) for r in rows], dtype=float)

        def _norm(values, invert=False):
            finite = np.isfinite(values)
            out = np.full(values.shape, np.nan, dtype=float)
            if not np.any(finite):
                return out
            vmin = np.nanmin(values[finite])
            vmax = np.nanmax(values[finite])
            if np.isclose(vmax, vmin):
                out[finite] = 0.5
            else:
                out[finite] = (values[finite] - vmin) / (vmax - vmin)
            if invert:
                out[finite] = 1.0 - out[finite]
            return out

        n_noise = _norm(noise_vals, invert=False)
        n_smooth = _norm(smooth_vals, invert=False)
        n_corr = _norm(corr_vals, invert=False)
        n_rms = _norm(rms_vals, invert=True)

        w_noise, w_smooth, w_corr, w_rms = 0.35, 0.25, 0.25, 0.15
        for i, row in enumerate(rows):
            comps = np.array([n_noise[i], n_smooth[i], n_corr[i], n_rms[i]], dtype=float)
            weights = np.array([w_noise, w_smooth, w_corr, w_rms], dtype=float)
            valid = np.isfinite(comps)
            if np.any(valid):
                score = float(np.sum(comps[valid] * weights[valid]) / np.sum(weights[valid]))
                row['GlobalFilterScore'] = score
            else:
                row['GlobalFilterScore'] = np.nan

        fieldnames = list(rows[0].keys())
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    heatmap_paths = []
    metric_columns = [
        ('HFNoiseReductionPct', 'HF noise reduction (%)'),
        ('SmoothGainX', 'Smooth gain (x)'),
        ('CorrRawPref', 'Corr(raw,pref)'),
        ('RMSDelta_uT', 'RMS delta (µT)'),
        ('GlobalFilterScore', 'Global filter score (0-1)')
    ]

    order_values_int = [int(o) for o in order_values]
    cutoff_values_float = [float(c) for c in cutoff_values]

    for metric_key, metric_label in metric_columns:
        matrix = np.full((len(order_values_int), len(cutoff_values_float)), np.nan)

        for row in rows:
            o = int(row['FilterOrder'])
            c = float(row['CutoffWn'])
            if o in order_values_int and c in cutoff_values_float:
                oi = order_values_int.index(o)
                ci = cutoff_values_float.index(c)
                matrix[oi, ci] = float(row[metric_key])

        fig, ax = plt.subplots(figsize=(7, 4.5))
        im = ax.imshow(matrix, aspect='auto', origin='lower', cmap='viridis')
        ax.set_xticks(range(len(cutoff_values_float)))
        ax.set_xticklabels([f"{c:.2f}" for c in cutoff_values_float])
        ax.set_yticks(range(len(order_values_int)))
        ax.set_yticklabels([str(o) for o in order_values_int])
        ax.set_xlabel('Cutoff Wn')
        ax.set_ylabel('Filter order')
        ax.set_title(f"{metric_label} ({gradient_selected}, nDelay={nDelay_selected})")
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label(metric_label)
        fig.tight_layout()

        heatmap_path = os.path.join(folder_path, f"{prefix}_{metric_key}_heatmap.png")
        fig.savefig(heatmap_path, dpi=300)
        plt.close(fig)
        heatmap_paths.append(heatmap_path)

    return {
        'csv_path': csv_path,
        'heatmap_paths': heatmap_paths,
        'row_count': len(rows)
    }


# =========================================================
# FID ANALYSIS
# =========================================================

def run_fid_analysis(
    base_path,
    setup,
    phantom_position,
    gradient_selected,
    nDelay_selected,
    apply_filter=False
):
    """
    Plot absolute values of FID data for minimum delay (n=0).
    Only one gradient at a time (no 'All' option).
    """
    folder_path = _resolve_measurement_folder(base_path, setup, phantom_position)

    for fname in os.listdir(folder_path):
        if not fname.endswith(".mat") or fname.startswith("FID"):
            continue

        file_path = os.path.join(folder_path, fname)

        try:
            Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = \
                sequenceAnalysis(file_path)

            # Debug: report which gradient this file reports
            try:
                detected_g = str(g_axis)
            except Exception:
                detected_g = repr(g_axis)

            g = g_axis.lower()
            grad_letter = g.upper()

            # map GUI selection like "GX" -> "X" for comparison; if user somehow passed All, treat as wildcard
            sel_letter = gradient_selected[-1] if gradient_selected != "All" else None
            # Only process the selected gradient
            if sel_letter is not None and grad_letter != sel_letter:
                continue

            # Calculate correct time vector for FID data (original units, assumed µs)
            tFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)
            # time is already in milliseconds from sequenceAnalysis conversion
            t_ms = tFID

            plt.figure(figsize=(10, 6))

            any_legend = False
            for n in range(nDelays):
                delay_offset_ms = n * (deadTime + acqTime)
                t_corr = t_ms + delay_offset_ms

                fid_n = np.squeeze(fidsmap[n, :, :])  # shape: (3, nReadouts)
                fid_no_grad = np.abs(fid_n[0, :])
                fid_pos_grad = np.abs(fid_n[1, :])
                fid_neg_grad = np.abs(fid_n[2, :])

                # apply filter if requested
                if apply_filter:
                    sos = signal.butter(4, 0.2, output='sos')
                    filt_no = signal.sosfilt(sos, fid_no_grad)
                    filt_pos = signal.sosfilt(sos, fid_pos_grad)
                    filt_neg = signal.sosfilt(sos, fid_neg_grad)
                else:
                    filt_no = filt_pos = filt_neg = None

                # measured data points for each channel
                if not any_legend:
                    plt.plot(t_corr, fid_no_grad, 'o', markersize=0.4, color='purple', alpha=0.6, label='FID_NoGrad')
                    plt.plot(t_corr, fid_pos_grad, 'o', markersize=0.4, color='cornflowerblue', alpha=0.6, label='FID_PositiveGrad')
                    plt.plot(t_corr, fid_neg_grad, 'o', markersize=0.4, color='lightpink', alpha=0.6, label='FID_NegativeGrad')
                    any_legend = True
                else:
                    plt.plot(t_corr, fid_no_grad, 'o', markersize=0.4, color='purple', alpha=0.6)
                    plt.plot(t_corr, fid_pos_grad, 'o', markersize=0.4, color='cornflowerblue', alpha=0.6)
                    plt.plot(t_corr, fid_neg_grad, 'o', markersize=0.4, color='lightpink', alpha=0.6)

                # filtered curves overlay if requested
                if apply_filter and filt_no is not None:
                    if n == 0:
                        plt.plot(t_corr, filt_no, '-', color='purple', linewidth=0.8, label='FID_NoGrad (Filtered)')
                        plt.plot(t_corr, filt_pos, '-', color='cornflowerblue', linewidth=0.8, label='FID_PositiveGrad (Filtered)')
                        plt.plot(t_corr, filt_neg, '-', color='lightpink', linewidth=0.8, label='FID_NegativeGrad (Filtered)')
                    else:
                        plt.plot(t_corr, filt_no, '-', color='purple', linewidth=0.8)
                        plt.plot(t_corr, filt_pos, '-', color='cornflowerblue', linewidth=0.8)
                        plt.plot(t_corr, filt_neg, '-', color='lightpink', linewidth=0.8)

            # end delay loop

            plt.title(f"Abs value FIDs for minimum delay - Grad {gradient_selected}", fontsize=13)
            plt.xlabel("Time (ms)", fontsize=12)
            plt.ylabel("FID strength (a.u.)", fontsize=12)
            plt.legend(fontsize=11)
            plt.grid(True)
            plt.tight_layout()

            # Store figure for later save
            fig = plt.gcf()
            if apply_filter:
                filtered_tag = "_filtered"
            else:
                filtered_tag = ""
            
            fig._custom_filename = f"FID{filtered_tag}_Grad_{gradient_selected}_nDelay_{nDelay_selected}"
            fig._custom_save_path = _resolve_measurement_folder(base_path, setup, phantom_position)

            return fig

        except Exception as e:
            print(f"Error in {fname}: {e}")
            import traceback
            traceback.print_exc()

    return None


# =========================================================
# PHASE ANALYSIS
# =========================================================

def run_phase_analysis(
    base_path,
    setup,
    phantom_position,
    gradient_selected,
    nDelay_selected,
    apply_filter=False
):
    """
    Plot unwrapped phase of FID data for minimum delay (n=0).
    Only one gradient at a time (no 'All' option).
    """
    folder_path = _resolve_measurement_folder(base_path, setup, phantom_position)

    for fname in os.listdir(folder_path):
        if not fname.endswith(".mat") or fname.startswith("FID"):
            continue

        file_path = os.path.join(folder_path, fname)

        try:
            Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = \
                sequenceAnalysis(file_path)

            g = g_axis.lower()
            grad_letter = g.upper()

            # convert GUI selection like "GX" -> "X" for comparison
            sel_letter = gradient_selected[-1] if gradient_selected != "All" else None
            # Only process the selected gradient
            if sel_letter is not None and grad_letter != sel_letter:
                continue

            tFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)
            # time is already in milliseconds from sequenceAnalysis conversion
            t_ms = tFID

            plt.figure(figsize=(10, 6))

            any_legend = False
            for n in range(nDelays):
                delay_offset_ms = n * (deadTime + acqTime)
                t_corr = t_ms + delay_offset_ms

                fid_n = np.squeeze(fidsmap[n, :, :])
                phase_no_grad = np.unwrap(np.angle(fid_n[0, :]))
                phase_pos_grad = np.unwrap(np.angle(fid_n[1, :]))
                phase_neg_grad = np.unwrap(np.angle(fid_n[2, :]))
                phase_diff = phase_pos_grad - phase_neg_grad

                if apply_filter:
                    sos = signal.butter(4, 0.2, output='sos')
                    filt_no = signal.sosfilt(sos, phase_no_grad)
                    filt_pos = signal.sosfilt(sos, phase_pos_grad)
                    filt_neg = signal.sosfilt(sos, phase_neg_grad)
                    filt_diff = signal.sosfilt(sos, phase_diff)
                else:
                    filt_no = filt_pos = filt_neg = filt_diff = None

                if not any_legend:
                    plt.plot(t_corr, phase_no_grad, 'o', markersize=0.4, color='purple',
                             alpha=0.6, label='Phase_NoGrad')
                    plt.plot(t_corr, phase_pos_grad, 'o', markersize=0.4, color='cornflowerblue',
                             alpha=0.6, label='Phase_PositiveGrad')
                    plt.plot(t_corr, phase_neg_grad, 'o', markersize=0.4, color='lightpink',
                             alpha=0.6, label='Phase_NegativeGrad')
                    plt.plot(t_corr, phase_diff, 'o', markersize=0.4, color='gray',
                             alpha=0.6, label='Phase_Diff')
                    any_legend = True
                else:
                    plt.plot(t_corr, phase_no_grad, 'o', markersize=0.4, color='purple',
                             alpha=0.6)
                    plt.plot(t_corr, phase_pos_grad, 'o', markersize=0.4, color='cornflowerblue',
                             alpha=0.6)
                    plt.plot(t_corr, phase_neg_grad, 'o', markersize=0.4, color='lightpink',
                             alpha=0.6)
                    plt.plot(t_corr, phase_diff, 'o', markersize=0.4, color='gray',
                             alpha=0.6)

                if apply_filter and filt_no is not None:
                    if n == 0:
                        plt.plot(t_corr, filt_no, '-', color='purple', linewidth=0.8, label='Phase_NoGrad (Filtered)')
                        plt.plot(t_corr, filt_pos, '-', color='cornflowerblue', linewidth=0.8, label='Phase_PositiveGrad (Filtered)')
                        plt.plot(t_corr, filt_neg, '-', color='lightpink', linewidth=0.8, label='Phase_NegativeGrad (Filtered)')
                        plt.plot(t_corr, filt_diff, '-', color='gray', linewidth=0.8, label='Phase_Diff (Filtered)')
                    else:
                        plt.plot(t_corr, filt_no, '-', color='purple', linewidth=0.8)
                        plt.plot(t_corr, filt_pos, '-', color='cornflowerblue', linewidth=0.8)
                        plt.plot(t_corr, filt_neg, '-', color='lightpink', linewidth=0.8)
                        plt.plot(t_corr, filt_diff, '-', color='gray', linewidth=0.8)

            plt.title(f"Phase of FIDs for minimum delay - Grad {gradient_selected}", fontsize=13)
            plt.xlabel("Time (ms)", fontsize=12)
            plt.ylabel("Phase (radians)", fontsize=12)
            plt.legend(fontsize=11)
            plt.grid(True)
            plt.tight_layout()

            # Store figure for later save
            fig = plt.gcf()
            if apply_filter:
                filtered_tag = "_filtered"
            else:
                filtered_tag = ""
            
            fig._custom_filename = f"Phase{filtered_tag}_Grad_{gradient_selected}_nDelay_{nDelay_selected}"
            fig._custom_save_path = _resolve_measurement_folder(base_path, setup, phantom_position)

            return fig

        except Exception as e:
            print(f"Error in {fname}: {e}")
            import traceback
            traceback.print_exc()

    return None
