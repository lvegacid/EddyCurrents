#!/usr/bin/env python3
"""
Standalone metric calculator for a single .mat curve file.

This script is intentionally independent from the GUI and exposes the key
settings near the top so you can quickly iterate on masks, filters, and
integration options.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

import numpy as np
from scipy import signal
from scipy import integrate
from scipy import optimize




# ============================================================================
# User settings
# ============================================================================
# Input .mat file (same format used by GUI sequenceAnalysis)
MAT_FILE = r"Z:\Projects\EddyCurrents\Data_acquisition\May2026_Foils\0mm\Copper120\Lateral\+X\EDDYCURRENTS.2026.05.29.09.09.08.324.mat"  # Example: r"Z:\path\to\your\curve.mat"

# Time masks in milliseconds for masked integrals. Edit freely.
# Example: [1.0, 5.0, 10.0, 20.0]
MASK_WINDOWS_MS: List[float] = [1.0, 5.0, 10.0]

# Integration method: "trapz" or "simpson"
INTEGRATION_METHOD = "trapz"


# Aggregate across delays: "mean" (GUI-like), "median", or "none"
AGGREGATION = "mean"

# Fitting / filter options (same spirit as GUI prefilter)
USE_PREFILTER = True
PREFILTER_ORDER = 4
PREFILTER_CUTOFF_WN = 0.08  # Normalized cutoff in (0, 1)



# Output options
SAVE_CSV = False
CSV_OUTPUT_PATH = r"metrics_output.csv"

# Debug reconstruction details
DEBUG_RECONSTRUCTION = True

# Exponential fitting settings (additive module)
# Alias requested by user: ext_order
ext_order: List[int] = [1, 2, 3, 4, 5]
TARGET_RMSE_PERCENT = 2.0  # Example: 2.0. If None, target search is skipped.
PLOT_EXP_FITS = True
EXP_FITS_PLOT_PATH = r"exp_fits_comparison.png"
SHOW_EXP_FITS = True


# ============================================================================
# Input / file loading
# ============================================================================
def _import_sequence_analysis():
    """Import sequenceAnalysis from project analysis package.

    This keeps the loader/fit consistent with the GUI pipeline.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from analysis.sequence_analysis import sequenceAnalysis  # pylint: disable=import-error

    return sequenceAnalysis


def load_curve_from_mat(mat_file: str):
    if not mat_file or not os.path.isfile(mat_file):
        raise FileNotFoundError(f"MAT file not found: {mat_file}")

    sequence_analysis = _import_sequence_analysis()
    Be, BeddyFitted, tiempo, n_delays, g_axis, dead_time, acq_time, fidsmap, n_readouts = sequence_analysis(mat_file)

    return {
        "Be": np.asarray(Be, dtype=float),
        "BeddyFitted": np.asarray(BeddyFitted, dtype=float),
        "tiempo": np.asarray(tiempo, dtype=float),
        "nDelays": int(n_delays),
        "g_axis": str(g_axis),
        "deadTime": float(dead_time),
        "acqTime": float(acq_time),
        "fidsmap": fidsmap,
        "nReadouts": int(n_readouts),
    }


# ============================================================================
# Time masking / reconstruction
# ============================================================================
def reconstruct_continuous_series(
    curve: np.ndarray,
    base_time_ms: np.ndarray,
    dead_time_ms: float,
    acq_time_ms: float,
) -> Dict[str, object]:
    """Reconstruct full timeline using GUI logic: tiempo + n*(deadTime+acqTime).

    Returns concatenated points and debug metadata.
    """
    n_delays = int(curve.shape[0])
    delay_stride = float(dead_time_ms + acq_time_ms)

    x_concat = []
    y_concat = []
    per_delay_points = []
    gap_intervals = []

    prev_end_t = None
    for n in range(n_delays):
        delay_offset = n * delay_stride
        t_seg = np.asarray(base_time_ms, dtype=float) + delay_offset
        y_seg = np.asarray(curve[n, :], dtype=float)

        finite = np.isfinite(t_seg) & np.isfinite(y_seg)
        t_seg = t_seg[finite]
        y_seg = y_seg[finite]
        if t_seg.size == 0:
            per_delay_points.append(0)
            continue

        # Ensure monotonic segment order.
        order = np.argsort(t_seg)
        t_seg = t_seg[order]
        y_seg = y_seg[order]

        if prev_end_t is not None and float(t_seg[0]) > float(prev_end_t):
            # Gap is implicitly linearly interpolated by integration between
            # previous endpoint and current startpoint.
            gap_intervals.append((float(prev_end_t), float(t_seg[0])))

        x_concat.append(t_seg)
        y_concat.append(y_seg)
        per_delay_points.append(int(t_seg.size))
        prev_end_t = float(t_seg[-1])

    if x_concat:
        x = np.concatenate(x_concat)
        y = np.concatenate(y_concat)
        finite_all = np.isfinite(x) & np.isfinite(y)
        x = x[finite_all]
        y = y[finite_all]
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        x_rel = x - float(x[0])
    else:
        x = np.array([], dtype=float)
        y = np.array([], dtype=float)
        x_rel = x

    return {
        "x_abs": x,
        "x_rel": x_rel,
        "y": y,
        "n_delays": n_delays,
        "per_delay_points": per_delay_points,
        "gap_intervals": gap_intervals,
        "delay_stride_ms": delay_stride,
        "total_span_ms": float(x_rel[-1] - x_rel[0]) if x_rel.size > 1 else 0.0,
    }


