# -*- coding: utf-8 -*-
"""
Created on Mon Mar  2 18:03:42 2026

@author: cidve
"""

# analysis/table_manager.py

import os
import numpy as np
import pandas as pd


def update_t0_table(
    base_path,
    setup,
    grad,
    phantom_position,
    B0_values,
    B0_fitted_values=None,
    B0_prefilter_values=None,
    B_integrated_values=None,
    B_integrated_1ms_values=None,
    B_integrated_5ms_values=None,
    B_integrated_10ms_values=None,
    extra_metrics=None,
):

    expected_columns = [
        "Grad",
        "Phantom_position",
        "B_measured_at_t0_FirstPoint",
        "B_measured_at_t0_Fitted",
        "B_measured_at_t0_PreFiltered",
        "B_integrated",
        "B_integrated_1ms",
        "B_integrated_5ms",
        "B_integrated_10ms",
    ]

    def _norm_grad(value):
        text = str(value).strip().upper()
        if text.startswith("G") and len(text) > 1:
            text = text[1:]
        return text

    def _norm_pos(value):
        return str(value).strip().lower()

    def _safe_mean(values):
        if values is None:
            return None
        arr = np.asarray(list(values), dtype=float)
        if arr.size == 0:
            return None
        finite = np.isfinite(arr)
        if not np.any(finite):
            return None
        return float(np.nanmean(arr))

    def _canonical_setup(name):
        text = str(name).strip()
        return text.split("_")[0] if "_" in text else text

    def _to_scalar(value):
        if value is None:
            return None
        if isinstance(value, (list, tuple, np.ndarray)):
            return _safe_mean(value)
        try:
            val = float(value)
        except Exception:
            return None
        return val if np.isfinite(val) else None

    save_path = os.path.join(base_path, setup)
    os.makedirs(save_path, exist_ok=True)

    setup_canonical = _canonical_setup(setup)

    table_file = os.path.join(
        save_path,
        f"Beddy_measured_at_t0_{setup_canonical}.txt"
    )

    mean_value = _safe_mean(B0_values)
    mean_fitted = _safe_mean(B0_fitted_values)
    mean_prefilter = _safe_mean(B0_prefilter_values)
    mean_integrated = _safe_mean(B_integrated_values)
    mean_integrated_1ms = _safe_mean(B_integrated_1ms_values)
    mean_integrated_5ms = _safe_mean(B_integrated_5ms_values)
    mean_integrated_10ms = _safe_mean(B_integrated_10ms_values)

    grad_norm = _norm_grad(grad)
    pos_norm = _norm_pos(phantom_position)

    new_row = {
        "Grad": grad_norm,
        "Phantom_position": phantom_position,
        "B_measured_at_t0_FirstPoint": mean_value,
        "B_measured_at_t0_Fitted": mean_fitted,
        "B_measured_at_t0_PreFiltered": mean_prefilter,
        "B_integrated": mean_integrated,
        "B_integrated_1ms": mean_integrated_1ms,
        "B_integrated_5ms": mean_integrated_5ms,
        "B_integrated_10ms": mean_integrated_10ms,
    }

    extra_metrics = extra_metrics or {}
    extra_scalars = {}
    for key, value in extra_metrics.items():
        key_text = str(key).strip()
        if not key_text or key_text in new_row:
            continue
        extra_scalars[key_text] = _to_scalar(value)
        new_row[key_text] = extra_scalars[key_text]

    if os.path.exists(table_file):
        df = pd.read_csv(table_file, sep="\t")
        # Drop empty/unnamed columns that may appear due to legacy malformed separators.
        keep_cols = []
        for col in df.columns:
            col_text = str(col).strip()
            if not col_text:
                continue
            if col_text.lower().startswith("unnamed:"):
                continue
            keep_cols.append(col)
        df = df.loc[:, keep_cols]
    else:
        df = pd.DataFrame(columns=expected_columns)

    if "B_measured_at_t0_PreFiltered" not in df.columns:
        df["B_measured_at_t0_PreFiltered"] = np.nan
    df["B_measured_at_t0_PreFiltered"] = pd.to_numeric(
        df["B_measured_at_t0_PreFiltered"], errors="coerce"
    )

    if "B_integrated" not in df.columns:
        df["B_integrated"] = np.nan
    # Normalize legacy blanks/strings so duplicate resolution can reliably prefer real values.
    df["B_integrated"] = pd.to_numeric(df["B_integrated"], errors="coerce")

    if "B_integrated_1ms" not in df.columns:
        df["B_integrated_1ms"] = np.nan
    df["B_integrated_1ms"] = pd.to_numeric(df["B_integrated_1ms"], errors="coerce")

    if "B_integrated_5ms" not in df.columns:
        df["B_integrated_5ms"] = np.nan
    df["B_integrated_5ms"] = pd.to_numeric(df["B_integrated_5ms"], errors="coerce")

    if "B_integrated_10ms" not in df.columns:
        df["B_integrated_10ms"] = np.nan
    df["B_integrated_10ms"] = pd.to_numeric(df["B_integrated_10ms"], errors="coerce")

    for col in extra_scalars:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Grad" not in df.columns:
        df["Grad"] = ""
    if "Phantom_position" not in df.columns:
        df["Phantom_position"] = ""

    grad_key = df["Grad"].apply(_norm_grad)
    pos_key = df["Phantom_position"].apply(_norm_pos)

    mask = (grad_key == grad_norm) & (pos_key == pos_norm)

    if mask.any():
        df.loc[mask, "Grad"] = grad_norm
        df.loc[mask, "Phantom_position"] = phantom_position
        df.loc[mask, "B_measured_at_t0_FirstPoint"] = mean_value
        df.loc[mask, "B_measured_at_t0_Fitted"] = mean_fitted
        # Rewrite derived columns only when newly computed, so transient failures do not erase values.
        if mean_prefilter is not None:
            df.loc[mask, "B_measured_at_t0_PreFiltered"] = mean_prefilter
        if mean_integrated is not None:
            df.loc[mask, "B_integrated"] = mean_integrated
        if mean_integrated_1ms is not None:
            df.loc[mask, "B_integrated_1ms"] = mean_integrated_1ms
        if mean_integrated_5ms is not None:
            df.loc[mask, "B_integrated_5ms"] = mean_integrated_5ms
        if mean_integrated_10ms is not None:
            df.loc[mask, "B_integrated_10ms"] = mean_integrated_10ms
        for col, val in extra_scalars.items():
            if val is not None:
                df.loc[mask, col] = val
    else:
        df = pd.concat([df, pd.DataFrame([new_row])],
                       ignore_index=True)

    # Keep only one row per normalized (Grad, Phantom_position), preserving latest values
    df["__grad_key__"] = df["Grad"].apply(_norm_grad)
    df["__pos_key__"] = df["Phantom_position"].apply(_norm_pos)

    # If legacy duplicates exist, keep the last written one.
    df["__row_order__"] = np.arange(len(df), dtype=int)
    df = df.sort_values(["__grad_key__", "__pos_key__", "__row_order__"])
    df = df.drop_duplicates(subset=["__grad_key__", "__pos_key__"], keep="last")
    df = df.drop(columns=[
        "__grad_key__",
        "__pos_key__",
        "__row_order__",
    ])

    df = df.sort_values("Grad").reset_index(drop=True)

    # Write columns in a stable order to avoid visual shifts in TSV viewers.
    for col in expected_columns:
        if col not in df.columns:
            df[col] = np.nan

    preferred_extra = []
    window_tags = ["", "_1ms", "_3ms", "_5ms", "_10ms"]
    for base in [
        "B_integrated",
        "B_integrated_fitted",
        "B_integrated_prefiltered",
        "B_integrated_exp_fit1",
        "B_integrated_exp_fit2",
    ]:
        for suffix in window_tags:
            metric_col = f"{base}{suffix}"
            rmse_col = f"{metric_col}_RMSE%"
            preferred_extra.append(metric_col)
            preferred_extra.append(rmse_col)

    preferred_extra.extend([
        "exp_fit1_A1",
        "exp_fit1_tau1",
        "exp_fit2_A1",
        "exp_fit2_tau1",
        "exp_fit2_A2",
        "exp_fit2_tau2",
    ])

    existing_extra = [c for c in df.columns if c not in expected_columns]
    ordered_extra = [c for c in preferred_extra if c in existing_extra]
    ordered_extra.extend(sorted([c for c in existing_extra if c not in ordered_extra]))

    df = df.reindex(columns=expected_columns + ordered_extra)

    df.to_csv(table_file, sep="\t", index=False)