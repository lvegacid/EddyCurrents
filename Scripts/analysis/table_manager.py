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
    B0_prefilter_values=None
):

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

    grad_norm = _norm_grad(grad)
    pos_norm = _norm_pos(phantom_position)

    new_row = {
        "Grad": grad_norm,
        "Phantom_position": phantom_position,
        "B_measured_at_t0_FirstPoint": mean_value,
        "B_measured_at_t0_Fitted": mean_fitted,
        "B_measured_at_t0_PreFiltered": mean_prefilter
    }

    if os.path.exists(table_file):
        df = pd.read_csv(table_file, sep="\t")
    else:
        df = pd.DataFrame(columns=[
            "Grad",
            "Phantom_position",
            "B_measured_at_t0_FirstPoint",
            "B_measured_at_t0_Fitted",
            "B_measured_at_t0_PreFiltered"
        ])

    if "B_measured_at_t0_PreFiltered" not in df.columns:
        df["B_measured_at_t0_PreFiltered"] = np.nan

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
        if mean_prefilter is not None:
            df.loc[mask, "B_measured_at_t0_PreFiltered"] = mean_prefilter
    else:
        df = pd.concat([df, pd.DataFrame([new_row])],
                       ignore_index=True)

    # Keep only one row per normalized (Grad, Phantom_position), preserving latest values
    df["__grad_key__"] = df["Grad"].apply(_norm_grad)
    df["__pos_key__"] = df["Phantom_position"].apply(_norm_pos)
    df = df.drop_duplicates(subset=["__grad_key__", "__pos_key__"], keep="last")
    df = df.drop(columns=["__grad_key__", "__pos_key__"])

    df = df.sort_values("Grad").reset_index(drop=True)

    df.to_csv(table_file, sep="\t", index=False)