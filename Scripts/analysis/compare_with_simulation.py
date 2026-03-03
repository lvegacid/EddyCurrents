import os
import pandas as pd
import numpy as np

import matplotlib.pyplot as plt


# ---------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------

def load_measured_table(base_path, setup):
    """
    Load measured table:
    Beddy_measured_at_t0_<setup>.txt
    Handles both tab-separated and space-separated formats.
    """
    table_path = os.path.join(
        base_path,
        setup,
        f"Beddy_measured_at_t0_{setup}.txt"
    )

    if not os.path.exists(table_path):
        raise FileNotFoundError(f"Measured table not found:\n{table_path}")

    # Use delim_whitespace to handle any whitespace (tab, space, etc.)
    df = pd.read_csv(table_path, delim_whitespace=True, skipinitialspace=True)
    return df


def load_simulated_table(base_path, setup):
    """
    Load simulated table:
    Beddy_simulated_freq2500_<setup>.txt
    Handles both tab-separated and space-separated formats.
    """
    table_path = os.path.join(
        base_path,
        setup,
        f"Beddy_simulated_freq2500_{setup}.txt"
    )

    if not os.path.exists(table_path):
        raise FileNotFoundError(f"Simulated table not found:\n{table_path}")

    # Use delim_whitespace to handle any whitespace (tab, space, etc.)
    df = pd.read_csv(table_path, delim_whitespace=True, skipinitialspace=True)
    return df


# ---------------------------------------------------------
# MAIN COMPARISON FUNCTION
# ---------------------------------------------------------

def compare_with_simulation(
    base_path,
    setup,
    gradient,
    measured_column,
    plot_type="Points",
    save_figure=True
):
    """
    gradient: "X", "Y", "Z"
    measured_column:
        "B_measured_at_t0_FirstPoint"
        or
        "B_measured_at_t0_Fitted"

    plot_type:
        "Points" or "Histograms"
    """

    df_meas = load_measured_table(base_path, setup)
    df_sim = load_simulated_table(base_path, setup)

    # Debug: print column names
    print(f"Measured table columns: {list(df_meas.columns)}")
    print(f"Simulated table columns: {list(df_sim.columns)}")
    print(f"Looking for gradient: {gradient}")
    print(f"Measured column: {measured_column}")

    # Validate measured column exists
    if measured_column not in df_meas.columns:
        raise ValueError(
            f"Column '{measured_column}' not found in measured table.\n"
            f"Available columns: {list(df_meas.columns)}"
        )

    # Validate gradient column exists
    if "Grad" not in df_meas.columns:
        raise ValueError(
            f"Column 'Grad' not found in measured table.\n"
            f"Available columns: {list(df_meas.columns)}"
        )

    if "Grad" not in df_sim.columns:
        raise ValueError(
            f"Column 'Grad' not found in simulated table.\n"
            f"Available columns: {list(df_sim.columns)}"
        )

    # Filter by gradient
    df_meas = df_meas[df_meas["Grad"] == gradient]
    df_sim = df_sim[df_sim["Grad"] == gradient]

    # Merge on Phantom_position
    df = pd.merge(
        df_meas,
        df_sim,
        on=["Grad", "Phantom_position"],
        how="outer"
    )

    # Extract values (may contain NaN)
    positions = df["Phantom_position"]
    measured_vals = df[measured_column]
    simulated_vals = df["B_simulated_freq2500Hz"]

    # Remove rows where BOTH are NaN
    mask_valid = ~(measured_vals.isna() & simulated_vals.isna())
    positions = positions[mask_valid]
    measured_vals = measured_vals[mask_valid]
    simulated_vals = simulated_vals[mask_valid]

    # -------------------------------------------------
    # HISTOGRAM STYLE (mean absolute) ------------------
    # -------------------------------------------------
    if plot_type == "Histograms":
        # calculate mean absolute values for this setup/gradient
        mean_meas = np.mean(np.abs(measured_vals))
        mean_sim = np.mean(np.abs(simulated_vals))

        font = 40
        base_colors = {"GX": "Blues", "GY": "Reds", "GZ": "Greens"}
        cmap = plt.get_cmap(base_colors.get(f"G{gradient}", "Blues"))
        color = cmap(0.6)

        fig, ax = plt.subplots(figsize=(15, 13))
        x = np.arange(1)
        width = 0.35

        ax.bar(x - width/2, mean_meas, width, color=color, alpha=0.9, label="Measured")
        ax.bar(x + width/2, mean_sim, width, color='gray', alpha=0.8, label="Simulated")

        # percent difference relative to measured
        if mean_meas != 0:
            perc = (mean_meas - mean_sim) / mean_meas * 100
            ax.text(0, max(mean_meas, mean_sim) * 1.05,
                    f"{perc:.1f}%",
                    ha='center', va='bottom', fontsize=font, color="black")

        ax.set_xticks(x)
        ax.set_xticklabels([setup], fontsize=font)
        ax.set_ylabel(f"Mean |B_eddy| (µT)", fontsize=font)
        ax.tick_params(axis='y', labelsize=font)
        ax.grid(True, axis='y', linestyle='--', alpha=0.6)
        ax.legend(fontsize=font)
        plt.tight_layout()

        if save_figure:
            save_path = os.path.join(
                base_path,
                setup,
                f"Histogram_{gradient}.png"
            )
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Figure saved: {save_path}")

        return plt.gcf()

    # -------------------------------------------------
    # PLOT
    # -------------------------------------------------

    # ----------------------------------------------------------
    # PLOTS
    # ----------------------------------------------------------
    # fixed positions for phantom samples
    positions_map = {
        "X": {"-X": -50, "Center": 0, "+X": 50},
        "Y": {"-Y": -50, "Center": 0, "+Y": 50},
        "Z": {"-Z": -50, "Center": 0, "+Z": 50}
    }

    # choose a base colormap for the gradient
    cmap_dict = {"GX": "Blues", "GY": "Reds", "GZ": "Greens"}
    cmap = plt.get_cmap(cmap_dict.get(f"G{gradient}", "Blues"))
    color = cmap(0.6)

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for i, axis in enumerate(["X", "Y", "Z"]):
        keys = ["-" + axis, "Center", "+" + axis]
        pos = [positions_map[axis].get(k, np.nan) for k in keys]
        vals_meas = []
        vals_sim = []
        for k in keys:
            row = df[df["Phantom_position"] == k]
            if not row.empty:
                vals_meas.append(row[measured_column].values[0])
                vals_sim.append(row["B_simulated_freq2500Hz"].values[0])
            else:
                vals_meas.append(np.nan)
                vals_sim.append(np.nan)

        # measured: solid line with circles
        axes[i].plot(pos, vals_meas, 'o-', color=color, linewidth=2,
                     label="Measured" if i == 0 else "")
        # simulated: dashed line
        axes[i].plot(pos, vals_sim, '--', color=color, linewidth=2,
                     label="Simulated" if i == 0 else "")

        axes[i].set_xlabel(f"{axis} position (mm)")
        axes[i].set_ylabel(f"G{gradient} (µT)")
        axes[i].set_title(f"G{gradient} along {axis} axis")
        axes[i].grid(True)

    axes[0].legend(fontsize=9, loc='best')
    plt.suptitle(f"Comparison of Measured vs Simulated – G{gradient}", fontsize=14)
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    if save_figure:
        save_path = os.path.join(
            base_path,
            setup,
            f"Comparison_{gradient}_{plot_type}.png"
        )
        plt.savefig(save_path, dpi=300)
        print(f"Figure saved: {save_path}")

    return plt.gcf()