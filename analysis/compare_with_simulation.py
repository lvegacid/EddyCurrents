import os
import re
import pandas as pd
import numpy as np

# choose a non-interactive backend so that plotting functions don't
# try to create their own Qt application and interfere with the GUI.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COMSOL_GRADIENTS = ("GX", "GY", "GZ")
COMSOL_LINESTYLE = (0, (1, 1, 1, 1))


def _normalize_gradient_token(gradient):
    g = str(gradient).strip().upper()
    if g in {"X", "GX"}:
        return "GX"
    if g in {"Y", "GY"}:
        return "GY"
    if g in {"Z", "GZ"}:
        return "GZ"
    return None


def _comsol_gradients_to_scan(gradient):
    g = str(gradient).strip().upper()
    if g == "ALL":
        return list(COMSOL_GRADIENTS)
    normalized = _normalize_gradient_token(g)
    return [normalized] if normalized else []


def _extract_case_name_from_sim_file(sim_file_path, fallback_setup):
    fname = os.path.basename(str(sim_file_path))
    match = re.match(r"^Beddy_simulated_freq\d+_(.+)\.txt$", fname, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return str(fallback_setup).strip()


def _resolve_comsol_root(base_path):
    parent = os.path.dirname(base_path)
    candidates = [
        os.path.join(parent, "Simulation results", "COMSOL_extracted_data"),
        os.path.join(base_path, "Simulation results", "COMSOL_extracted_data"),
        os.path.join(parent, "Simulations", "COMSOL_extracted_data"),
        os.path.join(base_path, "Simulations", "COMSOL_extracted_data"),
        r"Z:\Projects\EddyCurrents\Data_acquisition\Simulation results\COMSOL_extracted_data",
        r"Z:\Projects\EddyCurrents\Data_acquisition\Simulations\COMSOL_extracted_data",
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def _iter_comsol_case_dirs(comsol_root, gradient_token):
    grad_dir = os.path.join(comsol_root, gradient_token)
    if not os.path.isdir(grad_dir):
        return

    preferred_containers = ["MeasuredCases", "AllSimulations"]
    container_names = []
    for container in preferred_containers:
        container_dir = os.path.join(grad_dir, container)
        if os.path.isdir(container_dir):
            container_names.append(container)

    if not container_names:
        container_names = [""]

    for container in container_names:
        parent_dir = os.path.join(grad_dir, container) if container else grad_dir
        if not os.path.isdir(parent_dir):
            continue
        for entry in os.listdir(parent_dir):
            full_path = os.path.join(parent_dir, entry)
            if os.path.isdir(full_path):
                yield entry, full_path


def _find_matching_comsol_case_folder(comsol_root, gradient_token, case_name):
    case_name_lower = str(case_name).lower()
    for entry, full_path in _iter_comsol_case_dirs(comsol_root, gradient_token):
        if entry.lower().startswith(case_name_lower):
            return full_path

    for entry, full_path in _iter_comsol_case_dirs(comsol_root, gradient_token):
        if case_name_lower in entry.lower():
            return full_path

    return None


def _pick_comsol_txt_file(case_folder, axis_name):
    txt_files = [
        os.path.join(case_folder, name)
        for name in os.listdir(case_folder)
        if os.path.isfile(os.path.join(case_folder, name)) and name.lower().endswith(".txt")
    ]
    if not txt_files:
        return None

    axis = str(axis_name).upper()
    preferred_names = [
        f"beddy_line_{axis.lower()}.txt",
        f"beddy_line_{axis.upper()}.txt",
    ]

    for path in sorted(txt_files):
        lower_name = os.path.basename(path).lower()
        if lower_name in [n.lower() for n in preferred_names]:
            return path

    preferred_token = f"beddy_line_{axis.lower()}"
    for path in sorted(txt_files):
        lower_name = os.path.basename(path).lower()
        if preferred_token in lower_name:
            return path

    return None


def _load_comsol_curve(txt_path, axis_name):
    if txt_path is None or not os.path.exists(txt_path):
        return None, None

    x_vals = []
    y_vals = []
    float_pattern = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

    try:
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("%") or stripped.startswith("#"):
                    continue

                nums = float_pattern.findall(stripped)
                if len(nums) < 2:
                    continue

                try:
                    x_vals.append(float(nums[0]))
                    y_vals.append(float(nums[-1]))
                except Exception:
                    continue
    except Exception:
        return None, None

    if not x_vals or not y_vals:
        return None, None

    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return None, None

    x = x[finite]
    y = y[finite]

    # COMSOL line files are usually exported in meters; convert to mm for this plot.
    if np.nanmax(np.abs(x)) <= 1.0:
        x = x * 1000.0

    return x, y


def _clip_curve_with_outer_points(x, y, limit_mm=50.0):
    """Keep data inside +/-limit and include one outer point per side when available."""
    if x is None or y is None:
        return None, None

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return None, None

    x = x[finite]
    y = y[finite]

    inside = np.where(np.abs(x) <= float(limit_mm))[0]
    if inside.size == 0:
        return None, None

    selected = set(int(i) for i in inside)

    left = np.where(x < -float(limit_mm))[0]
    if left.size > 0:
        # Closest point below -limit (immediately outside the window)
        selected.add(int(left[np.argmax(x[left])]))

    right = np.where(x > float(limit_mm))[0]
    if right.size > 0:
        # Closest point above +limit (immediately outside the window)
        selected.add(int(right[np.argmin(x[right])]))

    idx = np.array(sorted(selected), dtype=int)
    x_sel = x[idx]
    y_sel = y[idx]

    # Draw lines in ascending x order for consistent rendering.
    order = np.argsort(x_sel)
    return x_sel[order], y_sel[order]


def _find_comsol_matches_for_case(base_path, case_name, gradient):
    comsol_root = _resolve_comsol_root(base_path)
    if not comsol_root:
        return {}

    matches = {}
    for grad_token in _comsol_gradients_to_scan(gradient):
        case_folder = _find_matching_comsol_case_folder(comsol_root, grad_token, case_name)
        if case_folder:
            matches[grad_token] = case_folder
    return matches


def _find_case_image(case_folder, preferred_name):
    if not case_folder or not os.path.isdir(case_folder):
        return None

    preferred_lower = str(preferred_name).lower()
    for name in os.listdir(case_folder):
        full_path = os.path.join(case_folder, name)
        if not os.path.isfile(full_path):
            continue
        if name.lower() == preferred_lower:
            return full_path
    return None


def _find_case_txt(case_folder, preferred_name):
    if not case_folder or not os.path.isdir(case_folder):
        return None

    preferred_lower = str(preferred_name).lower()
    for name in os.listdir(case_folder):
        full_path = os.path.join(case_folder, name)
        if not os.path.isfile(full_path):
            continue
        if name.lower() == preferred_lower:
            return full_path

    prefix = os.path.splitext(preferred_lower)[0]
    for name in os.listdir(case_folder):
        full_path = os.path.join(case_folder, name)
        if not os.path.isfile(full_path):
            continue
        lower_name = name.lower()
        if lower_name.endswith('.txt') and lower_name.startswith(prefix):
            return full_path

    return None


def _load_numeric_table(file_path):
    if not file_path or not os.path.isfile(file_path):
        return None

    try:
        arr = np.genfromtxt(file_path, comments='%', invalid_raise=False)
    except Exception:
        try:
            arr = np.genfromtxt(file_path, comments='#', invalid_raise=False)
        except Exception:
            return None

    if arr is None:
        return None

    arr = np.asarray(arr)
    if arr.size == 0:
        return None

    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    if arr.shape[1] == 0:
        return None

    finite_rows = np.isfinite(arr).any(axis=1)
    arr = arr[finite_rows]
    if arr.size == 0:
        return None

    return arr


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

    # Handle tabs/spaces robustly across pandas versions.
    df = pd.read_csv(table_path, sep=r"\s+", engine="python", skipinitialspace=True)
    return df


def _normalize_token(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _find_summary_case_column(header_tokens, setup_key, setup):
    targets = [_normalize_token(setup_key), _normalize_token(setup)]
    normalized = [(_normalize_token(tok), idx, tok) for idx, tok in enumerate(header_tokens)]

    for target in targets:
        if not target:
            continue
        for norm, idx, tok in normalized:
            if norm == target:
                return idx, tok
        for norm, idx, tok in normalized:
            if norm.startswith(target) or target in norm:
                return idx, tok
    return None, None


def _load_simulated_from_measuredcases_summary(summary_path, setup_key, setup, gradient, histogram_mode):
    if not summary_path or not os.path.isfile(summary_path):
        return None

    try:
        with open(summary_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    except Exception:
        return None

    if not lines:
        return None

    header_tokens = [tok.strip().strip('"') for tok in re.split(r"\t+", lines[0]) if tok.strip()]
    if len(header_tokens) < 2:
        return None

    case_col_idx, _ = _find_summary_case_column(header_tokens[1:], setup_key, setup)
    if case_col_idx is None:
        return None
    case_col_idx += 1  # account for metric column at position 0

    g = str(gradient).strip().upper()
    metric_by_pos = {
        "X": {"-X": "Beddy-X (uT)", "Center": "BeddyCenter (uT)", "+X": "Beddy+X (uT)"},
        "Y": {"-Y": "Beddy-Y (uT)", "Center": "BeddyCenter (uT)", "+Y": "Beddy+Y (uT)"},
        "Z": {"-Z": "Beddy-Z (uT)", "Center": "BeddyCenter (uT)", "+Z": "Beddy+Z (uT)"},
    }
    wanted = metric_by_pos.get(g)
    if not wanted:
        return None

    values_by_metric = {}
    for line in lines[1:]:
        parts = [tok.strip().strip('"') for tok in re.split(r"\t+", line)]
        if len(parts) <= case_col_idx:
            continue
        metric_name = parts[0]
        raw = parts[case_col_idx].replace(",", ".")
        try:
            values_by_metric[metric_name] = float(raw)
        except Exception:
            continue

    rows = []
    if str(histogram_mode).strip().lower().startswith("beddy_average_fov"):
        fov_metric = "Beddy_average_FOV (uT)"
        if fov_metric in values_by_metric:
            rows.append({
                "Grad": g,
                "Phantom_position": "Center",
                "B_simulated_freq2500Hz": values_by_metric[fov_metric],
            })
    else:
        # Point-by-point mode: average 7 absolute points then divide by 7.
        seven_metrics = [
            "Beddy+X (uT)",
            "Beddy-X (uT)",
            "Beddy+Y (uT)",
            "Beddy-Y (uT)",
            "Beddy+Z (uT)",
            "Beddy-Z (uT)",
            "BeddyCenter (uT)",
        ]

        vals7 = []
        for metric_name in seven_metrics:
            if metric_name not in values_by_metric:
                return None
            vals7.append(abs(float(values_by_metric[metric_name])))

        avg7 = float(sum(vals7) / 7.0)
        rows.append({
            "Grad": g,
            "Phantom_position": "Avg7Points",
            "B_simulated_freq2500Hz": avg7,
        })

    if not rows:
        return None
    return pd.DataFrame(rows)


def load_simulated_table(base_path, setup, setup_key=None, return_path=False, skip_global_fallback=False, gradient=None, histogram_mode="Beddy_average_FOV (uT)"):
    """
    Load simulated table:
    Beddy_simulated_freq2500_<setup>.txt
    Handles both tab-separated and space-separated formats.
    Returns None if file not found (simulated table is now optional).
    
    skip_global_fallback: If True, only searches in base_path/setup and COMSOL MeasuredCases,
                          skips global "Simulation results" folder fallback (used for histogram mode).
    """
    # Primary expected location (legacy behavior)
    if setup_key is None:
        setup_key = setup

    expected_name = f"Beddy_simulated_freq2500_{setup_key}.txt"
    table_path = os.path.join(base_path, setup, expected_name)

    # Histogram mode must rely on MeasuredCases summary table, not legacy per-case txt.
    if not skip_global_fallback and os.path.exists(table_path):
        df = pd.read_csv(table_path, sep=r"\s+", engine="python", skipinitialspace=True)
        return (df, table_path) if return_path else df

    comsol_root = _resolve_comsol_root(base_path)
    if comsol_root:
        for gradient_token in COMSOL_GRADIENTS:
            case_folder = _find_matching_comsol_case_folder(comsol_root, gradient_token, setup_key)
            if case_folder is None:
                case_folder = _find_matching_comsol_case_folder(comsol_root, gradient_token, setup)
            if case_folder is None:
                continue

            measured_cases_root = os.path.dirname(case_folder)
            is_measured_cases = str(os.path.basename(measured_cases_root)).lower() == "measuredcases"

            if skip_global_fallback:
                # Histogram mode: summary file in MeasuredCases only.
                if is_measured_cases:
                    summary_path = _find_case_txt(measured_cases_root, "Simulations_extracted_data.txt")
                    if summary_path:
                        df_summary = _load_simulated_from_measuredcases_summary(
                            summary_path,
                            setup_key=setup_key,
                            setup=setup,
                            gradient=gradient,
                            histogram_mode=histogram_mode,
                        )
                        if df_summary is not None and not df_summary.empty:
                            print(f"Loaded simulated summary table from: {summary_path}")
                            return (df_summary, summary_path) if return_path else df_summary
                continue

            preferred_names = [
                f"Beddy_simulated_freq2500_{setup_key}.txt",
                f"Beddy_simulated_freq2500_{setup}.txt",
                "Simulations_extracted_data.txt",
            ]
            for preferred_name in preferred_names:
                candidate = _find_case_txt(case_folder, preferred_name)
                if candidate and os.path.isfile(candidate):
                    df = pd.read_csv(candidate, sep=r"\s+", engine="python", skipinitialspace=True)
                    print(f"Loaded simulated table from: {candidate}")
                    return (df, candidate) if return_path else df

    # If skip_global_fallback is True, stop here and return None without searching global Simulation results
    if skip_global_fallback:
        return (None, None) if return_path else None

    # If not found, also look in sibling simulation folders placed
    # alongside the parent folder of the provided base_path.
    # Example: base_path = Z:\...\Data_acquisition\March2026
    #          simulations_dir = Z:\...\Data_acquisition\Simulation results
    candidates = []

    parent = os.path.dirname(base_path)
    search_dirs = [
        os.path.join(parent, "Simulation results"),
        os.path.join(base_path, "Simulation results"),
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
        # Simulated table is optional; return None if not found
        print(f"[INFO] Simulated table not found (optional). Continuing without it.")
        return (None, None) if return_path else None

    chosen = candidates[0]
    # Handle tabs/spaces robustly across pandas versions.
    df = pd.read_csv(chosen, sep=r"\s+", engine="python", skipinitialspace=True)
    print(f"Loaded simulated table from: {chosen}")
    return (df, chosen) if return_path else df


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
    cases=None,
    colormap="Single-color gradient",
    xlim_50mm=False,
    sim_histogram_mode="Beddy_average_FOV (uT)",
    normalize_histogram=False,
    custom_case_labels=None,
    apply_custom_hist_labels=False,
    include_simulation=True,
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

    if custom_case_labels is None:
        custom_case_labels = []

    def _canonical_setup(name):
        text = str(name).strip()
        return text.split("_")[0] if "_" in text else text

    # Prepare palette colors based on colormap selection
    palette_colors = None
    if colormap in ("Viridis", "Inferno") and len(cases) > 0:
        import matplotlib.cm as cm
        cmap = cm.get_cmap(colormap.lower())
        # For Inferno, cap the upper end at 0.70 so the lightest colour
        # keeps enough contrast against a white background.
        # For Viridis, 0.85 is fine (ends in green, not yellow).
        upper = 0.70 if colormap == "Inferno" else 0.85
        sample_range = np.linspace(0.0, upper, len(cases))
        palette_colors = [cmap(pos) for pos in sample_range]

    measured_cases = []
    simulated_by_setup = {}
    setup_measured_color = {}
    setup_display_label = {}

    for case in cases:
        case_base = case.get("base_path", base_path)
        case_setup = case.get("setup", setup)
        case_setup_key = _canonical_setup(case_setup)

        df_meas = load_measured_table(case_base, case_setup, case_setup_key)
        if include_simulation:
            df_sim, sim_file_path = load_simulated_table(
                case_base,
                case_setup,
                case_setup_key,
                return_path=True,
                skip_global_fallback=(plot_type == "Histograms"),
                gradient=gradient,
                histogram_mode=sim_histogram_mode,
            )
        else:
            df_sim, sim_file_path = None, None

        if measured_column not in df_meas.columns:
            raise ValueError(
                f"Column '{measured_column}' not found in measured table ({case_setup}).\n"
                f"Available columns: {list(df_meas.columns)}"
            )
        if "Grad" not in df_meas.columns:
            raise ValueError(f"Column 'Grad' not found in measured table ({case_setup}).")

        # Normalize measured column as numeric; blanks/invalid values become NaN.
        df_meas[measured_column] = pd.to_numeric(df_meas[measured_column], errors="coerce")
        
        # Simulated table is now optional
        if df_sim is not None:
            if "Grad" not in df_sim.columns:
                raise ValueError(f"Column 'Grad' not found in simulated table ({case_setup}).")
            df_sim = df_sim[df_sim["Grad"] == gradient]
        else:
            # Create empty DataFrame with same structure if table not found
            df_sim = pd.DataFrame(columns=["Grad", "Phantom_position", "B_simulated_freq2500Hz"])

        df_meas = df_meas[df_meas["Grad"] == gradient]

        measured_cases.append({
            "base_path": case_base,
            "setup": case_setup,
            "setup_key": case_setup_key,
            "data": df_meas,
        })

        if case_setup_key not in setup_display_label:
            setup_display_label[case_setup_key] = case_setup

        if include_simulation and case_setup_key not in simulated_by_setup:
            simulated_by_setup[case_setup_key] = {
                "data": df_sim,
                "sim_file_path": sim_file_path,
                "base_path": case_base,
            }

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
            if apply_custom_hist_labels and idx < len(custom_case_labels):
                display_label = str(custom_case_labels[idx]).strip() or setup_name
            else:
                display_label = f"{folder_tail}_{setup_name}"
            measured_labels.append(f"Measured_{display_label}")

            if palette_colors and idx < len(palette_colors):
                measured_color = palette_colors[idx]
            else:
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
            vals = simulated_by_setup[setup_name]["data"]["B_simulated_freq2500Hz"].dropna().to_numpy(dtype=float)
            mean_sim = float(np.mean(np.abs(vals))) if vals.size > 0 else np.nan
            sim_vals.append(mean_sim)
            if apply_custom_hist_labels:
                # Match simulated setup to first measured case with the same setup key.
                custom_idx = None
                for i_case, mc in enumerate(measured_cases):
                    if mc.get("setup_key") == setup_name:
                        custom_idx = i_case
                        break
                if custom_idx is not None and custom_idx < len(custom_case_labels):
                    sim_display = str(custom_case_labels[custom_idx]).strip() or setup_display_label.get(setup_name, setup_name)
                else:
                    sim_display = setup_display_label.get(setup_name, setup_name)
            else:
                sim_display = setup_display_label.get(setup_name, setup_name)
            sim_labels.append(f"Simulated_{sim_display}")
            if use_black_sim:
                sim_colors.append((0.0, 0.0, 0.0))
            else:
                sim_colors.append(setup_measured_color.get(setup_name, (0.0, 0.0, 0.0)))

        labels = measured_labels + sim_labels
        values = measured_vals + sim_vals
        colors = measured_colors + sim_colors

        if normalize_histogram:
            meas_finite = [abs(v) for v in measured_vals if np.isfinite(v)]
            sim_finite = [abs(v) for v in sim_vals if np.isfinite(v)]

            meas_ref = max(meas_finite) if meas_finite else None
            sim_ref = max(sim_finite) if sim_finite else None

            if meas_ref and meas_ref > 0:
                measured_vals = [v / meas_ref if np.isfinite(v) else np.nan for v in measured_vals]
            if sim_ref and sim_ref > 0:
                sim_vals = [v / sim_ref if np.isfinite(v) else np.nan for v in sim_vals]

            values = measured_vals + sim_vals

        fig, ax = plt.subplots(figsize=(15, 8))
        x = np.arange(len(labels))
        bars = ax.bar(x, values, color=colors, alpha=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=10)
        ax.set_ylabel(
            "Normalized Mean |B_eddy| (measured max = 1, simulated max = 1)"
            if normalize_histogram else
            "Mean |B_eddy| (µT)"
        )
        if include_simulation:
            ax.set_title(f"Measured vs Simulated Histograms – G{gradient}")
        else:
            ax.set_title(f"Measured Histograms – G{gradient}")
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

    invert_sim_sign = str(gradient).strip().upper() in {"Z", "GZ"}

    sim_setups = list(simulated_by_setup.keys())
    use_black_sim = len(sim_setups) <= 1
    comsol_label_added = False
    comsol_matches_by_setup = {}
    sim_axis_source = {"X": "X", "Y": "Y", "Z": "Z"}

    for setup_name in sim_setups:
        sim_meta = simulated_by_setup[setup_name]
        case_name = _extract_case_name_from_sim_file(sim_meta.get("sim_file_path"), setup_name)
        comsol_matches_by_setup[setup_name] = _find_comsol_matches_for_case(
            sim_meta.get("base_path", base_path),
            case_name,
            gradient,
        )

    preferred_setup_key = measured_cases[0]["setup_key"] if measured_cases else None
    search_setup_order = []
    if preferred_setup_key:
        search_setup_order.append(preferred_setup_key)
    for setup_name in sim_setups:
        if setup_name not in search_setup_order:
            search_setup_order.append(setup_name)

    show_setup_visuals = str(gradient).strip().upper() != "ALL" and len(search_setup_order) > 0
    if show_setup_visuals:
        n_visuals = 2 * len(search_setup_order)
        bottom_cols = max(n_visuals + 2, 6)
        fig_width = max(18, 4.8 * max(3, n_visuals))
        fig = plt.figure(figsize=(fig_width, 8.0), constrained_layout=True)
        outer_gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 1.0], hspace=0.35)
        top_gs = outer_gs[0].subgridspec(1, 3)
        bottom_gs = outer_gs[1].subgridspec(1, bottom_cols)
        plot_axes = [fig.add_subplot(top_gs[0, i]) for i in range(3)]
    else:
        fig, axes = plt.subplots(1, 3, figsize=(18, 4.8), constrained_layout=True)
        plot_axes = list(axes)

    for i, axis in enumerate(["X", "Y", "Z"]):
        keys = ["-" + axis, "Center", "+" + axis]
        pos = [positions_map[axis].get(k, np.nan) for k in keys]
        measured_linewidth = 3.2
        simulated_linewidth = 3.2

        for case_idx, mc in enumerate(measured_cases):
            df_meas_case = mc["data"]
            vals_meas = []
            for k in keys:
                row = df_meas_case[df_meas_case["Phantom_position"] == k]
                vals_meas.append(row[measured_column].values[0] if not row.empty else np.nan)

            if palette_colors and case_idx < len(palette_colors):
                c = palette_colors[case_idx]
            else:
                lighten = min(0.85, 0.35 * case_idx)
                c = grad_base + (1.0 - grad_base) * lighten
                c = tuple(np.clip(c, 0.0, 1.0))
            folder_tail = os.path.basename(os.path.normpath(mc["base_path"]))
            setup_name = mc["setup"]
            if setup_name not in setup_measured_color:
                setup_measured_color[setup_name] = c
            meas_label = f"Measured_{folder_tail}_{setup_name}"

            plot_axes[i].plot(pos, vals_meas, 'o-', color=c, linewidth=measured_linewidth,
                         label=meas_label if i == 0 else "")

        for sim_idx, setup_name in enumerate(sim_setups):
            sim_meta = simulated_by_setup[setup_name]
            df_sim_case = sim_meta["data"]

            if use_black_sim:
                sim_color = (0.0, 0.0, 0.0)
            else:
                sim_color = setup_measured_color.get(setup_name, (0.0, 0.0, 0.0))

            # Do not plot per-position points from Beddy_simulated_freq2500*.txt.
            # Keep only COMSOL continuous curves as simulation overlay.

            comsol_matches = comsol_matches_by_setup.get(setup_name, {})

            source_axis = sim_axis_source.get(axis, axis)

            for case_folder in comsol_matches.values():
                txt_path = _pick_comsol_txt_file(case_folder, source_axis)
                try:
                    x_comsol, y_comsol = _load_comsol_curve(txt_path, source_axis)
                except Exception:
                    continue
                if x_comsol is None or y_comsol is None:
                    continue
                # Apply xlim 50mm filter if requested
                if xlim_50mm:
                    x_comsol, y_comsol = _clip_curve_with_outer_points(x_comsol, y_comsol, limit_mm=50.0)
                    if x_comsol is None or y_comsol is None:
                        continue
                    if len(x_comsol) == 0 or len(y_comsol) == 0:
                        continue
                if invert_sim_sign:
                    y_comsol = -y_comsol
                legend_label = "simulated curve" if (i == 0 and not comsol_label_added) else ""
                plot_axes[i].plot(
                    x_comsol,
                    y_comsol,
                    linestyle=COMSOL_LINESTYLE,
                    color=sim_color,
                    linewidth=simulated_linewidth,
                    label=legend_label,
                )
                if legend_label:
                    comsol_label_added = True

        plot_axes[i].set_xlabel(f"{axis} position (mm)")
        plot_axes[i].set_ylabel(f"G{gradient} (µT)")
        plot_axes[i].set_title(f"G{gradient} along {axis} axis")
        plot_axes[i].grid(True)

    # Apply xlim 50mm to all plot axes if requested
    if xlim_50mm:
        for ax in plot_axes:
            ax.set_xlim(-50, 50)

    plot_axes[0].legend(fontsize=9, loc='best')

    if show_setup_visuals:
        n_visuals = 2 * len(search_setup_order)
        start_col = max(0, (bottom_cols - n_visuals) // 2)

        def _apply_isometric_fov_view(ax):
            ax.set_box_aspect((1, 1, 1))
            try:
                ax.set_proj_type('ortho')
            except Exception:
                pass
            ax.view_init(elev=35.264, azim=-45)

        for i_setup, setup_name in enumerate(search_setup_order):
            comsol_matches = comsol_matches_by_setup.get(setup_name, {})
            case_folder = next(iter(comsol_matches.values()), None)

            view_col = start_col + 2 * i_setup
            fov_col = view_col + 1

            ax_view = fig.add_subplot(bottom_gs[0, view_col])
            view3d_path = _find_case_image(case_folder, "Beddy_3DView.png")
            if view3d_path is not None:
                try:
                    ax_view.imshow(plt.imread(view3d_path))
                    ax_view.set_title(f"{setup_name} - Beddy_3DView")
                except Exception:
                    ax_view.set_title(f"{setup_name} - Beddy_3DView (invalid)")
            else:
                ax_view.set_title(f"{setup_name} - Beddy_3DView (missing)")
            ax_view.axis('off')

            ax_fov = fig.add_subplot(bottom_gs[0, fov_col])
            fov_png_path = _find_case_image(case_folder, "Beddy_FOV.png")
            if fov_png_path is not None:
                try:
                    ax_fov.imshow(plt.imread(fov_png_path))
                    ax_fov.set_title(f"{setup_name} - Beddy_FOV")
                    ax_fov.axis('off')
                except Exception:
                    ax_fov.set_title(f"{setup_name} - Beddy_FOV (invalid)")
                    ax_fov.set_axis_off()
            else:
                fov_txt_path = _find_case_txt(case_folder, "Beddy_FOV.txt")
                fov_data = _load_numeric_table(fov_txt_path)
                if fov_data is not None and fov_data.shape[1] >= 4:
                    ax_fov.remove()
                    ax_fov = fig.add_subplot(bottom_gs[0, fov_col], projection='3d')
                    fov_values = -fov_data[:, -1] if invert_sim_sign else fov_data[:, -1]
                    scat = ax_fov.scatter(
                        fov_data[:, 0],
                        fov_data[:, 2],
                        fov_data[:, 1],
                        c=fov_values,
                        cmap='rainbow',
                        s=6,
                        alpha=0.8,
                    )
                    ax_fov.set_title(f"{setup_name} - Beddy_FOV")
                    ax_fov.set_xlabel('X')
                    ax_fov.set_ylabel('Z')
                    ax_fov.set_zlabel('Y')
                    _apply_isometric_fov_view(ax_fov)
                    try:
                        cbar = fig.colorbar(scat, ax=ax_fov, fraction=0.03, pad=0.08)
                        cbar.set_label('Beddy (uT)')
                    except Exception:
                        pass
                else:
                    ax_fov.set_title(f"{setup_name} - Beddy_FOV (missing)")
                    ax_fov.set_axis_off()

    plt.suptitle(f"Comparison of Measured vs Simulated – G{gradient}", fontsize=14)
    if not show_setup_visuals:
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