def integrate_until_time(x: np.ndarray, y: np.ndarray, t_end: float, method: str) -> float:
    """Integrate y(x) from start up to t_end, including partial segment/gap via interpolation."""
    if x.size < 2:
        return np.nan

    t_end = float(t_end)
    if t_end <= float(x[0]):
        return 0.0

    if t_end >= float(x[-1]):
        return integrate_series(y, x, method)

    left_mask = x <= t_end
    x_cut = x[left_mask]
    y_cut = y[left_mask]
    if x_cut.size < 1:
        return 0.0

    # Add exact boundary point so masks cutting inside a delay or a gap
    # include the corresponding partial linear segment.
    if float(x_cut[-1]) < t_end:
        y_end = float(np.interp(t_end, x, y))
        x_cut = np.append(x_cut, t_end)
        y_cut = np.append(y_cut, y_end)

    if x_cut.size < 2:
        return 0.0
    return integrate_series(y_cut, x_cut, method)


def rmse_until_time(
    x_ref: np.ndarray,
    y_ref: np.ndarray,
    x_cmp: np.ndarray,
    y_cmp: np.ndarray,
    t_end: float,
) -> float:
    """RMSE between two curves up to t_end using linear interpolation on a common grid."""
    if x_ref.size < 2 or x_cmp.size < 2:
        return np.nan

    t_min = max(float(x_ref[0]), float(x_cmp[0]))
    t_max_common = min(float(x_ref[-1]), float(x_cmp[-1]))
    t_hi = min(float(t_end), t_max_common)

    if t_hi <= t_min:
        return np.nan

    x_union = np.union1d(x_ref, x_cmp)
    x_eval = x_union[(x_union >= t_min) & (x_union <= t_hi)]
    if x_eval.size < 2:
        return np.nan

    y_ref_i = np.interp(x_eval, x_ref, y_ref)
    y_cmp_i = np.interp(x_eval, x_cmp, y_cmp)
    return float(np.sqrt(np.mean((y_cmp_i - y_ref_i) ** 2)))


# ============================================================================
# Exponential fitting (additive module)
# ============================================================================
def _exp_model(t: np.ndarray, *params: float) -> np.ndarray:
    """Multi-exponential model with free-sign amplitudes:
    y(t) = sum_i A_i * exp(-t / tau_i)
    params = [A1, tau1, A2, tau2, ...]
    """
    t = np.asarray(t, dtype=float)
    y = np.zeros_like(t, dtype=float)
    n_terms = len(params) // 2
    for i in range(n_terms):
        a_i = float(params[2 * i])
        tau_i = float(params[2 * i + 1])
        y += a_i * np.exp(-t / tau_i)
    return y


def _initial_guess_for_order(order: int, x: np.ndarray, y: np.ndarray) -> List[float]:
    y_abs_max = float(np.nanmax(np.abs(y))) if y.size > 0 and np.any(np.isfinite(y)) else 1.0
    t_span = float(np.nanmax(x) - np.nanmin(x)) if x.size > 1 else 1.0
    if t_span <= 0:
        t_span = 1.0

    # Spread taus log-like across the signal duration.
    tau_grid = np.linspace(max(t_span * 0.05, 1e-6), max(t_span * 1.2, 2e-6), order)
    amp_grid = np.linspace(y_abs_max, y_abs_max / max(order, 1), order)

    p0 = []
    for i in range(order):
        p0.extend([float(amp_grid[i]), float(tau_grid[i])])
    return p0


