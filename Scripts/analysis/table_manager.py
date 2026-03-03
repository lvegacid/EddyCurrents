# -*- coding: utf-8 -*-
"""
Created on Mon Mar  2 18:03:42 2026

@author: cidve
"""

# analysis/table_manager.py

import os
import pandas as pd


def update_t0_table(base_path, setup, grad, phantom_position, B0_values, B0_fitted_values=None):

    save_path = os.path.join(base_path, setup)
    os.makedirs(save_path, exist_ok=True)

    table_file = os.path.join(
        save_path,
        f"Beddy_measured_at_t0_{setup}.txt"
    )

    mean_value = float(sum(B0_values) / len(B0_values))
    mean_fitted = float(sum(B0_fitted_values) / len(B0_fitted_values)) if B0_fitted_values else None

    new_row = {
        "Grad": grad,
        "Phantom_position": phantom_position,
        "B_measured_at_t0_FirstPoint": mean_value,
        "B_measured_at_t0_Fitted": mean_fitted
    }

    if os.path.exists(table_file):
        df = pd.read_csv(table_file, sep="\t")
    else:
        df = pd.DataFrame(columns=[
            "Grad",
            "Phantom_position",
            "B_measured_at_t0_FirstPoint",
            "B_measured_at_t0_Fitted"
        ])

    mask = (df["Grad"] == grad) & \
           (df["Phantom_position"] == phantom_position)

    if mask.any():
        df.loc[mask, "B_measured_at_t0_FirstPoint"] = mean_value
        df.loc[mask, "B_measured_at_t0_Fitted"] = mean_fitted
    else:
        df = pd.concat([df, pd.DataFrame([new_row])],
                       ignore_index=True)

    df = df.sort_values("Grad")

    df.to_csv(table_file, sep="\t", index=False)