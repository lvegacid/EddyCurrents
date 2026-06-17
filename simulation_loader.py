import os
import re
from collections import defaultdict

import numpy as np
import pandas as pd


DEFAULT_SIMULATION_ROOT = (
    r"Z:\Projects\EddyCurrents\Data_acquisition\Simulation results\COMSOL_Time_domain"
)


class TimeDomainSimulationLoader:
    GRADIENTS = ("GX", "GY", "GZ")
    LOCATIONS = ("Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z")
    FILE_RE = re.compile(
        r"^Beddy_Time_Point_"
        r"(?P<location>Center|\+X|-X|\+Y|-Y|\+Z|-Z)"
        r"(?:_Offset_(?P<axis>[XYZ])_(?P<value>-?\d+(?:\.\d+)?)mm)?"
        r"\.txt$",
        re.IGNORECASE,
    )

    def __init__(self, simulation_root=DEFAULT_SIMULATION_ROOT, time_zero_ms=100.4):
        self.simulation_root = simulation_root
        self.time_zero_ms = float(time_zero_ms)

    def detect_available_offsets(self, setup_name):
        setup_dir = self._setup_dir(setup_name)
        if not os.path.isdir(setup_dir):
            return []

        found = set()
        for gradient in self.GRADIENTS:
            gradient_dir = os.path.join(setup_dir, gradient)
            if not os.path.isdir(gradient_dir):
                continue
            for location in self.LOCATIONS:
                point_dir = os.path.join(gradient_dir, location)
                if not os.path.isdir(point_dir):
                    continue
                for fname in os.listdir(point_dir):
                    parsed = self._parse_filename(fname)
                    if parsed and parsed["offset_key"]:
                        found.add(parsed["offset_key"])
        return sorted(found, key=self._offset_sort_key)

    def load_plot_ready_data(
        self,
        setup_name,
        gradients=None,
        locations=None,
        offset_mode="none",
        selected_offsets=None,
    ):
        result = {
            "curves": defaultdict(lambda: defaultdict(list)),
            "warnings": [],
            "setup_dir": self._setup_dir(setup_name),
        }

        setup_dir = result["setup_dir"]
        if not os.path.isdir(setup_dir):
            result["warnings"].append(f"No time-domain simulations found for {setup_name}")
            result["curves"] = self._freeze_curves(result["curves"])
            return result

        gradients = list(gradients or self.GRADIENTS)
        locations = list(locations or self.LOCATIONS)
        selected_offsets = set(selected_offsets or [])

        for gradient in gradients:
            gradient_dir = os.path.join(setup_dir, gradient)
            if not os.path.isdir(gradient_dir):
                result["warnings"].append(f"Time-domain simulations not found for {gradient}")
                continue

            for location in locations:
                point_dir = os.path.join(gradient_dir, location)
                if not os.path.isdir(point_dir):
                    result["warnings"].append(
                        f"Time-domain simulations not found for {gradient} / {location}"
                    )
                    continue

                location_curves = []
                nominal_loaded = False
                offset_seen = False

                for fname in sorted(os.listdir(point_dir)):
                    parsed = self._parse_filename(fname)
                    if not parsed or parsed["location"] != location:
                        continue

                    offset_key = parsed["offset_key"]
                    if offset_key is None:
                        if nominal_loaded:
                            continue
                        curve = self._load_curve(os.path.join(point_dir, fname), "Sim", None)
                        nominal_loaded = True
                    else:
                        if offset_mode == "none":
                            continue
                        if offset_mode == "selected" and offset_key not in selected_offsets:
                            continue
                        curve = self._load_curve(
                            os.path.join(point_dir, fname),
                            self._legend_label_for_offset(offset_key),
                            offset_key,
                        )
                        offset_seen = True

                    if curve is None:
                        result["warnings"].append(
                            f"Invalid time-domain simulation file: {os.path.join(point_dir, fname)}"
                        )
                        continue
                    location_curves.append(curve)

                if not location_curves:
                    if offset_mode == "none" or not offset_seen:
                        result["warnings"].append(
                            f"Time-domain simulations not found for {gradient} / {location}"
                        )
                    continue

                result["curves"][gradient][location].extend(location_curves)

        result["curves"] = self._freeze_curves(result["curves"])
        result["warnings"] = self._dedupe(result["warnings"])
        return result

    def _load_curve(self, file_path, label, offset_key):
        arr = self._read_numeric_txt(file_path)
        if arr is None or arr.shape[1] < 2:
            return None

        time_raw = np.asarray(arr[:, 0], dtype=float)
        values = np.asarray(arr[:, 1], dtype=float)
        finite_mask = np.isfinite(time_raw) & np.isfinite(values)
        time_raw = time_raw[finite_mask]
        values = values[finite_mask]
        if time_raw.size == 0:
            return None

        time_ms = self._to_milliseconds(time_raw)
        keep = time_ms >= self.time_zero_ms
        time_ms = time_ms[keep]
        values = values[keep]
        if time_ms.size == 0:
            return None

        return {
            "label": label,
            "offset_key": offset_key,
            "time_ms": time_ms - self.time_zero_ms,
            "values": values,
            "source_path": file_path,
        }

    def _read_numeric_txt(self, file_path):
        try:
            df = pd.read_csv(file_path, sep=r"\s+|\t+", engine="python", comment="#")
        except Exception:
            try:
                df = pd.read_csv(file_path, sep="\t", engine="python", comment="#")
            except Exception:
                return None

        if df is None or df.empty:
            return None

        numeric_cols = []
        for col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce")
            if series.notna().any():
                numeric_cols.append(series.to_numpy(dtype=float))
            if len(numeric_cols) >= 2:
                break

        if len(numeric_cols) < 2:
            return None

        return np.column_stack(numeric_cols[:2])

    def _to_milliseconds(self, time_values):
        finite = np.asarray(time_values[np.isfinite(time_values)], dtype=float)
        if finite.size == 0:
            return np.asarray(time_values, dtype=float)

        max_abs = float(np.nanmax(np.abs(finite)))
        if max_abs <= 5.0:
            return np.asarray(time_values, dtype=float) * 1000.0
        return np.asarray(time_values, dtype=float)

    def _parse_filename(self, fname):
        match = self.FILE_RE.match(str(fname or "").strip())
        if not match:
            return None
        location = match.group("location")
        axis = match.group("axis")
        value = match.group("value")
        offset_key = None
        if axis and value is not None:
            offset_key = f"Offset_{axis.upper()}_{self._compact_number(value)}mm"
        return {
            "location": location,
            "axis": axis.upper() if axis else None,
            "value": value,
            "offset_key": offset_key,
        }

    def _legend_label_for_offset(self, offset_key):
        match = re.match(r"^Offset_([XYZ])_(-?\d+(?:\.\d+)?)mm$", str(offset_key or ""))
        if not match:
            return f"Sim_{offset_key}"
        axis, value = match.groups()
        return f"Sim_Offset_{axis}{self._compact_number(value)}"

    def _setup_dir(self, setup_name):
        return os.path.join(self.simulation_root, str(setup_name or "").strip())

    def _compact_number(self, value):
        num = float(value)
        if abs(num - round(num)) < 1e-9:
            return str(int(round(num)))
        return f"{num:g}"

    def _offset_sort_key(self, offset_key):
        match = re.match(r"^Offset_([XYZ])_(-?\d+(?:\.\d+)?)mm$", str(offset_key or ""))
        if not match:
            return (99, str(offset_key))
        axis_order = {"X": 0, "Y": 1, "Z": 2}
        axis, value = match.groups()
        return (axis_order.get(axis, 99), float(value), str(offset_key))

    def _freeze_curves(self, curves):
        frozen = {}
        for gradient, loc_map in curves.items():
            frozen[gradient] = {location: list(items) for location, items in loc_map.items()}
        return frozen

    def _dedupe(self, items):
        seen = set()
        ordered = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered


class CylinderTimeDomainLoader(TimeDomainSimulationLoader):
    """
    Extends TimeDomainSimulationLoader for Cylinder files.

    Cylinder filenames follow the pattern:
        Beddy_Time_Cylinder_h<H>mm_r<R>mm_<Location>[_Offset_<Axis>_<Value>mm].txt

    Examples:
        Beddy_Time_Cylinder_h10mm_r5mm_Center.txt
        Beddy_Time_Cylinder_h10mm_r5mm_+X_Offset_X_5mm.txt

    All file-reading, curve-loading, filtering and time-conversion logic is
    inherited unchanged from TimeDomainSimulationLoader.  Only the filename
    regex, parameter extraction (H, R) and legend label generation differ.
    """

    FILE_RE = re.compile(
        r"^Beddy_Time_Cylinder_"
        r"h(?P<h>-?\d+(?:\.\d+)?)mm_"
        r"r(?P<r>-?\d+(?:\.\d+)?)mm_"
        r"(?P<location>Center|\+X|-X|\+Y|-Y|\+Z|-Z)"
        r"(?:_Offset_(?P<axis>[XYZ])_(?P<value>-?\d+(?:\.\d+)?)mm)?"
        r"\.txt$",
        re.IGNORECASE,
    )

    def __init__(self, simulation_root=DEFAULT_SIMULATION_ROOT, time_zero_ms=100.4):
        super().__init__(simulation_root=simulation_root, time_zero_ms=time_zero_ms)
        self._selected_h = None   # float mm or None = any
        self._selected_r = None   # float mm or None = any

    # ------------------------------------------------------------------
    # Public API additions
    # ------------------------------------------------------------------

    def detect_hr_values(self, setup_name):
        """
        Scan all Cylinder files in setup_name and return sorted lists of
        discovered H and R values (as compact strings like '10', '5.5').
        """
        setup_dir = self._setup_dir(setup_name)
        h_set = set()
        r_set = set()
        if not os.path.isdir(setup_dir):
            return [], []

        for gradient in self.GRADIENTS:
            gradient_dir = os.path.join(setup_dir, gradient)
            if not os.path.isdir(gradient_dir):
                continue
            for location in self.LOCATIONS:
                loc_dir = os.path.join(gradient_dir, location)
                if not os.path.isdir(loc_dir):
                    continue
                for fname in os.listdir(loc_dir):
                    parsed = self._parse_filename(fname)
                    if parsed:
                        h_set.add(parsed["h"])
                        r_set.add(parsed["r"])

        def _sort_key(v):
            try:
                return float(v)
            except Exception:
                return 0.0

        return (
            sorted(h_set, key=_sort_key),
            sorted(r_set, key=_sort_key),
        )

    def set_selected_hr(self, h_str, r_str):
        """Set the H and R filter applied during load_plot_ready_data."""
        try:
            self._selected_h = float(h_str) if h_str not in (None, "", "Any") else None
        except (ValueError, TypeError):
            self._selected_h = None
        try:
            self._selected_r = float(r_str) if r_str not in (None, "", "Any") else None
        except (ValueError, TypeError):
            self._selected_r = None

    def detect_available_offsets(self, setup_name):
        """Return offset keys found in Cylinder files for this setup."""
        setup_dir = self._setup_dir(setup_name)
        if not os.path.isdir(setup_dir):
            return []

        found = set()
        for gradient in self.GRADIENTS:
            gradient_dir = os.path.join(setup_dir, gradient)
            if not os.path.isdir(gradient_dir):
                continue
            for location in self.LOCATIONS:
                loc_dir = os.path.join(gradient_dir, location)
                if not os.path.isdir(loc_dir):
                    continue
                for fname in os.listdir(loc_dir):
                    parsed = self._parse_filename(fname)
                    if parsed and parsed["offset_key"]:
                        found.add(parsed["offset_key"])
        return sorted(found, key=self._offset_sort_key)

    # ------------------------------------------------------------------
    # Override: filename parsing
    # ------------------------------------------------------------------

    def _parse_filename(self, fname):
        match = self.FILE_RE.match(str(fname or "").strip())
        if not match:
            return None

        h_raw = match.group("h")
        r_raw = match.group("r")
        location = match.group("location")
        axis = match.group("axis")
        value = match.group("value")

        # Apply H/R filter if set
        if self._selected_h is not None:
            try:
                if abs(float(h_raw) - self._selected_h) > 1e-6:
                    return None
            except (ValueError, TypeError):
                pass
        if self._selected_r is not None:
            try:
                if abs(float(r_raw) - self._selected_r) > 1e-6:
                    return None
            except (ValueError, TypeError):
                pass

        offset_key = None
        if axis and value is not None:
            offset_key = f"Offset_{axis.upper()}_{self._compact_number(value)}mm"

        return {
            "location": location,
            "h": self._compact_number(h_raw),
            "r": self._compact_number(r_raw),
            "axis": axis.upper() if axis else None,
            "value": value,
            "offset_key": offset_key,
        }

    # ------------------------------------------------------------------
    # Override: legend label for nominal curve
    # ------------------------------------------------------------------

    def load_plot_ready_data(
        self,
        setup_name,
        gradients=None,
        locations=None,
        offset_mode="none",
        selected_offsets=None,
    ):
        """
        Identical flow to the parent, but nominal curves get a Cylinder label.
        """
        from collections import defaultdict

        result = {
            "curves": defaultdict(lambda: defaultdict(list)),
            "warnings": [],
            "setup_dir": self._setup_dir(setup_name),
        }

        setup_dir = result["setup_dir"]
        if not os.path.isdir(setup_dir):
            result["warnings"].append(f"No time-domain Cylinder simulations found for {setup_name}")
            result["curves"] = self._freeze_curves(result["curves"])
            return result

        gradients = list(gradients or self.GRADIENTS)
        locations = list(locations or self.LOCATIONS)
        selected_offsets = set(selected_offsets or [])

        h_label = self._compact_number(str(self._selected_h)) if self._selected_h is not None else "?"
        r_label = self._compact_number(str(self._selected_r)) if self._selected_r is not None else "?"
        nominal_label = f"Cylinder_R{r_label}_H{h_label}"

        for gradient in gradients:
            gradient_dir = os.path.join(setup_dir, gradient)
            if not os.path.isdir(gradient_dir):
                result["warnings"].append(f"Cylinder simulations not found for {gradient}")
                continue

            for location in locations:
                loc_dir = os.path.join(gradient_dir, location)
                if not os.path.isdir(loc_dir):
                    result["warnings"].append(
                        f"Cylinder simulations not found for {gradient} / {location}"
                    )
                    continue

                location_curves = []
                nominal_loaded = False
                offset_seen = False

                for fname in sorted(os.listdir(loc_dir)):
                    parsed = self._parse_filename(fname)
                    if not parsed or parsed["location"] != location:
                        continue

                    offset_key = parsed["offset_key"]
                    if offset_key is None:
                        if nominal_loaded:
                            continue
                        curve = self._load_curve(
                            os.path.join(loc_dir, fname), nominal_label, None
                        )
                        nominal_loaded = True
                    else:
                        if offset_mode == "none":
                            continue
                        if offset_mode == "selected" and offset_key not in selected_offsets:
                            continue
                        curve = self._load_curve(
                            os.path.join(loc_dir, fname),
                            self._legend_label_for_offset(offset_key),
                            offset_key,
                        )
                        offset_seen = True

                    if curve is None:
                        result["warnings"].append(
                            f"Invalid Cylinder simulation file: {os.path.join(loc_dir, fname)}"
                        )
                        continue
                    location_curves.append(curve)

                if not location_curves:
                    if offset_mode == "none" or not offset_seen:
                        result["warnings"].append(
                            f"Cylinder simulations not found for {gradient} / {location}"
                        )
                    continue

                result["curves"][gradient][location].extend(location_curves)

        result["curves"] = self._freeze_curves(result["curves"])
        result["warnings"] = self._dedupe(result["warnings"])
        return result