def fit_exponentials_orders(
    x: np.ndarray,
    y: np.ndarray,
    orders: List[int],
) -> Dict[str, object]:
    """Fit Exp1..ExpN over full reconstructed curve and compute RMSE."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]

    if x.size < 3:
        return {"fits": [], "target_order": None}

    order_idx = np.argsort(x)
    x = x[order_idx]
    y = y[order_idx]

    # Work in non-negative relative time for stable tau interpretation.
    x = x - float(x[0])

    # Peak-to-peak from original reconstructed curve (reference for RMSE%).
    y_peak_to_peak = float(np.nanmax(y) - np.nanmin(y)) if y.size > 0 else np.nan

    fits = []
    for order in orders:
        if int(order) < 1:
            continue

        n = int(order)
        p0 = _initial_guess_for_order(n, x, y)

        # Amplitudes are unconstrained (mixed signs allowed), taus positive.
        lower_bounds = []
        upper_bounds = []
        for _ in range(n):
            lower_bounds.extend([-np.inf, 1e-9])
            upper_bounds.extend([np.inf, np.inf])

        try:
            popt, _ = optimize.curve_fit(
                _exp_model,
                x,
                y,
                p0=p0,
                bounds=(lower_bounds, upper_bounds),
                maxfev=50000,
            )
            y_fit = _exp_model(x, *popt)
            rmse = float(np.sqrt(np.mean((y - y_fit) ** 2)))
            rmse_percent = float(100.0 * rmse / y_peak_to_peak) if y_peak_to_peak > 0 else np.nan
            success = True
            error_msg = ""
        except Exception as exc:
            popt = np.asarray([], dtype=float)
            y_fit = np.full_like(y, np.nan, dtype=float)
            rmse = np.nan
            rmse_percent = np.nan
            success = False
            error_msg = str(exc)

        coeffs = {}
        if popt.size >= 2:
            for i in range(n):
                coeffs[f"A{i + 1}"] = float(popt[2 * i])
                coeffs[f"tau{i + 1}"] = float(popt[2 * i + 1])

        fits.append(
            {
                "name": f"Exp{n}",
                "order": n,
                "coefficients": coeffs,
                "rmse": rmse,
                "rmse_percent": rmse_percent,
                "success": success,
                "error": error_msg,
                "x": x,
                "y_fit": y_fit,
            }
        )

    target_order = None
    if TARGET_RMSE_PERCENT is not None:
        try:
            target = float(TARGET_RMSE_PERCENT)
            candidates = [
                f for f in fits
                if f["success"] and np.isfinite(f["rmse_percent"]) and f["rmse_percent"] < target
            ]
            if candidates:
                target_order = int(min(candidates, key=lambda d: d["order"])["order"])
        except Exception:
            target_order = None

    return {
        "fits": fits,
        "target_order": target_order,
    }


def plot_exponential_fits(x: np.ndarray, y: np.ndarray, fit_result: Dict[str, object], output_path: str):
    if not PLOT_EXP_FITS:
        return

    try:
        import matplotlib
        # If a non-interactive backend is active, switch to an interactive one.
        if SHOW_EXP_FITS and matplotlib.get_backend().lower() == "agg":
            try:
                matplotlib.use("TkAgg", force=True)
            except Exception:
                try:
                    matplotlib.use("QtAgg", force=True)
                except Exception:
                    pass
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"[warn] Could not import matplotlib for exponential-fit plot: {exc}")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x, y, "o", markersize=3, alpha=0.45, color="black", label="Reconstructed curve")

    fits = fit_result.get("fits", [])
    for fit in fits:
        if not fit.get("success", False):
            continue
        coeffs = fit.get("coefficients", {})
        terms = []
        order = int(fit.get("order", 0))
        for i in range(1, order + 1):
            a_key = f"A{i}"
            tau_key = f"tau{i}"
            if a_key in coeffs and tau_key in coeffs:
                terms.append(f"A{i}={coeffs[a_key]:.3g},tau{i}={coeffs[tau_key]:.3g}")

        coeff_text = " | ".join(terms)
        if coeff_text:
            legend_label = (
                f"{fit['name']} (RMSE={fit['rmse']:.6g}, RMSE%={fit.get('rmse_percent', np.nan):.3g}%) "
                f"[{coeff_text}]"
            )
        else:
            legend_label = (
                f"{fit['name']} (RMSE={fit['rmse']:.6g}, RMSE%={fit.get('rmse_percent', np.nan):.3g}%)"
            )

        ax.plot(fit["x"], fit["y_fit"], linewidth=2.0, label=legend_label)

    ax.set_title("Reconstructed curve with exponential fits")
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Signal")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)

    if SHOW_EXP_FITS:
        try:
            # Keep this after save so the file is always written even if display fails.
            plt.show(block=True)
        except Exception as exc:
            print(f"[warn] Could not display exponential-fit plot window: {exc}")

    plt.close(fig)


# ============================================================================
# Fitting options
# ============================================================================
def compute_prefilter_curve(data: Dict, order: int, cutoff_wn: float) -> np.ndarray:
    """Compute GUI-like prefiltered Be from phase difference derivatives."""
    fidsmap = data["fidsmap"]
    n_delays = data["nDelays"]
    n_readouts = data["nReadouts"]
    dead_time = data["deadTime"]
    acq_time = data["acqTime"]

    gamma_b = 42.577e6
    time_fid = np.linspace(dead_time, acq_time + dead_time, n_readouts)

    cutoff = float(np.clip(cutoff_wn, 0.01, 0.49))
    order = int(order)
    sos = signal.butter(order, cutoff, output="sos")

    be_pref = np.full((n_delays, n_readouts), np.nan, dtype=float)

    for n in range(n_delays):
        fid_n = np.squeeze(fidsmap[n, :, :])
        phase_pos = np.unwrap(np.angle(fid_n[1, :]))
        phase_neg = np.unwrap(np.angle(fid_n[2, :]))

        try:
            filt_pos = signal.sosfiltfilt(sos, phase_pos)
            filt_neg = signal.sosfiltfilt(sos, phase_neg)
        except ValueError:
            filt_pos = signal.sosfilt(sos, phase_pos)
            filt_neg = signal.sosfilt(sos, phase_neg)

        filt_diff = filt_pos - filt_neg
        be_pref[n, :] = (1.0 / (4.0 * np.pi * gamma_b)) * np.gradient(filt_diff, time_fid * 1e-3) * 1e6

    return be_pref


# ============================================================================
# Integration options
# ============================================================================
def integrate_series(y: np.ndarray, x: np.ndarray, method: str) -> float:
    if method == "simpson":
        if np.size(y) < 2:
            return np.nan
        return float(integrate.simpson(y, x=x))
    return float(integrate.trapezoid(y, x=x))


# ============================================================================
# Metric computation
# ============================================================================
def compute_integral_metrics(curve: np.ndarray, t_rel_ms: np.ndarray, windows_ms: List[float], method: str) -> Dict:
    raise NotImplementedError("Use compute_integral_metrics_reconstructed()")


def compute_integral_metrics_reconstructed(
    curve: np.ndarray,
    base_time_ms: np.ndarray,
    dead_time_ms: float,
    acq_time_ms: float,
    windows_ms: List[float],
    method: str,
) -> Dict[str, object]:
    """Compute cumulative integrals on reconstructed full timeline across all delays."""
    curve_abs = np.abs(np.asarray(curve, dtype=float))
    recon = reconstruct_continuous_series(curve_abs, base_time_ms, dead_time_ms, acq_time_ms)
    x_rel = recon["x_rel"]
    y = recon["y"]

    all_cumulative = integrate_until_time(x_rel, y, float(x_rel[-1]) if x_rel.size else 0.0, method)

    masked_cumulative = {}
    for w in windows_ms:
        masked_cumulative[w] = integrate_until_time(x_rel, y, float(w), method)

    # Keep per-delay metrics for compatibility/debug.
    per_delay_all = []
    per_delay_masked = {w: [] for w in windows_ms}
    t_seg_rel = np.asarray(base_time_ms, dtype=float)
    finite_t = np.isfinite(t_seg_rel)
    if np.any(finite_t):
        t_seg_rel = t_seg_rel - float(np.nanmin(t_seg_rel[finite_t]))

    for n in range(curve_abs.shape[0]):
        row = curve_abs[n, :]
        valid = np.isfinite(row) & np.isfinite(t_seg_rel)
        if np.sum(valid) >= 2:
            t_valid = t_seg_rel[valid]
            y_valid = row[valid]
            per_delay_all.append(integrate_series(y_valid, t_valid, method))
            for w in windows_ms:
                per_delay_masked[w].append(integrate_until_time(t_valid, y_valid, float(w), method))

    return {
        "all": per_delay_all,
        "all_cumulative": all_cumulative,
        "masked": per_delay_masked,
        "masked_cumulative": masked_cumulative,
        "debug": recon,
    }


def aggregate(values: List[float], mode: str):
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.nan
    if mode == "median":
        return float(np.nanmedian(arr))
    if mode == "none":
        return arr
    return float(np.nanmean(arr))


def build_results(data: Dict) -> Dict[str, object]:
    base_time_ms = np.asarray(data["tiempo"], dtype=float)
    dead_time_ms = float(data["deadTime"])
    acq_time_ms = float(data["acqTime"])

    sources = {
        "B_integrated_raw": data["Be"],
        "B_integrated_fitted": data["BeddyFitted"],
    }

    if USE_PREFILTER:
        sources["B_integrated_prefiltered"] = compute_prefilter_curve(
            data,
            order=PREFILTER_ORDER,
            cutoff_wn=PREFILTER_CUTOFF_WN,
        )

    # Reconstruct signed curves for RMSE comparison (reference = raw curve).
    recon_signed = {
        name: reconstruct_continuous_series(
            np.asarray(curve, dtype=float),
            base_time_ms,
            dead_time_ms,
            acq_time_ms,
        )
        for name, curve in sources.items()
    }
    ref_series = recon_signed["B_integrated_raw"]
    ref_x = ref_series["x_rel"]
    ref_y = ref_series["y"]

    # Additive exponential fitting family on full reconstructed raw curve.
    exp_fit_results = fit_exponentials_orders(ref_x, ref_y, ext_order)
    plot_exponential_fits(ref_x, ref_y, exp_fit_results, EXP_FITS_PLOT_PATH)

    results: Dict[str, object] = {
        "file": data,
        "metrics": {},
        "exp_fits": exp_fit_results,
    }

    for source_name, curve in sources.items():
        metric_raw = compute_integral_metrics_reconstructed(
            curve=curve,
            base_time_ms=base_time_ms,
            dead_time_ms=dead_time_ms,
            acq_time_ms=acq_time_ms,
            windows_ms=MASK_WINDOWS_MS,
            method=INTEGRATION_METHOD,
        )

        summary = {
            "all": metric_raw["all_cumulative"],
            "all_by_delay": metric_raw["all"],
            "masked": {},
            "masked_by_delay": {},
            "debug": metric_raw["debug"],
            "rmse_all": np.nan,
            "rmse_masked": {},
        }

        cur_series = recon_signed[source_name]
        cur_x = cur_series["x_rel"]
        cur_y = cur_series["y"]
        summary["rmse_all"] = rmse_until_time(ref_x, ref_y, cur_x, cur_y, float("inf"))

        for w in MASK_WINDOWS_MS:
            values = metric_raw["masked"].get(w, [])
            summary["masked"][w] = metric_raw["masked_cumulative"].get(w, np.nan)
            summary["masked_by_delay"][w] = values
            summary["rmse_masked"][w] = rmse_until_time(ref_x, ref_y, cur_x, cur_y, float(w))

        results["metrics"][source_name] = summary

    return results


# ============================================================================
# Results printing / saving
# ============================================================================
def print_results(results: Dict[str, object], mat_file: str):
    print("=" * 72)
    print("MAT curve metrics (standalone)")
    print("=" * 72)
    print(f"File: {mat_file}")

    data = results["file"]
    print(f"Gradient axis: {data['g_axis']}")
    print(f"nDelays: {data['nDelays']}")
    print(f"Integration: {INTEGRATION_METHOD}")
    print(f"Aggregation (legacy per-delay view): {AGGREGATION}")
    print(f"Mask windows (ms): {MASK_WINDOWS_MS}")
    if USE_PREFILTER:
        print(f"Prefilter: ON (order={PREFILTER_ORDER}, cutoff={PREFILTER_CUTOFF_WN})")
    else:
        print("Prefilter: OFF")

    print("-" * 72)

    for source_name, summary in results["metrics"].items():
        print(f"\n[{source_name}]")
        print(f"  B_integrated (all time): {summary['all']}  RMSE={summary['rmse_all']}")
        for w in MASK_WINDOWS_MS:
            print(f"  B_integrated_{w:g}ms: {summary['masked'][w]}  RMSE={summary['rmse_masked'][w]}")

        if DEBUG_RECONSTRUCTION:
            dbg = summary.get("debug", {})
            print(f"  [debug] total reconstructed span (ms): {dbg.get('total_span_ms')}")
            print(f"  [debug] points per delay: {dbg.get('per_delay_points')}")
            gaps = dbg.get("gap_intervals", [])
            print(f"  [debug] inserted gap intervals: {len(gaps)}")
            if gaps:
                print(f"  [debug] first gap interval (ms): {gaps[0]}")

    exp_data = results.get("exp_fits", {})
    exp_fits = exp_data.get("fits", [])
    if exp_fits:
        def _build_exp_coeff_table(fits: List[Dict[str, object]]) -> str:
            max_order = 0
            for fit_item in fits:
                coeffs_item = fit_item.get("coefficients", {})
                max_order = max(max_order, len(coeffs_item) // 2)

            headers = ["Fit", "RMSE", "RMSE%"]
            for i in range(1, max_order + 1):
                headers.extend([f"A{i}", f"tau{i}"])

            rows = []
            for fit_item in fits:
                row = [
                    str(fit_item.get("name", "")),
                    f"{fit_item.get('rmse', np.nan):.6g}",
                    f"{fit_item.get('rmse_percent', np.nan):.6g}",
                ]
                coeffs_item = fit_item.get("coefficients", {})
                for i in range(1, max_order + 1):
                    a_key = f"A{i}"
                    tau_key = f"tau{i}"
                    if a_key in coeffs_item:
                        row.append(f"{coeffs_item[a_key]:.6g}")
                    else:
                        row.append("")
                    if tau_key in coeffs_item:
                        row.append(f"{coeffs_item[tau_key]:.6g}")
                    else:
                        row.append("")
                rows.append(row)

            widths = [len(h) for h in headers]
            for row in rows:
                for j, cell in enumerate(row):
                    widths[j] = max(widths[j], len(cell))

            def _fmt(row_vals: List[str]) -> str:
                return " | ".join(val.ljust(widths[idx]) for idx, val in enumerate(row_vals))

            sep = "-+-".join("-" * w for w in widths)
            lines = [_fmt(headers), sep]
            for row in rows:
                lines.append(_fmt(row))
            return "\n".join(lines)

        print("\n" + "-" * 72)
        print("Exponential fit metrics (full reconstructed raw curve)")
        print("-" * 72)
        print(_build_exp_coeff_table(exp_fits))

        for fit in exp_fits:
            print(f"{fit['name']}: RMSE={fit['rmse']}  RMSE%={fit.get('rmse_percent', np.nan)}%")
            if fit.get("success", False):
                coeffs = fit.get("coefficients", {})
                coeff_text = ", ".join([f"{k}={v}" for k, v in coeffs.items()])
                print(f"  coefficients: {coeff_text}")
            else:
                print(f"  fit failed: {fit.get('error', '')}")

        if TARGET_RMSE_PERCENT is not None:
            target_order = exp_data.get("target_order", None)
            if target_order is None:
                print(f"Target RMSE%={TARGET_RMSE_PERCENT}: no order reached the threshold.")
            else:
                print(f"Minimum exponential order achieving RMSE% < {TARGET_RMSE_PERCENT}: Exp{target_order}")

        if PLOT_EXP_FITS:
            print(f"Exponential-fit plot saved to: {EXP_FITS_PLOT_PATH}")


def save_results_csv(results: Dict[str, object], output_path: str):
    rows = []
    for source_name, summary in results["metrics"].items():
        rows.append({
            "metric_source": source_name,
            "window_ms": "all",
            "value": summary["all"],
        })
        for w, v in summary["masked"].items():
            rows.append({
                "metric_source": source_name,
                "window_ms": float(w),
                "value": v,
            })

    # Manual CSV write keeps this script dependency-light.
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("metric_source,window_ms,value\n")
        for row in rows:
            f.write(f"{row['metric_source']},{row['window_ms']},{row['value']}\n")


# ============================================================================
# Main
# ============================================================================
def main():
    # Allow optional CLI override: python mat_curve_metrics.py <path_to_mat>
    mat_file = sys.argv[1].strip() if len(sys.argv) > 1 else MAT_FILE.strip()

    print(f"Script: {os.path.abspath(__file__)}")
    print(f"MAT_FILE (effective): {mat_file!r}")

    if not mat_file:
        raise ValueError(
            "No MAT file provided. Set MAT_FILE at the top of the script or pass it as first argument."
        )

    data = load_curve_from_mat(mat_file)
    results = build_results(data)
    print_results(results, mat_file)

    if SAVE_CSV:
        save_results_csv(results, CSV_OUTPUT_PATH)
        print(f"\nSaved CSV: {CSV_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
