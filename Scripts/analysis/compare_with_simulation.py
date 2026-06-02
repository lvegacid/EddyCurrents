import os
import pandas as pd
import numpy as np

import matplotlib.pyplot as plt


# ---------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------

def load_measured_table(base_path, setup, setup_key=None):
    """
    Load measured table:
    Beddy_measured_at_t0_<setup>.txt
    Handles both tab-separated and space-separated formats.
    """
    if setup_key is None:
        setup_key = setup

    table_path = os.path.join(base_path, setup, f"Beddy_measured_at_t0_{setup_key}.txt")

    legacy_path = os.path.join(base_path, setup, f"Beddy_measured_at_t0_{setup}.txt")
    if not os.path.exists(table_path) and os.path.exists(legacy_path):
        table_path = legacy_path

    if not os.path.exists(table_path):
        raise FileNotFoundError(f"Measured table not found:\n{table_path}")

    # Use delim_whitespace to handle any whitespace (tab, space, etc.)
    df = pd.read_csv(table_path, delim_whitespace=True, skipinitialspace=True)
    return df


def load_simulated_table(base_path, setup, setup_key=None):
    """
    Load simulated table:
    Beddy_simulated_freq2500_<setup>.txt
    Handles both tab-separated and space-separated formats.
    """
    # Primary expected location (legacy behavior)
    if setup_key is None:
        setup_key = setup

    expected_name = f"Beddy_simulated_freq2500_{setup_key}.txt"
    table_path = os.path.join(base_path, setup, expected_name)

    if os.path.exists(table_path):
        df = pd.read_csv(table_path, delim_whitespace=True, skipinitialspace=True)
        return df

    # If not found, also look in a sibling 'Simulations' folder placed
    # alongside the parent folder of the provided base_path.
    # Example: base_path = Z:\...\Data_acquisition\March2026
    #          simulations_dir = Z:\...\Data_acquisition\Simulations
    candidates = []

    parent = os.path.dirname(base_path)
    search_dirs = [
        os.path.join(parent, "Simulations"),
        os.path.join(base_path, "Simulations"),
        parent,
    ]

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not fname.lower().endswith('.txt'):
                continue
            # prefer filenames that end with the setup name
            lower = fname.lower()
            if lower.endswith(setup.lower() + '.txt'):
                # insert at front to prioritize exact-end matches
                candidates.insert(0, os.path.join(d, fname))
            elif setup.lower() in lower:
                candidates.append(os.path.join(d, fname))

    # If we still have no candidates, also try matching expected_name exactly
    if not candidates:
        for d in search_dirs:
            p = os.path.join(d, expected_name)
            if os.path.exists(p):
                candidates.append(p)
                break

    if not candidates:
        attempted = [table_path] + [os.path.join(d, expected_name) for d in search_dirs]
        raise FileNotFoundError(
            "Simulated table not found. Tried paths:\n" + "\n".join(attempted)
        )

    chosen = candidates[0]
    # Use delim_whitespace to handle any whitespace (tab, space, etc.)
    df = pd.read_csv(chosen, delim_whitespace=True, skipinitialspace=True)
    print(f"Loaded simulated table from: {chosen}")
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
    save_figure=True,
    cases=None
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

    if cases is None or len(cases) == 0:
        cases = [{
            "base_path": base_path,
            "setup": setup,
            "phantom": None,
        }]

    def _canonical_setup(name):
        text = str(name).strip()
        return text.split("_")[0] if "_" in text else text

    measured_cases = []
    simulated_by_setup = {}
    setup_measured_color = {}

    for case in cases:
        case_base = case.get("base_path", base_path)
        case_setup = case.get("setup", setup)
        case_setup_key = _canonical_setup(case_setup)

        df_meas = load_measured_table(case_base, case_setup, case_setup_key)
        df_sim = load_simulated_table(case_base, case_setup, case_setup_key)

        if measured_column not in df_meas.columns:
            raise ValueError(
                f"Column '{measured_column}' not found in measured table ({case_setup}).\n"
                f"Available columns: {list(df_meas.columns)}"
            )
        if "Grad" not in df_meas.columns:
            raise ValueError(f"Column 'Grad' not found in measured table ({case_setup}).")
        if "Grad" not in df_sim.columns:
            raise ValueError(f"Column 'Grad' not found in simulated table ({case_setup}).")

        df_meas = df_meas[df_meas["Grad"] == gradient]
        df_sim = df_sim[df_sim["Grad"] == gradient]

        measured_cases.append({
            "base_path": case_base,
            "setup": case_setup,
            "setup_key": case_setup_key,
            "data": df_meas,
        })

        if case_setup_key not in simulated_by_setup:
            simulated_by_setup[case_setup_key] = df_sim

    # -------------------------------------------------
    # HISTOGRAM STYLE ---------------------------------
    # -------------------------------------------------
    if plot_type == "Histograms":
        # measured bars (one per case)
        grad_base = {
            "X": np.array([0.05, 0.15, 0.55]),
            "Y": np.array([0.55, 0.05, 0.05]),
            "Z": np.array([0.05, 0.45, 0.05]),
        }.get(gradient, np.array([0.1, 0.1, 0.5]))

        measured_labels = []
        measured_vals = []
        measured_colors = []

        for idx, mc in enumerate(measured_cases):
            folder_tail = os.path.basename(os.path.normpath(mc["base_path"]))
            setup_name = mc["setup"]
            vals = mc["data"][measured_column].dropna().to_numpy(dtype=float)
            mean_meas = float(np.mean(np.abs(vals))) if vals.size > 0 else np.nan
            measured_vals.append(mean_meas)
            measured_labels.append(f"Measured_{folder_tail}_{setup_name}")

            lighten = min(0.85, 0.35 * idx)
            color = grad_base + (1.0 - grad_base) * lighten
            measured_color = tuple(np.clip(color, 0.0, 1.0))
            measured_colors.append(measured_color)
            if setup_name not in setup_measured_color:
                setup_measured_color[setup_name] = measured_color

        # simulated bars (one per unique setup)
        sim_labels = []
        sim_vals = []
        sim_colors = []
        sim_setups = list(simulated_by_setup.keys())
        use_black_sim = len(sim_setups) <= 1

        for idx, setup_name in enumerate(sim_setups):
            vals = simulated_by_setup[setup_name]["B_simulated_freq2500Hz"].dropna().to_numpy(dtype=float)
            mean_sim = float(np.mean(np.abs(vals))) if vals.size > 0 else np.nan
            sim_vals.append(mean_sim)
            sim_labels.append(f"Simulated_{setup_name}")
            if use_black_sim:
                sim_colors.append((0.0, 0.0, 0.0))
            else:
                sim_colors.append(setup_measured_color.get(setup_name, (0.0, 0.0, 0.0)))

        labels = measured_labels + sim_labels
        values = measured_vals + sim_vals
        colors = measured_colors + sim_colors

        fig, ax = plt.subplots(figsize=(15, 8))
        x = np.arange(len(labels))
        bars = ax.bar(x, values, color=colors, alpha=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=10)
        ax.set_ylabel("Mean |B_eddy| (µT)")
        ax.set_title(f"Measured vs Simulated Histograms – G{gradient}")
        ax.grid(True, axis='y', linestyle='--', alpha=0.6)

        for bar, v in zip(bars, values):
            if np.isfinite(v):
                ax.text(bar.get_x() + bar.get_width()/2, v, f"{v:.2f}", ha='center', va='bottom', fontsize=9)

        plt.tight_layout()

        if save_figure:
            save_path = os.path.join(base_path, setup, f"Histogram_G{gradient}.png")
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

    grad_base = {
        "X": np.array([0.05, 0.15, 0.55]),
        "Y": np.array([0.55, 0.05, 0.05]),
        "Z": np.array([0.05, 0.45, 0.05]),
    }.get(gradient, np.array([0.1, 0.1, 0.5]))

    sim_setups = list(simulated_by_setup.keys())
    use_black_sim = len(sim_setups) <= 1

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for i, axis in enumerate(["X", "Y", "Z"]):
        keys = ["-" + axis, "Center", "+" + axis]
        pos = [positions_map[axis].get(k, np.nan) for k in keys]

        for case_idx, mc in enumerate(measured_cases):
            df_meas_case = mc["data"]
            vals_meas = []
            for k in keys:
                row = df_meas_case[df_meas_case["Phantom_position"] == k]
                vals_meas.append(row[measured_column].values[0] if not row.empty else np.nan)

            lighten = min(0.85, 0.35 * case_idx)
            c = grad_base + (1.0 - grad_base) * lighten
            c = tuple(np.clip(c, 0.0, 1.0))
            folder_tail = os.path.basename(os.path.normpath(mc["base_path"]))
            setup_name = mc["setup"]
            if setup_name not in setup_measured_color:
                setup_measured_color[setup_name] = c
            meas_label = f"Measured_{folder_tail}_{setup_name}"

            axes[i].plot(pos, vals_meas, 'o-', color=c, linewidth=2,
                         label=meas_label if i == 0 else "")

        for sim_idx, setup_name in enumerate(sim_setups):
            df_sim_case = simulated_by_setup[setup_name]
            vals_sim = []
            for k in keys:
                row = df_sim_case[df_sim_case["Phantom_position"] == k]
                vals_sim.append(row["B_simulated_freq2500Hz"].values[0] if not row.empty else np.nan)

            if use_black_sim:
                sim_color = (0.0, 0.0, 0.0)
            else:
                sim_color = setup_measured_color.get(setup_name, (0.0, 0.0, 0.0))
            sim_label = f"Simulated_{setup_name}"
            axes[i].plot(pos, vals_sim, '--', color=sim_color, linewidth=2,
                         label=sim_label if i == 0 else "")

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