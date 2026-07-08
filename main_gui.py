# -*- coding: utf-8 -*-

import sys
import os
import importlib.util
import subprocess
import shutil
import re
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")


def _ensure_package(pkg_name: str):
    try:
        __import__(pkg_name)
    except ImportError:
        print(f"Package '{pkg_name}' not found; installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
        __import__(pkg_name)


for _pkg in ["numpy", "scipy", "matplotlib", "pandas", "PyQt5", "scipy.io"]:
    _ensure_package(_pkg)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QMessageBox, QListWidget, QListWidgetItem, QInputDialog,
    QScrollArea, QCheckBox, QRubberBand, QDialog, QGroupBox,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView,
)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt, QSettings, QPoint, QRect

from analysis.measured_analysis import (
    run_measured_analysis,
    run_fid_analysis,
    run_phase_analysis,
    extract_filter_metrics_sweep,
)
from analysis.compare_with_simulation import compare_with_simulation, load_measured_table
from analysis.sequence_analysis import sequenceAnalysis
from simulation_loader import TimeDomainSimulationLoader, CylinderTimeDomainLoader


class FileList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setMinimumHeight(40)
        self.setMaximumHeight(80)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.addItem(path)


class CompareFileItemWidget(QWidget):
    def __init__(self, file_path, default_label):
        super().__init__()
        self.file_path = file_path
        self.remove_callback = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._label_edit = QLineEdit(default_label)
        layout.addWidget(self._label_edit)

        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(self._on_remove)
        layout.addWidget(rm_btn)

    def _on_remove(self):
        if callable(self.remove_callback):
            self.remove_callback(self.file_path)

    def get_label(self):
        text = self._label_edit.text().strip()
        return text if text else os.path.splitext(os.path.basename(self.file_path))[0]


class CompareFileListWidget(QListWidget):
    def __init__(self, gui_ref=None):
        super().__init__()
        self.gui_ref = gui_ref
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setMinimumHeight(80)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.gui_ref is not None and hasattr(self.gui_ref, "compare_drop_event"):
            self.gui_ref.compare_drop_event(event)
            return
        event.ignore()


class CopyableTableWidget(QTableWidget):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            ranges = self.selectedRanges()
            if not ranges:
                return
            r = ranges[0]
            lines = []
            for row in range(r.topRow(), r.bottomRow() + 1):
                vals = []
                for col in range(r.leftColumn(), r.rightColumn() + 1):
                    item = self.item(row, col)
                    vals.append(item.text() if item is not None else "")
                lines.append("\t".join(vals))
            QApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)


class _AddManuallyDialog(QDialog):
    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self._gui = gui
        self.setWindowTitle("Add files manually")
        self.setMinimumWidth(600)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select .mat files and copy them into the selected Setup/Phantom folder."))

        self._files = FileList()
        layout.addWidget(self._files)

        btn_row = QHBoxLayout()
        browse_btn = QPushButton("Add files")
        browse_btn.clicked.connect(self._browse_files)
        btn_row.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._files.clear)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        run_row = QHBoxLayout()
        run_btn = QPushButton("Copy")
        run_btn.clicked.connect(self._run_copy)
        run_row.addWidget(run_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        run_row.addWidget(cancel_btn)
        layout.addLayout(run_row)

    def _browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select .mat files", "", "MAT Files (*.mat)")
        for f in files:
            self._files.addItem(f)

    def _run_copy(self):
        if self._files.count() == 0:
            QMessageBox.warning(self, "Add files", "No files selected.")
            return

        base_path = self._gui.base_path
        setup = self._gui.setup_combo.currentText().strip()
        phantom = self._gui._canonical_phantom_position(self._gui.phantom_combo.currentText())
        target_dir = os.path.join(base_path, setup, phantom)
        os.makedirs(target_dir, exist_ok=True)

        copied = 0
        failed = []
        for i in range(self._files.count()):
            src = self._files.item(i).text().strip()
            if not os.path.isfile(src):
                failed.append(src)
                continue
            try:
                shutil.copy2(src, os.path.join(target_dir, os.path.basename(src)))
                copied += 1
            except Exception:
                failed.append(src)

        self._gui._refresh_compare_measured_columns()
        if failed:
            QMessageBox.warning(self, "Add files", f"Copied: {copied}\nFailed: {len(failed)}")
        else:
            QMessageBox.information(self, "Add files", f"Copied {copied} files to:\n{target_dir}")
        self.accept()


class _PostprocessAnalyzeDialog(QDialog):
    PREFERRED = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self._gui = gui
        self.setWindowTitle("Analyze all positions")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Parent folder"))
        self._path_edit = QLineEdit(self._gui.base_path or "")
        path_row.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        setup_row = QHBoxLayout()
        setup_row.addWidget(QLabel("Setup"))
        self._setup_combo = QComboBox()
        setup_row.addWidget(self._setup_combo)
        setup_row.addWidget(QLabel("Position"))
        self._pos_combo = QComboBox()
        setup_row.addWidget(self._pos_combo)
        layout.addLayout(setup_row)

        self._setup_combo.currentIndexChanged.connect(self._refresh_positions)
        self._path_edit.textChanged.connect(self._refresh_setups)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self._run)
        btn_row.addWidget(run_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._refresh_setups()

    def _browse_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select parent folder")
        if folder:
            self._path_edit.setText(folder)

    def _refresh_setups(self):
        self._setup_combo.clear()
        self._setup_combo.addItem("(All subfolders)")

        parent_path = self._path_edit.text().strip()
        if not parent_path or not os.path.isdir(parent_path):
            self._refresh_positions()
            return

        setups = [
            f for f in sorted(os.listdir(parent_path))
            if os.path.isdir(os.path.join(parent_path, f))
        ]
        self._setup_combo.addItems(setups)

        current_setup = self._gui.setup_combo.currentText().strip() if hasattr(self._gui, "setup_combo") else ""
        if current_setup:
            idx = self._setup_combo.findText(current_setup)
            if idx >= 0:
                self._setup_combo.setCurrentIndex(idx)

        self._refresh_positions()

    def _refresh_positions(self):
        self._pos_combo.clear()
        self._pos_combo.addItem("All")

        parent_path = self._path_edit.text().strip()
        setup_name = self._setup_combo.currentText().strip()
        setup_path = ""
        if parent_path and setup_name and setup_name != "(All subfolders)":
            setup_path = os.path.join(parent_path, setup_name)

        if setup_path and os.path.isdir(setup_path):
            existing = [
                f for f in os.listdir(setup_path)
                if os.path.isdir(os.path.join(setup_path, f)) and f != "Experimental_data"
            ]
            ordered = [p for p in self.PREFERRED if p in existing] + [p for p in sorted(existing) if p not in self.PREFERRED]
            self._pos_combo.addItems(ordered)
        else:
            self._pos_combo.addItems(self.PREFERRED)

    def _run(self):
        parent_path = self._path_edit.text().strip()
        if not parent_path or not os.path.isdir(parent_path):
            QMessageBox.warning(self, "Warning", "Select a valid parent folder.")
            return

        selected_setup = self._setup_combo.currentText().strip()
        selected_position = self._pos_combo.currentText().strip() or "All"

        if selected_setup and selected_setup != "(All subfolders)":
            setups = [selected_setup]
        else:
            setups = [
                f for f in sorted(os.listdir(parent_path))
                if os.path.isdir(os.path.join(parent_path, f))
            ]

        if not setups:
            QMessageBox.warning(self, "Warning", "No setup subfolders found in the selected parent folder.")
            return

        self._gui.base_path = parent_path
        self._gui.path_edit.blockSignals(True)
        self._gui.path_edit.setText(parent_path)
        self._gui.path_edit.blockSignals(False)
        self._gui.settings.setValue("last_base_path", parent_path)
        self._gui.update_setup_dropdown()
        if setups:
            self._gui.setup_combo.blockSignals(True)
            self._gui.setup_combo.setCurrentText(setups[0])
            self._gui.setup_combo.blockSignals(False)

        apply_filter = self._gui.filter_checkbox.isChecked()
        try:
            beprefilter_cutoff = float(self._gui.beprefilter_cutoff_combo.currentText().split()[0])
        except Exception:
            beprefilter_cutoff = 0.08
        try:
            beprefilter_order = int(self._gui.beprefilter_order_combo.currentText())
        except Exception:
            beprefilter_order = 4

        self.accept()

        success = 0
        failed = []

        for setup in setups:
            setup_path = os.path.join(parent_path, setup)
            if not os.path.isdir(setup_path):
                failed.append(f"{setup}: setup folder not found")
                continue

            if selected_position == "All":
                positions = [
                    name for name in os.listdir(setup_path)
                    if os.path.isdir(os.path.join(setup_path, name)) and name != "Experimental_data"
                ]
                preferred = [p for p in self.PREFERRED if p in positions]
                positions = preferred + [p for p in sorted(positions) if p not in preferred]
            else:
                positions = [self._gui._canonical_phantom_position(selected_position)]

            if not positions:
                failed.append(f"{setup}: no position folders found")
                continue

            for position in positions:
                position_path = os.path.join(setup_path, position)
                if not os.path.isdir(position_path):
                    failed.append(f"{setup}/{position}: position folder not found")
                    continue
                try:
                    run_measured_analysis(
                        base_path=parent_path,
                        setup=setup,
                        phantom_position=position,
                        gradient_selected="All",
                        nDelay_selected="All",
                        apply_filter=apply_filter,
                        beprefilter_cutoff=beprefilter_cutoff,
                        beprefilter_order=beprefilter_order,
                    )
                    success += 1
                except Exception as e:
                    failed.append(f"{setup}/{position}: {e}")

        self._gui._refresh_compare_measured_columns()

        if failed:
            msg = (
                f"Analysis finished with issues.\n"
                f"Processed positions: {success}\n"
                f"Parent folder: {parent_path}\n\n"
                f"Errors:\n" + "\n".join(failed)
            )
            QMessageBox.warning(self._gui, "Analyze files", msg)
        else:
            QMessageBox.information(
                self._gui,
                "Analyze files",
                f"Analysis complete. Processed positions: {success}\nParent folder:\n{parent_path}",
            )


class _ChangePlotParametersDialog(QDialog):
    """Dialog to customize plot parameters used by Plot actions."""

    def __init__(self, initial_values=None, parent=None):
        super().__init__(parent)
        initial = dict(initial_values or {})
        self.setWindowTitle("Change Plot Parameters")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        size_group = QGroupBox("Sizes")
        size_layout = QVBoxLayout(size_group)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font size:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(1, 72)
        self.font_size_spin.setValue(int(initial.get("font_size", 12)))
        font_row.addWidget(self.font_size_spin)
        font_row.addStretch()
        size_layout.addLayout(font_row)

        marker_row = QHBoxLayout()
        marker_row.addWidget(QLabel("Marker size (plot points):"))
        self.marker_size_spin = QDoubleSpinBox()
        self.marker_size_spin.setDecimals(1)
        self.marker_size_spin.setRange(0.5, 25.0)
        self.marker_size_spin.setSingleStep(0.5)
        self.marker_size_spin.setValue(float(initial.get("marker_size", 5.0)))
        marker_row.addWidget(self.marker_size_spin)
        marker_row.addStretch()
        size_layout.addLayout(marker_row)

        line_row = QHBoxLayout()
        line_row.addWidget(QLabel("Line Width:"))
        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setDecimals(1)
        self.line_width_spin.setRange(0.1, 20.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setValue(float(initial.get("line_width", 1.5)))
        line_row.addWidget(self.line_width_spin)
        line_row.addStretch()
        size_layout.addLayout(line_row)

        layout.addWidget(size_group)

        xy_group = QGroupBox("xytext (annotation offset in points)")
        xy_layout = QVBoxLayout(xy_group)

        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X:"))
        self.xytext_x_spin = QDoubleSpinBox()
        self.xytext_x_spin.setDecimals(1)
        self.xytext_x_spin.setRange(-100.0, 100.0)
        self.xytext_x_spin.setSingleStep(1.0)
        self.xytext_x_spin.setValue(float(initial.get("xytext_x", 20.0)))
        x_row.addWidget(self.xytext_x_spin)
        x_row.addStretch()
        xy_layout.addLayout(x_row)

        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y:"))
        self.xytext_y_spin = QDoubleSpinBox()
        self.xytext_y_spin.setDecimals(1)
        self.xytext_y_spin.setRange(-100.0, 100.0)
        self.xytext_y_spin.setSingleStep(1.0)
        self.xytext_y_spin.setValue(float(initial.get("xytext_y", 12.0)))
        y_row.addWidget(self.xytext_y_spin)
        y_row.addStretch()
        xy_layout.addLayout(y_row)

        layout.addWidget(xy_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def values(self):
        return {
            "font_size": int(self.font_size_spin.value()),
            "xytext_x": float(self.xytext_x_spin.value()),
            "xytext_y": float(self.xytext_y_spin.value()),
            "marker_size": float(self.marker_size_spin.value()),
            "line_width": float(self.line_width_spin.value()),
        }


class ZoomLabel(QLabel):
    """QLabel with wheel zoom, rectangle zoom and resettable viewport."""
    def __init__(self, parent=None, gui_ref=None):
        super().__init__(parent)
        self._gui_ref = gui_ref
        self._orig_pixmap = None
        self._view_rect = QRect()
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self._selection_origin = None
        self._pan_origin = None
        self._pan_start_rect = QRect()
        self._pan_enabled = False
        self._display_scale = 1.0
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def set_pan_enabled(self, enabled):
        self._pan_enabled = bool(enabled)
        if not self._pan_enabled:
            self._pan_origin = None
            self._pan_start_rect = QRect()
            self.unsetCursor()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls()]
            if any(os.path.isfile(p) and p.lower().endswith('.mat') for p in paths):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if self._gui_ref is not None and hasattr(self._gui_ref, 'compare_drop_event'):
            self._gui_ref.compare_drop_event(event)
        else:
            event.ignore()

    def setPixmap(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        if pixmap and not pixmap.isNull():
            self._view_rect = QRect(0, 0, pixmap.width(), pixmap.height())
            self._display_scale = 1.0
        else:
            self._view_rect = QRect()
            self._display_scale = 1.0
        self._rubber_band.hide()
        self._update_scaled()

    def reset_zoom(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return
        self._view_rect = QRect(0, 0, self._orig_pixmap.width(), self._orig_pixmap.height())
        self._display_scale = 1.0
        self._rubber_band.hide()
        self._update_scaled()

    def _is_full_view(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            return False
        return (
            self._view_rect.x() == 0
            and self._view_rect.y() == 0
            and self._view_rect.width() == self._orig_pixmap.width()
            and self._view_rect.height() == self._orig_pixmap.height()
        )

    def wheelEvent(self, event):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        # Allow zooming out from the initial full-view fit-to-width state.
        if delta < 0 and self._is_full_view():
            self._display_scale = max(0.05, self._display_scale / 1.15)
            self._update_scaled()
            return

        if delta > 0 and self._display_scale < 1.0 and self._is_full_view():
            self._display_scale = min(1.0, self._display_scale * 1.15)
            self._update_scaled()
            return

        zoom_factor = 1 / 1.15 if delta > 0 else 1.15
        focus_x, focus_y = self._map_label_point_to_image(event.pos())
        self._zoom_around_point(focus_x, focus_y, zoom_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._pan_enabled:
                if not self._point_in_displayed_pixmap(event.pos()):
                    return
                self._pan_origin = event.pos()
                self._pan_start_rect = QRect(self._view_rect)
                self.setCursor(Qt.ClosedHandCursor)
                return
            if not self._point_in_displayed_pixmap(event.pos()):
                return
            self._selection_origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._selection_origin, self._selection_origin))
            self._rubber_band.show()
        elif event.button() == Qt.RightButton:
            if not self._point_in_displayed_pixmap(event.pos()):
                return
            self._pan_origin = event.pos()
            self._pan_start_rect = QRect(self._view_rect)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._selection_origin is not None:
            rect = QRect(self._selection_origin, event.pos()).normalized()
            self._rubber_band.setGeometry(rect)
        elif self._pan_origin is not None and not self._pan_start_rect.isNull():
            display_rect = self._display_rect_for_view()
            if display_rect.width() <= 0 or display_rect.height() <= 0:
                return

            dx_label = event.x() - self._pan_origin.x()
            dy_label = event.y() - self._pan_origin.y()
            dx_img = dx_label * self._pan_start_rect.width() / display_rect.width()
            dy_img = dy_label * self._pan_start_rect.height() / display_rect.height()

            new_rect = QRect(
                int(round(self._pan_start_rect.x() - dx_img)),
                int(round(self._pan_start_rect.y() - dy_img)),
                self._pan_start_rect.width(),
                self._pan_start_rect.height()
            )
            self._view_rect = self._clamped_rect(new_rect)
            self._update_scaled()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pan_enabled and self._pan_origin is not None:
            self._pan_origin = None
            self._pan_start_rect = QRect()
            self.unsetCursor()
            return

        if event.button() == Qt.LeftButton and self._selection_origin is not None:
            selection_rect = self._rubber_band.geometry().normalized()
            self._rubber_band.hide()
            self._selection_origin = None

            if selection_rect.width() < 12 or selection_rect.height() < 12:
                return

            self._zoom_to_selection(selection_rect)
        elif event.button() == Qt.RightButton and self._pan_origin is not None:
            self._pan_origin = None
            self._pan_start_rect = QRect()
            self.unsetCursor()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _display_rect_for_view(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            return QRect()
        pix = self.pixmap()
        if pix is not None and not pix.isNull():
            return QRect(0, 0, pix.width(), pix.height())
        return QRect(0, 0, max(1, self.width()), max(1, self.height()))

    def _point_in_displayed_pixmap(self, pos):
        return self._display_rect_for_view().contains(pos)

    def _map_label_point_to_image(self, pos):
        display_rect = self._display_rect_for_view()
        if display_rect.isNull():
            return 0.0, 0.0

        rel_x = (pos.x() - display_rect.left()) / max(1, display_rect.width())
        rel_y = (pos.y() - display_rect.top()) / max(1, display_rect.height())
        rel_x = min(max(rel_x, 0.0), 1.0)
        rel_y = min(max(rel_y, 0.0), 1.0)

        img_x = self._view_rect.x() + rel_x * self._view_rect.width()
        img_y = self._view_rect.y() + rel_y * self._view_rect.height()
        return img_x, img_y

    def _zoom_around_point(self, focus_x, focus_y, zoom_factor):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            return

        cur = self._view_rect
        new_w = max(20, int(round(cur.width() * zoom_factor)))
        new_h = max(20, int(round(cur.height() * zoom_factor)))
        new_w = min(new_w, self._orig_pixmap.width())
        new_h = min(new_h, self._orig_pixmap.height())

        rel_x = 0.5 if cur.width() == 0 else (focus_x - cur.x()) / cur.width()
        rel_y = 0.5 if cur.height() == 0 else (focus_y - cur.y()) / cur.height()

        new_x = int(round(focus_x - rel_x * new_w))
        new_y = int(round(focus_y - rel_y * new_h))
        self._view_rect = self._clamped_rect(QRect(new_x, new_y, new_w, new_h))
        self._update_scaled()

    def _zoom_to_selection(self, selection_rect):
        display_rect = self._display_rect_for_view()
        if display_rect.isNull() or self._view_rect.isNull():
            return

        clipped = selection_rect.intersected(display_rect)
        if clipped.width() < 5 or clipped.height() < 5:
            return

        scale_x = self._view_rect.width() / max(1, display_rect.width())
        scale_y = self._view_rect.height() / max(1, display_rect.height())
        new_x = self._view_rect.x() + int(round((clipped.left() - display_rect.left()) * scale_x))
        new_y = self._view_rect.y() + int(round((clipped.top() - display_rect.top()) * scale_y))
        new_w = max(20, int(round(clipped.width() * scale_x)))
        new_h = max(20, int(round(clipped.height() * scale_y)))

        # Keep viewport aspect ratio fixed so zoom never deforms plot geometry.
        target_aspect = self._view_rect.width() / max(1, self._view_rect.height())
        if new_h > 0:
            cur_aspect = new_w / new_h
            if cur_aspect > target_aspect:
                new_w = max(20, int(round(new_h * target_aspect)))
            else:
                new_h = max(20, int(round(new_w / max(1e-9, target_aspect))))

        self._display_scale = 1.0
        self._view_rect = self._clamped_rect(QRect(new_x, new_y, new_w, new_h))
        self._update_scaled()

    def _clamped_rect(self, rect):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return QRect()

        img_w = self._orig_pixmap.width()
        img_h = self._orig_pixmap.height()
        w = min(max(20, rect.width()), img_w)
        h = min(max(20, rect.height()), img_h)
        x = min(max(0, rect.x()), max(0, img_w - w))
        y = min(max(0, rect.y()), max(0, img_h - h))
        return QRect(x, y, w, h)

    def _update_scaled(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            super().clear()
            return

        cropped = self._orig_pixmap.copy(self._clamped_rect(self._view_rect))
        parent_w = self.parentWidget().width() if self.parentWidget() is not None else cropped.width()
        target_w = max(1, int(parent_w))
        scaled_w = max(1, int(round(target_w * self._display_scale)))
        scaled = cropped.scaledToWidth(scaled_w, Qt.SmoothTransformation)
        super().setPixmap(scaled)
        self.setFixedSize(scaled.size())


class _SimulationOffsetSelectionDialog(QDialog):
    def __init__(self, offset_keys, selected_offsets=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select simulation offsets")
        self.resize(360, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select one or more simulation offsets:"))

        self.offset_list = QListWidget()
        self.offset_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for key in offset_keys:
            item = QListWidgetItem(str(key))
            self.offset_list.addItem(item)
            if key in set(selected_offsets or []):
                item.setSelected(True)
        layout.addWidget(self.offset_list)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def selected_offsets(self):
        return [item.text().strip() for item in self.offset_list.selectedItems() if item.text().strip()]


# =========================================================
# MAIN GUI
# =========================================================

class EddyCurrentGUI(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("MRI Eddy Current Analysis")
        self.resize(1000, 500)

        self.base_path = None
        self.base_path2 = None
        self.add_case_enabled = False
        self.comparison_save_dir = None
        self.additional_cases = []
        self._global_sync_in_progress = False
        self._plot_phantom_sync_in_progress = False
        # track files and labels for plot comparison
        self.compare_items = []  # list of (path, label) tuples
        # track current analysis figure for saving
        self.current_analysis_figure = None
        self.current_analysis_filename = None
        self.current_analysis_image_path = None
        self.current_analysis_table_frames = None
        self.current_analysis_table_filename = None
        self.current_analysis_table_dialog = None
        self._time_domain_sim_loader = TimeDomainSimulationLoader()
        self._cylinder_sim_loader = CylinderTimeDomainLoader()
        self._time_domain_sim_overlay_enabled = False
        self._time_domain_sim_offset_mode = "none"
        self._time_domain_sim_selected_offsets = []
        self._time_domain_simulation_warning_buffer = []
        # Sim overlay session – single source of truth for what is plotted.
        # Plot resets it; Add appends to it; Clear empties it.
        self._sim_overlay_session_cases = []       # list of spec dicts
        self._sim_overlay_session_colormap = None  # chosen once at first Plot
        self._sim_overlay_spec_color_map = {}      # spec-key -> RGBA color
        self._sim_overlay_color_index = 0
        # Plot session color counter for measured-data colormaps
        self._plot_session_color_index = 0
        # Colormap chosen for the current multi-case measured-data session.
        # None means "no session yet → ask on next Plot".
        self._multi_case_colormap = None

        # create layouts first; widgets will follow
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # ======================================================
        # =============== POSTPROCESS FILES ====================
        # ======================================================
        postprocess_group = QGroupBox("Postprocess files")
        postprocess_group.setStyleSheet(
            "QGroupBox { border: 2px solid #4C8C4A; border-radius: 6px; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }"
        )
        postprocess_layout = QHBoxLayout(postprocess_group)
        btn_add_files = QPushButton("Add new files")
        btn_add_files.clicked.connect(self.open_add_new_files_flow)
        postprocess_layout.addWidget(btn_add_files)
        btn_analyze_files = QPushButton("Analyze all positions")
        btn_analyze_files.clicked.connect(self.open_analyze_files_flow)
        postprocess_layout.addWidget(btn_analyze_files)
        postprocess_layout.addStretch()
        main_layout.addWidget(postprocess_group)

        # ======================================================
        # ================== SELECT FILES ======================
        # ======================================================

        select_group = QGroupBox()
        select_group.setStyleSheet(
            "QGroupBox { border: 2px solid #2A7DAA; border-radius: 6px; margin-top: 8px; }"
        )
        select_group_layout = QVBoxLayout(select_group)
        main_layout.addWidget(select_group)

        select_label = QLabel("SELECT FILES")
        select_label.setStyleSheet("font-weight: bold; color: red;")
        select_group_layout.addWidget(select_label)

        config_row = QHBoxLayout()
        select_group_layout.addLayout(config_row)

        config_row.addWidget(QLabel("Path"))

        self.path_edit = QLineEdit()
        self.path_edit.setMinimumWidth(300)
        config_row.addWidget(self.path_edit)

        # load last base path suggestion once the path_edit exists
        self.settings = QSettings("EddyCurrents", "EddyGUI")
        last = self.settings.value("last_base_path", "")
        if last:
            self.base_path = last
            self.path_edit.setText(last)
            # dropdown will be filled after the combo is created

        browse_path_btn = QPushButton("Browse")
        browse_path_btn.clicked.connect(self.select_base_path)
        config_row.addWidget(browse_path_btn)

        config_row.addSpacing(20)

        config_row.addWidget(QLabel("Setup"))

        self.setup_combo = QComboBox()
        self.setup_combo.setMinimumWidth(150)
        self.setup_combo.currentIndexChanged.connect(self.update_phantom_dropdown)
        self.setup_combo.currentIndexChanged.connect(lambda _=0: self.refresh_global_comparison_controls())
        self.setup_combo.currentIndexChanged.connect(lambda _=0: self._refresh_cylinder_hr_dropdowns())
        self.setup_combo.currentIndexChanged.connect(lambda _=0: self._refresh_time_domain_materials())
        config_row.addWidget(self.setup_combo)
        # now that combo exists we can populate it with the last path
        if self.base_path:
            self.update_setup_dropdown()
            self.update_phantom_dropdown()

        add_setup_btn = QPushButton("Add")
        add_setup_btn.clicked.connect(self.add_new_setup)
        config_row.addWidget(add_setup_btn)

        config_row.addSpacing(20)

        config_row.addWidget(QLabel("Phantom position"))

        self.phantom_combo = QComboBox()
        self.phantom_combo.addItems(
            ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        )
        self.phantom_combo.currentIndexChanged.connect(lambda _=0: self.refresh_plot_phantom_dropdown())
        config_row.addWidget(self.phantom_combo)

        config_row.addSpacing(16)
        config_row.addWidget(QLabel("Legend"))
        self.case1_legend_input = QLineEdit()
        self.case1_legend_input.setPlaceholderText("Custom label")
        self.case1_legend_input.setMaximumWidth(140)
        config_row.addWidget(self.case1_legend_input)

        self.add_case_btn = QPushButton("Add case")
        self.add_case_btn.clicked.connect(self.add_case)
        config_row.addWidget(self.add_case_btn)

        config_row.addStretch()

        select_compare_row = QHBoxLayout()
        select_group_layout.addLayout(select_compare_row)

        self.add_cases_container = QVBoxLayout()
        select_compare_row.addLayout(self.add_cases_container, 1)

        self.global_compare_group = QGroupBox("Global comparison")
        self.global_compare_group.setVisible(False)
        global_layout = QVBoxLayout(self.global_compare_group)

        global_path_row = QHBoxLayout()
        global_path_row.addWidget(QLabel("Path_global"))
        self.global_path_edit = QLineEdit()
        self.global_path_edit.setMinimumWidth(260)
        self.global_path_edit.setPlaceholderText("Global base path")
        global_path_row.addWidget(self.global_path_edit)
        global_layout.addLayout(global_path_row)

        global_setup_row = QHBoxLayout()
        global_setup_row.addWidget(QLabel("Setup_global"))
        self.global_setup_combo = QComboBox()
        self.global_setup_combo.setMinimumWidth(220)
        global_setup_row.addWidget(self.global_setup_combo)
        global_layout.addLayout(global_setup_row)

        global_phantom_row = QHBoxLayout()
        global_phantom_row.addWidget(QLabel("Phantom position global"))
        self.global_phantom_combo = QComboBox()
        self.global_phantom_combo.setMinimumWidth(220)
        global_phantom_row.addWidget(self.global_phantom_combo)
        global_layout.addLayout(global_phantom_row)

        global_layout.addStretch()
        select_compare_row.addWidget(self.global_compare_group)

        self.global_path_edit.editingFinished.connect(self.apply_global_path)
        self.global_setup_combo.currentIndexChanged.connect(self.apply_global_setup)
        self.global_phantom_combo.currentIndexChanged.connect(self.apply_global_phantom)

        self.path_edit.textChanged.connect(lambda _=None: self.refresh_global_comparison_controls())

        self.case2_row = QHBoxLayout()
        self.add_cases_container.addLayout(self.case2_row)
        self.case2_widgets = []

        lbl_path2 = QLabel("Path2")
        self.case2_row.addWidget(lbl_path2)
        self.case2_widgets.append(lbl_path2)

        self.path2_edit = QLineEdit()
        self.path2_edit.setMinimumWidth(300)
        self.case2_row.addWidget(self.path2_edit)
        self.case2_widgets.append(self.path2_edit)

        browse_path2_btn = QPushButton("Browse")
        browse_path2_btn.clicked.connect(self.select_base_path2)
        self.case2_row.addWidget(browse_path2_btn)
        self.case2_widgets.append(browse_path2_btn)

        self.case2_row.addSpacing(20)

        lbl_setup2 = QLabel("Setup2")
        self.case2_row.addWidget(lbl_setup2)
        self.case2_widgets.append(lbl_setup2)

        self.setup2_combo = QComboBox()
        self.setup2_combo.setMinimumWidth(150)
        self.setup2_combo.currentIndexChanged.connect(self.update_phantom_dropdown_case2)
        self.setup2_combo.currentIndexChanged.connect(lambda _=0: self.refresh_global_comparison_controls())
        self.case2_row.addWidget(self.setup2_combo)
        self.case2_widgets.append(self.setup2_combo)

        self.case2_row.addSpacing(20)

        lbl_phantom2 = QLabel("Phantom position2")
        self.case2_row.addWidget(lbl_phantom2)
        self.case2_widgets.append(lbl_phantom2)

        self.phantom2_combo = QComboBox()
        self.phantom2_combo.currentIndexChanged.connect(lambda _=0: self.refresh_plot_phantom_dropdown())
        self.case2_row.addWidget(self.phantom2_combo)
        self.case2_widgets.append(self.phantom2_combo)

        delete_case2_btn = QPushButton("Delete")
        self.case2_row.addWidget(delete_case2_btn)
        self.case2_widgets.append(delete_case2_btn)

        self.case2_row.addSpacing(20)
        
        lbl_legend2 = QLabel("Legend:")
        self.case2_row.addWidget(lbl_legend2)
        self.case2_widgets.append(lbl_legend2)
        
        self.case2_legend_input = QLineEdit()
        self.case2_legend_input.setPlaceholderText("Custom label")
        self.case2_legend_input.setMaximumWidth(120)
        self.case2_row.addWidget(self.case2_legend_input)
        self.case2_widgets.append(self.case2_legend_input)

        self.case2_row.addStretch()

        for widget in self.case2_widgets:
            widget.setVisible(False)

        self.additional_cases.append({
            'index': 2,
            'base_path': None,
            'row': self.case2_row,
            'path_edit': self.path2_edit,
            'setup_combo': self.setup2_combo,
            'phantom_combo': self.phantom2_combo,
            'legend_input': self.case2_legend_input,
            'delete_btn': delete_case2_btn,
            'widgets': self.case2_widgets,
            'visible': False
        })

        delete_case2_btn.clicked.connect(lambda _=False: self.delete_case(2))
        self.path2_edit.textChanged.connect(lambda _=None: self.refresh_global_comparison_controls())

        # file_list kept as hidden widget so existing backend methods work
        self.file_list = FileList()
        self.file_list.hide()

        # ======================================================
        # ================== ANALYZE DATA ======================
        # ======================================================

        analyze_group = QGroupBox()
        analyze_group.setStyleSheet(
            "QGroupBox { border: 2px solid #B07A28; border-radius: 6px; margin-top: 8px; }"
        )
        analyze_group_layout = QVBoxLayout(analyze_group)
        main_layout.addWidget(analyze_group)

        analyze_label = QLabel("PLOT DATA")
        analyze_label.setStyleSheet("font-weight: bold; color: red;")
        analyze_group_layout.addWidget(analyze_label)

        time_domain_label = QLabel("Time-domain analysis")
        time_domain_label.setStyleSheet("font-weight: bold; color: #444;")
        analyze_group_layout.addWidget(time_domain_label)

        analyze_row = QHBoxLayout()
        analyze_group_layout.addLayout(analyze_row)

        analyze_row.addWidget(QLabel("Plot"))

        self.plot_combo = QComboBox()
        self.plot_combo.addItems(["Beddy", "FID", "Phase"])
        self.plot_combo.currentIndexChanged.connect(self.update_gradient_options)
        analyze_row.addWidget(self.plot_combo)

        analyze_row.addSpacing(20)

        analyze_row.addWidget(QLabel("Gradient"))

        self.gradient_combo = QComboBox()
        self.gradient_combo.addItems(["GX", "GY", "GZ", "All"])
        analyze_row.addWidget(self.gradient_combo)

        analyze_row.addSpacing(12)
        analyze_row.addWidget(QLabel("Phantom position"))
        self.plot_phantom_combo = QComboBox()
        self.plot_phantom_combo.setMinimumWidth(120)
        self.plot_phantom_combo.currentIndexChanged.connect(self.apply_plot_phantom_selection)
        analyze_row.addWidget(self.plot_phantom_combo)

        analyze_row.addSpacing(20)

        analyze_row.addWidget(QLabel("nDelay"))

        self.ndelay_combo = QComboBox()
        self.ndelay_combo.addItems(["All"] + [str(i) for i in range(10)])
        analyze_row.addWidget(self.ndelay_combo)

        analyze_row.addSpacing(20)

        self.filter_checkbox = QCheckBox("Filter")
        analyze_row.addWidget(self.filter_checkbox)

        self.exp_fit_checkbox = QCheckBox("Exponential fit")
        analyze_row.addWidget(self.exp_fit_checkbox)

        analyze_row.addSpacing(12)
        analyze_row.addWidget(QLabel("BePrefilter cutoff (Wn)"))
        self.beprefilter_cutoff_combo = QComboBox()
        self.beprefilter_cutoff_combo.addItems([
            "0.12 (menos agresivo)",
            "0.10 (agresivo)",
            "0.08 (muy agresivo)",
            "0.06 (extra agresivo)",
            "0.04 (extremo)"
        ])
        self.beprefilter_cutoff_combo.setCurrentText("0.08 (muy agresivo)")
        analyze_row.addWidget(self.beprefilter_cutoff_combo)

        analyze_row.addSpacing(10)
        analyze_row.addWidget(QLabel("Order"))
        self.beprefilter_order_combo = QComboBox()
        self.beprefilter_order_combo.addItems(["1", "2", "4", "8"])
        self.beprefilter_order_combo.setCurrentText("4")
        analyze_row.addWidget(self.beprefilter_order_combo)

        analyze_row.addSpacing(20)
        self.analyze_change_legend_checkbox = QCheckBox("Change legend")
        analyze_row.addWidget(self.analyze_change_legend_checkbox)

        analyze_row.addSpacing(12)
        self.analyze_change_dimensions_checkbox = QCheckBox("Change dimensions")
        analyze_row.addWidget(self.analyze_change_dimensions_checkbox)

        analyze_row.addSpacing(12)
        self.analyze_change_font_checkbox = QCheckBox("Change plot parameters")
        analyze_row.addWidget(self.analyze_change_font_checkbox)

        analyze_row.addStretch()

        analyze_btn = QPushButton("Plot")
        analyze_btn.clicked.connect(self.run_analysis)
        analyze_row.addWidget(analyze_btn)

        save_plot_btn = QPushButton("Save plot")
        save_plot_btn.clicked.connect(self.save_current_analysis_plot)
        analyze_row.addWidget(save_plot_btn)

        extract_metrics_btn = QPushButton("Extract filter metrics")
        extract_metrics_btn.clicked.connect(self.extract_filter_metrics)
        analyze_row.addWidget(extract_metrics_btn)

        reset_zoom_btn = QPushButton("Reset Zoom")
        reset_zoom_btn.clicked.connect(self.reset_zoom)
        analyze_row.addWidget(reset_zoom_btn)

        self.pan_mode_checkbox = QCheckBox("Pan")
        self.pan_mode_checkbox.setToolTip("Drag with left mouse button to move the zoomed view")
        self.pan_mode_checkbox.toggled.connect(self._set_plot_pan_mode)
        analyze_row.addWidget(self.pan_mode_checkbox)

        limits_row = QHBoxLayout()
        analyze_group_layout.addLayout(limits_row)

        limits_row.addWidget(QLabel("XLim"))
        self.plot_xlim_min_spin = QDoubleSpinBox()
        self.plot_xlim_min_spin.setDecimals(4)
        self.plot_xlim_min_spin.setSingleStep(0.1)
        self.plot_xlim_min_spin.setEnabled(False)
        limits_row.addWidget(self.plot_xlim_min_spin)

        self.plot_xlim_max_spin = QDoubleSpinBox()
        self.plot_xlim_max_spin.setDecimals(4)
        self.plot_xlim_max_spin.setSingleStep(0.1)
        self.plot_xlim_max_spin.setEnabled(False)
        limits_row.addWidget(self.plot_xlim_max_spin)

        limits_row.addSpacing(12)
        limits_row.addWidget(QLabel("YLim"))
        self.plot_ylim_min_spin = QDoubleSpinBox()
        self.plot_ylim_min_spin.setDecimals(4)
        self.plot_ylim_min_spin.setSingleStep(0.1)
        self.plot_ylim_min_spin.setEnabled(False)
        limits_row.addWidget(self.plot_ylim_min_spin)

        self.plot_ylim_max_spin = QDoubleSpinBox()
        self.plot_ylim_max_spin.setDecimals(4)
        self.plot_ylim_max_spin.setSingleStep(0.1)
        self.plot_ylim_max_spin.setEnabled(False)
        limits_row.addWidget(self.plot_ylim_max_spin)

        self.plot_auto_limits_btn = QPushButton("Auto limits")
        self.plot_auto_limits_btn.setEnabled(False)
        self.plot_auto_limits_btn.clicked.connect(self._reset_plot_limits_auto)
        limits_row.addWidget(self.plot_auto_limits_btn)
        limits_row.addStretch()

        self.plot_canvas_container = QWidget()
        self.plot_canvas_layout = QVBoxLayout(self.plot_canvas_container)
        self.plot_canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_canvas_layout.setSpacing(4)
        self.plot_canvas_container.setVisible(False)
        analyze_group_layout.addWidget(self.plot_canvas_container)

        self.analysis_canvas = None
        self.analysis_toolbar = None
        self._analysis_draw_cid = None
        self._updating_plot_limits = False
        self.plot_xlim_min_spin.valueChanged.connect(self._on_plot_limits_changed)
        self.plot_xlim_max_spin.valueChanged.connect(self._on_plot_limits_changed)
        self.plot_ylim_min_spin.valueChanged.connect(self._on_plot_limits_changed)
        self.plot_ylim_max_spin.valueChanged.connect(self._on_plot_limits_changed)

        sim_compare_row = QHBoxLayout()
        analyze_group_layout.addLayout(sim_compare_row)

        self.time_domain_sim_compare_checkbox = QCheckBox("Compare with time-domain simulations")
        self.time_domain_sim_compare_checkbox.setChecked(False)
        self.time_domain_sim_compare_checkbox.toggled.connect(self.update_time_domain_sim_controls)
        sim_compare_row.addWidget(self.time_domain_sim_compare_checkbox)

        sim_compare_row.addSpacing(12)
        sim_compare_row.addWidget(QLabel("Material:"))
        self.sim_materials_list = QListWidget()
        self.sim_materials_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sim_materials_list.setMinimumWidth(130)
        self.sim_materials_list.setMaximumHeight(64)
        self.sim_materials_list.itemSelectionChanged.connect(self._on_sim_material_selection_changed)
        sim_compare_row.addWidget(self.sim_materials_list)

        # Phantom Type selector (Point / Cylinder)
        sim_compare_row.addSpacing(12)
        sim_compare_row.addWidget(QLabel("Phantom Type:"))
        self.sim_phantom_type_combo = QComboBox()
        self.sim_phantom_type_combo.addItems(["Point", "Cylinder"])
        self.sim_phantom_type_combo.setCurrentText("Point")
        self.sim_phantom_type_combo.currentTextChanged.connect(self._on_sim_phantom_type_changed)
        sim_compare_row.addWidget(self.sim_phantom_type_combo)

        # H / R dropdowns – only visible in Cylinder mode
        sim_compare_row.addSpacing(8)
        self.sim_h_label = QLabel("H (mm):")
        sim_compare_row.addWidget(self.sim_h_label)
        self.sim_h_combo = QComboBox()
        self.sim_h_combo.setMinimumWidth(60)
        sim_compare_row.addWidget(self.sim_h_combo)

        sim_compare_row.addSpacing(6)
        self.sim_r_label = QLabel("R (mm):")
        sim_compare_row.addWidget(self.sim_r_label)
        self.sim_r_combo = QComboBox()
        self.sim_r_combo.setMinimumWidth(60)
        sim_compare_row.addWidget(self.sim_r_combo)

        self.time_domain_sim_offsets_btn = QPushButton("Simulation offsets...")
        self.time_domain_sim_offsets_btn.clicked.connect(self.configure_time_domain_simulation_offsets)
        sim_compare_row.addWidget(self.time_domain_sim_offsets_btn)

        self.time_domain_sim_offsets_status = QLabel("No offsets")
        self.time_domain_sim_offsets_status.setStyleSheet("color: #666;")
        sim_compare_row.addWidget(self.time_domain_sim_offsets_status)

        sim_compare_row.addSpacing(12)
        self.add_sim_case_btn = QPushButton("Add")
        self.add_sim_case_btn.setToolTip("Add another simulation case to the overlay list")
        self.add_sim_case_btn.clicked.connect(self._add_sim_overlay_case)
        sim_compare_row.addWidget(self.add_sim_case_btn)

        self.clear_sim_cases_btn = QPushButton("Clear")
        self.clear_sim_cases_btn.setToolTip("Remove all accumulated simulation overlays")
        self.clear_sim_cases_btn.clicked.connect(self._clear_sim_overlay_cases)
        sim_compare_row.addWidget(self.clear_sim_cases_btn)

        self.sim_cases_status = QLabel("")
        self.sim_cases_status.setStyleSheet("color: #555; font-style: italic;")
        sim_compare_row.addWidget(self.sim_cases_status)

        sim_compare_row.addStretch()

        # Hide cylinder-only controls initially
        for w in (self.sim_h_label, self.sim_h_combo, self.sim_r_label, self.sim_r_combo):
            w.setVisible(False)

        compare_label = QLabel("Single-value analysis")
        compare_label.setStyleSheet("font-weight: bold; color: blue;")
        analyze_group_layout.addWidget(compare_label)

        compare_row = QHBoxLayout()
        analyze_group_layout.addLayout(compare_row)

        compare_row.addWidget(QLabel("Gradient"))
        self.compare_grad_combo = QComboBox()
        self.compare_grad_combo.addItems(["X", "Y", "Z"])
        compare_row.addWidget(self.compare_grad_combo)

        compare_row.addSpacing(20)

        compare_row.addWidget(QLabel("Metrics"))
        self.compare_meas_combo = QComboBox()
        self.compare_meas_combo.addItems([
            "B_measured_at_t0_FirstPoint",
            "B_measured_at_t0_Fitted",
            "B_measured_at_t0_PreFiltered",
            "B_integrated",
            "Exp_fit",
        ])
        compare_row.addWidget(self.compare_meas_combo)

        compare_row.addSpacing(20)
        self.compare_with_sim_checkbox = QCheckBox("Compare with simulation")
        self.compare_with_sim_checkbox.setChecked(True)
        compare_row.addWidget(self.compare_with_sim_checkbox)

        compare_row.addSpacing(20)

        compare_row.addWidget(QLabel("Plot type"))
        self.compare_plot_combo = QComboBox()
        self.compare_plot_combo.addItems(["Points", "Histograms"])
        compare_row.addWidget(self.compare_plot_combo)

        compare_row.addSpacing(20)
        self.compare_sim_hist_label = QLabel("Sim histogram")
        compare_row.addWidget(self.compare_sim_hist_label)
        self.compare_sim_hist_mode_combo = QComboBox()
        self.compare_sim_hist_mode_combo.addItems([
            "Beddy_average_FOV (uT)",
            "Point-by-point average",
        ])
        compare_row.addWidget(self.compare_sim_hist_mode_combo)

        compare_row.addSpacing(20)
        self.change_legend_checkbox = QCheckBox("Change legend")
        compare_row.addWidget(self.change_legend_checkbox)

        compare_row.addSpacing(12)
        self.change_dimensions_checkbox = QCheckBox("Change dimensions")
        compare_row.addWidget(self.change_dimensions_checkbox)

        self.compare_grad_combo.addItems(["X", "Y", "Z", "All"])
        self.change_font_checkbox = QCheckBox("Change plot parameters")
        compare_row.addWidget(self.change_font_checkbox)

        compare_row.addSpacing(12)
        self.xlim_50mm_checkbox = QCheckBox("xlim 50mm")
        compare_row.addWidget(self.xlim_50mm_checkbox)

        compare_row.addSpacing(12)
        self.normalize_hist_checkbox = QCheckBox("Normalize")
        compare_row.addWidget(self.normalize_hist_checkbox)

        compare_row.addStretch()

        compare_btn = QPushButton("Plot")
        compare_btn.clicked.connect(self.run_comparison)
        compare_row.addWidget(compare_btn)

        extract_single_value_btn = QPushButton("Extract single-value metrics")
        extract_single_value_btn.clicked.connect(self.extract_single_value_metrics)
        compare_row.addWidget(extract_single_value_btn)

        self.compare_with_sim_checkbox.toggled.connect(self.update_single_value_sim_controls)
        self.update_single_value_sim_controls()
        self.update_time_domain_sim_controls()
        self._refresh_time_domain_materials()

        # Keep measured-column options in sync with the selected measured table.
        self.setup_combo.currentIndexChanged.connect(self._refresh_compare_measured_columns)
        self.setup_combo.currentIndexChanged.connect(lambda _=0: self.refresh_plot_phantom_dropdown())
        self.phantom_combo.currentIndexChanged.connect(lambda _=0: self.refresh_plot_phantom_dropdown())
        self._refresh_compare_measured_columns()

        plot_sim_group = QGroupBox()
        plot_sim_group.setStyleSheet(
            "QGroupBox { border: 2px solid #3F6E9A; border-radius: 6px; margin-top: 8px; }"
        )
        plot_sim_group_layout = QVBoxLayout(plot_sim_group)
        main_layout.addWidget(plot_sim_group)

        plot_sim_label = QLabel("PLOT SIMULATIONS")
        plot_sim_label.setStyleSheet("font-weight: bold; color: blue;")
        plot_sim_group_layout.addWidget(plot_sim_label)

        plot_sim_row = QHBoxLayout()
        plot_sim_group_layout.addLayout(plot_sim_row)

        plot_sim_row.addWidget(QLabel("Simulation case"))
        self.sim_case_combo = QComboBox()
        self.sim_case_combo.setMinimumWidth(200)
        plot_sim_row.addWidget(self.sim_case_combo)

        refresh_sim_cases_btn = QPushButton("Refresh")
        refresh_sim_cases_btn.clicked.connect(self.refresh_simulation_cases)
        plot_sim_row.addWidget(refresh_sim_cases_btn)

        plot_sim_row.addSpacing(20)

        plot_sim_row.addWidget(QLabel("Plot Type"))
        self.sim_plot_type_combo = QComboBox()
        self.sim_plot_type_combo.addItems(["B0", "Beddy"])
        plot_sim_row.addWidget(self.sim_plot_type_combo)

        plot_sim_row.addSpacing(20)

        plot_sim_row.addWidget(QLabel("Gradient"))
        self.sim_gradient_combo = QComboBox()
        self.sim_gradient_combo.addItems(["GX", "GY", "GZ", "All"])
        plot_sim_row.addWidget(self.sim_gradient_combo)

        plot_sim_row.addSpacing(20)
        compare_metrics_btn = QPushButton("Compare metrics")
        compare_metrics_btn.clicked.connect(self.compare_simulation_metrics)
        plot_sim_row.addWidget(compare_metrics_btn)

        plot_sim_row.addStretch()

        plot_sim_btn = QPushButton("Plot simulations")
        plot_sim_btn.clicked.connect(self.run_simulation_plot)
        plot_sim_row.addWidget(plot_sim_btn)

        self.sim_root_path = r"Z:\Projects\EddyCurrents\Data_acquisition\Simulation results\COMSOL_extracted_data"
        self.refresh_simulation_cases()

        # space for image preview (zoomable + pannable)
        self.image_label = ZoomLabel(gui_ref=self)
        self.image_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.image_label.setMinimumHeight(300)
        self.image_label.set_pan_enabled(False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self.image_label)
        main_layout.addWidget(scroll)

        drop_hint_label = QLabel("To visualize plots directly, drag and drop .mat files.")
        drop_hint_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(drop_hint_label)

        # Keep compare-files backend alive, but remove the separate visible panel.
        self.compare_file_list = CompareFileListWidget(gui_ref=self)
        self.compare_file_list.hide()

        self.refresh_plot_phantom_dropdown()

    # =========================================================

    def select_base_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Base Directory")
        if folder:
            self.base_path = folder
            self.path_edit.setText(folder)
            self.update_setup_dropdown()
            self.update_phantom_dropdown()
            # save for next time
            self.settings.setValue("last_base_path", folder)
            self.refresh_global_comparison_controls()

    def add_case(self):
        self.add_case_enabled = True
        self.global_compare_group.setVisible(True)

        hidden_cases = [c for c in self.additional_cases if not c['visible']]
        if hidden_cases:
            case = hidden_cases[0]
            for widget in case['widgets']:
                widget.setVisible(True)
            case['visible'] = True

            global_path = self.global_path_edit.text().strip()
            if global_path and os.path.isdir(global_path):
                self._set_case_base_path(case, global_path)

            global_setup = self.global_setup_combo.currentText().strip()
            if global_setup:
                idx_setup = case['setup_combo'].findText(global_setup)
                if idx_setup >= 0:
                    case['setup_combo'].setCurrentIndex(idx_setup)

            global_phantom = self.global_phantom_combo.currentText().strip()
            if global_phantom:
                idx_phantom = case['phantom_combo'].findText(global_phantom)
                if idx_phantom >= 0:
                    case['phantom_combo'].setCurrentIndex(idx_phantom)

            if case['index'] == 2:
                self.update_setup_dropdown_case2()
                self.update_phantom_dropdown_case2()
            self.refresh_global_comparison_controls()
            return

        self._create_dynamic_case_row()
        self.refresh_global_comparison_controls()

    def _create_dynamic_case_row(self):
        case_index = len(self.additional_cases) + 2
        row = QHBoxLayout()
        self.add_cases_container.addLayout(row)
        widgets = []

        lbl_path = QLabel(f"Path{case_index}")
        row.addWidget(lbl_path)
        widgets.append(lbl_path)

        path_edit = QLineEdit()
        path_edit.setMinimumWidth(300)
        row.addWidget(path_edit)
        widgets.append(path_edit)

        browse_btn = QPushButton("Browse")
        row.addWidget(browse_btn)
        widgets.append(browse_btn)

        row.addSpacing(20)

        lbl_setup = QLabel(f"Setup{case_index}")
        row.addWidget(lbl_setup)
        widgets.append(lbl_setup)

        setup_combo = QComboBox()
        setup_combo.setMinimumWidth(150)
        row.addWidget(setup_combo)
        widgets.append(setup_combo)

        row.addSpacing(20)

        lbl_phantom = QLabel(f"Phantom position{case_index}")
        row.addWidget(lbl_phantom)
        widgets.append(lbl_phantom)

        phantom_combo = QComboBox()
        phantom_combo.currentIndexChanged.connect(lambda _=0: self.refresh_plot_phantom_dropdown())
        row.addWidget(phantom_combo)
        widgets.append(phantom_combo)

        delete_btn = QPushButton("Delete")
        row.addWidget(delete_btn)
        widgets.append(delete_btn)

        row.addSpacing(20)

        lbl_legend = QLabel(f"Legend{case_index}")
        row.addWidget(lbl_legend)
        widgets.append(lbl_legend)

        legend_input = QLineEdit()
        legend_input.setPlaceholderText("Custom label")
        legend_input.setMaximumWidth(140)
        row.addWidget(legend_input)
        widgets.append(legend_input)

        row.addStretch()

        case = {
            'index': case_index,
            'base_path': None,
            'row': row,
            'path_edit': path_edit,
            'setup_combo': setup_combo,
            'phantom_combo': phantom_combo,
            'legend_input': legend_input,
            'delete_btn': delete_btn,
            'widgets': widgets,
            'visible': True
        }

        browse_btn.clicked.connect(lambda _=False, c=case: self.select_base_path_case(c))
        setup_combo.currentIndexChanged.connect(lambda _=0, c=case: self.update_phantom_dropdown_case(c))
        setup_combo.currentIndexChanged.connect(lambda _=0: self.refresh_global_comparison_controls())
        delete_btn.clicked.connect(lambda _=False, idx=case_index: self.delete_case(idx))
        path_edit.textChanged.connect(lambda _=None: self.refresh_global_comparison_controls())

        self.additional_cases.append(case)
        self.update_setup_dropdown_case(case)
        self.update_phantom_dropdown_case(case)

        global_path = self.global_path_edit.text().strip()
        if global_path and os.path.isdir(global_path):
            self._set_case_base_path(case, global_path)

        global_setup = self.global_setup_combo.currentText().strip()
        if global_setup:
            idx_setup = case['setup_combo'].findText(global_setup)
            if idx_setup >= 0:
                case['setup_combo'].setCurrentIndex(idx_setup)

        global_phantom = self.global_phantom_combo.currentText().strip()
        if global_phantom:
            idx_phantom = case['phantom_combo'].findText(global_phantom)
            if idx_phantom >= 0:
                case['phantom_combo'].setCurrentIndex(idx_phantom)

    def select_base_path2(self):
        case2 = next((c for c in self.additional_cases if c['index'] == 2), None)
        if case2 is None:
            return
        self.select_base_path_case(case2)

    def select_base_path_case(self, case):
        folder = QFileDialog.getExistingDirectory(self, f"Select Base Directory (Path{case['index']})")
        if folder:
            case['base_path'] = folder
            case['path_edit'].setText(folder)
            if case['index'] == 2:
                self.base_path2 = folder
            self.update_setup_dropdown_case(case)
            self.update_phantom_dropdown_case(case)
            self.refresh_global_comparison_controls()

    def select_comparison_save_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to save comparison plots")
        if folder:
            self.comparison_save_dir = folder

    def delete_case(self, case_index):
        case = next((c for c in self.additional_cases if c['index'] == case_index), None)
        if case is None:
            return

        case['base_path'] = None
        case['path_edit'].clear()
        case['setup_combo'].clear()
        case['phantom_combo'].clear()
        legend_input = case.get('legend_input')
        if legend_input is not None:
            legend_input.clear()
        case['visible'] = False

        for widget in case['widgets']:
            widget.setVisible(False)

        if case_index == 2:
            self.base_path2 = None

        if not any(c.get('visible', False) for c in self.additional_cases):
            self.add_case_enabled = False
            self.global_compare_group.setVisible(False)

        self.refresh_global_comparison_controls()

    def _get_active_compare_cases(self):
        cases = [{
            'index': 1,
            'base_path': self.base_path,
            'path_edit': self.path_edit,
            'setup_combo': self.setup_combo,
            'phantom_combo': self.phantom_combo,
            'visible': True
        }]
        for case in self.additional_cases:
            if case.get('visible', False):
                cases.append(case)
        return cases

    def _set_case_base_path(self, case, new_path):
        if case['index'] == 1:
            self.base_path = new_path
            self.path_edit.setText(new_path)
            self.settings.setValue("last_base_path", new_path)
            self.update_setup_dropdown()
            self.update_phantom_dropdown()
            return

        case['base_path'] = new_path
        case['path_edit'].setText(new_path)
        if case['index'] == 2:
            self.base_path2 = new_path
        self.update_setup_dropdown_case(case)
        self.update_phantom_dropdown_case(case)

    def _list_setup_folders(self, base_path):
        if not base_path or not os.path.isdir(base_path):
            return []
        return sorted([
            f for f in os.listdir(base_path)
            if os.path.isdir(os.path.join(base_path, f))
        ])

    def _list_phantom_positions(self, base_path, setup_name):
        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        if not base_path or not setup_name:
            return []

        setup_path = os.path.join(base_path, setup_name)
        if not os.path.isdir(setup_path):
            return []

        candidates = [
            f for f in os.listdir(setup_path)
            if os.path.isdir(os.path.join(setup_path, f)) and f != "Experimental_data"
        ]

        normalized = []
        for name in candidates:
            canonical = self._canonical_phantom_position(name)
            if canonical in defaults and canonical not in normalized:
                normalized.append(canonical)

        return [p for p in defaults if p in normalized]

    def refresh_global_comparison_controls(self):
        if not hasattr(self, 'global_setup_combo') or self._global_sync_in_progress:
            return

        active_cases = self._get_active_compare_cases()
        base_paths = []
        for case in active_cases:
            base_path = (case.get('base_path') or case['path_edit'].text().strip())
            if not base_path or not os.path.isdir(base_path):
                base_paths = []
                break
            base_paths.append(base_path)

        previous_setup = self.global_setup_combo.currentText().strip()
        self.global_setup_combo.blockSignals(True)
        self.global_setup_combo.clear()

        common_setups = []
        if base_paths:
            shared = None
            for base_path in base_paths:
                current = set(self._list_setup_folders(base_path))
                shared = current if shared is None else (shared & current)
            if shared:
                common_setups = sorted(shared)
                self.global_setup_combo.addItems(common_setups)

        if previous_setup and previous_setup in common_setups:
            self.global_setup_combo.setCurrentText(previous_setup)
        self.global_setup_combo.blockSignals(False)

        selected_setup = self.global_setup_combo.currentText().strip()
        previous_phantom = self.global_phantom_combo.currentText().strip()
        self.global_phantom_combo.blockSignals(True)
        self.global_phantom_combo.clear()

        common_phantoms = []
        if base_paths and selected_setup:
            shared = None
            for base_path in base_paths:
                current = set(self._list_phantom_positions(base_path, selected_setup))
                shared = current if shared is None else (shared & current)
            if shared:
                defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
                common_phantoms = [p for p in defaults if p in shared]
                self.global_phantom_combo.addItems(common_phantoms)

        if previous_phantom and previous_phantom in common_phantoms:
            self.global_phantom_combo.setCurrentText(previous_phantom)
        self.global_phantom_combo.blockSignals(False)

        self.refresh_plot_phantom_dropdown()

    def apply_global_path(self):
        if self._global_sync_in_progress:
            return

        global_path = self.global_path_edit.text().strip()
        if not global_path:
            return
        if not os.path.isdir(global_path):
            QMessageBox.warning(self, "Warning", "Path_global is not a valid directory.")
            return

        self._global_sync_in_progress = True
        try:
            for case in self._get_active_compare_cases():
                self._set_case_base_path(case, global_path)
        finally:
            self._global_sync_in_progress = False

        self.refresh_global_comparison_controls()

    def apply_global_setup(self):
        if self._global_sync_in_progress:
            return

        setup_name = self.global_setup_combo.currentText().strip()
        if not setup_name:
            return

        self._global_sync_in_progress = True
        try:
            for case in self._get_active_compare_cases():
                combo = case['setup_combo']
                idx = combo.findText(setup_name)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            self._global_sync_in_progress = False

        self.refresh_global_comparison_controls()

    def apply_global_phantom(self):
        if self._global_sync_in_progress:
            return

        phantom_name = self.global_phantom_combo.currentText().strip()
        if not phantom_name:
            return

        self._global_sync_in_progress = True
        try:
            for case in self._get_active_compare_cases():
                combo = case['phantom_combo']
                idx = combo.findText(phantom_name)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            self._global_sync_in_progress = False

        self.refresh_global_comparison_controls()

    def update_setup_dropdown(self):
        self.setup_combo.clear()
        if not self.base_path or not os.path.isdir(self.base_path):
            return
        folders = [
            f for f in os.listdir(self.base_path)
            if os.path.isdir(os.path.join(self.base_path, f))
        ]
        self.setup_combo.addItems(folders)
        self._refresh_compare_measured_columns()
        self._refresh_time_domain_materials()

    def _refresh_compare_measured_columns(self):
        if not hasattr(self, "compare_meas_combo"):
            return

        previous = self.compare_meas_combo.currentText().strip()
        prev_match = re.match(r"^(B_integrated(?:_.+)?)_\d+(?:\.\d+)?ms$", previous)
        if prev_match:
            previous = prev_match.group(1)
        columns = []

        base = (self.base_path or "").strip()
        setup = (self.setup_combo.currentText() if hasattr(self, "setup_combo") else "").strip()

        table_path = None
        if base and setup:
            setup_canonical = setup.split("_")[0] if "_" in setup else setup
            candidates = [
                os.path.join(base, setup, f"Beddy_measured_at_t0_{setup_canonical}.txt"),
                os.path.join(base, setup, f"Beddy_measured_at_t0_{setup}.txt"),
            ]
            for p in candidates:
                if os.path.exists(p):
                    table_path = p
                    break

            if table_path is None:
                setup_dir = os.path.join(base, setup)
                if os.path.isdir(setup_dir):
                    for fname in sorted(os.listdir(setup_dir)):
                        if fname.startswith("Beddy_measured_at_t0_") and fname.lower().endswith(".txt"):
                            table_path = os.path.join(setup_dir, fname)
                            break

        if table_path and os.path.exists(table_path):
            try:
                df_cols = pd.read_csv(table_path, sep="\t", nrows=1).columns
            except Exception:
                try:
                    df_cols = pd.read_csv(table_path, sep=r"\s+", engine="python", skipinitialspace=True, nrows=1).columns
                except Exception:
                    df_cols = []

            seen = set()
            for col in df_cols:
                col_text = str(col).strip()
                if not col_text:
                    continue
                if col_text.lower().startswith("unnamed:"):
                    continue
                if col_text in ("Grad", "Phantom_position"):
                    continue
                if col_text in seen:
                    continue
                seen.add(col_text)
                columns.append(col_text)

        if not columns:
            columns = [
                "B_measured_at_t0_FirstPoint",
                "B_measured_at_t0_Fitted",
                "B_measured_at_t0_PreFiltered",
                "B_integrated",
            ]

        # Keep raw (non-canonicalized) columns for extraction logic.
        self._compare_measured_raw_columns = list(columns)

        columns = self._build_metric_options(columns)

        self.compare_meas_combo.blockSignals(True)
        self.compare_meas_combo.clear()
        self.compare_meas_combo.addItems(columns)
        if previous and previous in columns:
            self.compare_meas_combo.setCurrentText(previous)
        self.compare_meas_combo.blockSignals(False)

    def _build_metric_options(self, raw_columns):
        options = []
        seen = set()

        for col in raw_columns:
            name = str(col).strip()
            if not name:
                continue
            if name.lower().startswith("unnamed:"):
                continue
            if name in ("Grad", "Phantom_position"):
                continue
            if "rmse%" in name.lower():
                continue

            canonical = name
            if name.startswith("B_integrated"):
                m = re.match(r"^(B_integrated(?:_.+)?)_\d+(?:\.\d+)?ms$", name)
                if m:
                    canonical = m.group(1)
            if canonical in seen:
                continue

            seen.add(canonical)
            options.append(canonical)

        for special in ["B_integrated", "Exp_fit"]:
            if special not in seen:
                options.append(special)
                seen.add(special)

        return options

    def _ask_b_integrated_window_selection(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("B_integrated windows")
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Select time windows to include for selected B_integrated metrics:"))

        window_order = ["1ms", "3ms", "5ms", "10ms", "All"]
        checks = []
        for w in window_order:
            cb = QCheckBox(w)
            cb.setChecked(False)
            checks.append((w, cb))
            layout.addWidget(cb)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return None

        selected = [w for w, cb in checks if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Warning", "Select at least one B_integrated window.")
            return None
        return selected

    def _ask_single_b_integrated_window(self):
        items = ["All", "1ms", "3ms", "5ms", "10ms"]
        selected, ok = QInputDialog.getItem(
            self,
            "B_integrated window",
            "Select time window:",
            items,
            0,
            False,
        )
        if not ok:
            return None
        return str(selected).strip()

    def _expand_b_integrated_metrics_by_windows(self, selected_metrics, all_measured_columns):
        selected = [str(m).strip() for m in selected_metrics if str(m).strip()]
        available = set(str(c).strip() for c in all_measured_columns if str(c).strip())

        bases = [
            m for m in selected
            if m.startswith("B_integrated")
            and "rmse%" not in m.lower()
            and not re.search(r"_\d+(?:\.\d+)?ms$", m)
        ]
        if not bases:
            return selected

        windows = self._ask_b_integrated_window_selection()
        if windows is None:
            return None

        expanded = []
        seen = set()

        for metric in selected:
            if metric in ("Exp_fit",):
                if metric not in seen:
                    expanded.append(metric)
                    seen.add(metric)
                continue

            is_b_integrated_base = (
                metric.startswith("B_integrated")
                and "rmse%" not in metric.lower()
                and not re.search(r"_\d+(?:\.\d+)?ms$", metric)
            )

            if not is_b_integrated_base:
                if metric not in seen:
                    expanded.append(metric)
                    seen.add(metric)
                continue

            added_any = False
            for w in windows:
                candidate = metric if w == "All" else f"{metric}_{w}"
                if candidate in available and candidate not in seen:
                    expanded.append(candidate)
                    seen.add(candidate)
                    added_any = True

            if (not added_any) and metric in available and metric not in seen:
                expanded.append(metric)
                seen.add(metric)

        return expanded

    def _with_rmse_companions(self, selected_metrics, all_measured_columns):
        """Append available <metric>_RMSE% columns for selected metrics.

        RMSE columns are hidden from selection UIs but included automatically
        in extracted tables when their paired metric is selected.
        """
        selected = [str(m).strip() for m in selected_metrics if str(m).strip()]
        available = set(str(c).strip() for c in all_measured_columns if str(c).strip())
        out = []
        seen = set()

        for metric in selected:
            if metric not in seen:
                out.append(metric)
                seen.add(metric)

            if "rmse%" in metric.lower():
                continue

            companion = f"{metric}_RMSE%"
            if companion in available and companion not in seen:
                out.append(companion)
                seen.add(companion)

        return out

    def update_setup_dropdown_case2(self):
        case2 = next((c for c in self.additional_cases if c['index'] == 2), None)
        if case2 is None:
            return
        if self.base_path2:
            case2['base_path'] = self.base_path2
            case2['path_edit'].setText(self.base_path2)
        self.update_setup_dropdown_case(case2)

    def update_setup_dropdown_case(self, case):
        combo = case['setup_combo']
        combo.clear()
        base_path = case['base_path'] or case['path_edit'].text().strip()
        if not base_path or not os.path.isdir(base_path):
            return
        folders = [
            f for f in os.listdir(base_path)
            if os.path.isdir(os.path.join(base_path, f))
        ]
        combo.addItems(folders)

    def _canonical_phantom_position(self, value):
        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        raw = str(value or "").strip()
        if not raw:
            return "Center"

        s = raw.replace('\\', '/').upper()

        if "CENTER" in s:
            return "Center"

        for axis in ["X", "Y", "Z"]:
            if f"+{axis}" in s or f"+/{axis}" in s:
                return f"+{axis}"
            if f"-{axis}" in s or f"-/{axis}" in s:
                return f"-{axis}"

        for d in defaults:
            if raw == d:
                return d

        return raw

    def update_phantom_dropdown(self):
        if not hasattr(self, "phantom_combo"):
            return
        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        self.phantom_combo.clear()
        setup_name = self.setup_combo.currentText()
        if not self.base_path or not setup_name:
            self.phantom_combo.addItems(defaults)
            return

        setup_path = os.path.join(self.base_path, setup_name)
        if not os.path.isdir(setup_path):
            self.phantom_combo.addItems(defaults)
            return

        candidates = [
            f for f in os.listdir(setup_path)
            if os.path.isdir(os.path.join(setup_path, f)) and f != "Experimental_data"
        ]

        if candidates:
            normalized = []
            for c in candidates:
                n = self._canonical_phantom_position(c)
                if n in defaults and n not in normalized:
                    normalized.append(n)
            if normalized:
                ordered = [d for d in defaults if d in normalized]
                self.phantom_combo.addItems(ordered)
            else:
                self.phantom_combo.addItems(defaults)
        else:
            self.phantom_combo.addItems(defaults)

    def update_phantom_dropdown_case2(self):
        case2 = next((c for c in self.additional_cases if c['index'] == 2), None)
        if case2 is None:
            return
        self.update_phantom_dropdown_case(case2)

    def update_phantom_dropdown_case(self, case):
        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        combo = case['phantom_combo']
        combo.clear()
        setup_name = case['setup_combo'].currentText()
        base_path = case['base_path'] or case['path_edit'].text().strip()
        if not base_path or not setup_name:
            combo.addItems(defaults)
            return

        setup_path = os.path.join(base_path, setup_name)
        if not os.path.isdir(setup_path):
            combo.addItems(defaults)
            return

        candidates = [
            f for f in os.listdir(setup_path)
            if os.path.isdir(os.path.join(setup_path, f)) and f != "Experimental_data"
        ]

        if candidates:
            normalized = []
            for c in candidates:
                n = self._canonical_phantom_position(c)
                if n in defaults and n not in normalized:
                    normalized.append(n)
            if normalized:
                ordered = [d for d in defaults if d in normalized]
                combo.addItems(ordered)
            else:
                combo.addItems(defaults)
        else:
            combo.addItems(defaults)

    def add_new_setup(self):
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return
        text, ok = QInputDialog.getText(self, "New Setup", "Enter setup name:")
        if ok and text.strip():
            new_folder = os.path.join(self.base_path, text.strip())
            if not os.path.exists(new_folder):
                os.makedirs(new_folder)
                # create Experimental_data subfolder immediately
                os.makedirs(os.path.join(new_folder, "Experimental_data"), exist_ok=True)
                self.update_setup_dropdown()
                self.setup_combo.setCurrentText(text.strip())
            else:
                QMessageBox.information(self, "Info", "Folder already exists.")

    def browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        for file in files:
            self.file_list.addItem(file)

    def file_list_clear_safe(self):
        self.file_list.clear()

    def confirm_upload(self):

        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path.")
            return

        setup_name = self.setup_combo.currentText()
        if not setup_name:
            QMessageBox.warning(self, "Warning", "Select Setup.")
            return

        if self.file_list.count() == 0:
            QMessageBox.warning(self, "Warning", "No files selected.")
            return

        phantom_position = self._canonical_phantom_position(self.phantom_combo.currentText())

        target_dir = os.path.join(
            self.base_path,
            setup_name,
            phantom_position
        )

        os.makedirs(target_dir, exist_ok=True)

        try:
            for i in range(self.file_list.count()):
                file_path = self.file_list.item(i).text()
                shutil.copy2(file_path, target_dir)

            QMessageBox.information(
                self,
                "Success",
                f"{self.file_list.count()} files copied successfully."
            )

            self.file_list.clear()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def extract_experimental_files(self):
        """Copy .m files from the setup's Experimental_data folder into
        the corresponding sample_pos subdirectories.

        Each MATLAB file is searched for a line defining ``sample_pos``.
        The quoted value is normalized and used as the name of the target
        directory (e.g. ``+x`` -> ``+X``, ``center`` -> ``Center``).
        """
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        setup = self.setup_combo.currentText()
        if not setup:
            QMessageBox.warning(self, "Warning", "Select Setup.")
            return

        exp_dir = os.path.join(self.base_path, setup, "Experimental_data")
        if not os.path.isdir(exp_dir):
            QMessageBox.warning(
                self,
                "Warning",
                "No Experimental_data folder found for this setup."
            )
            return

        # accept both Matlab script (.m) and data (.mat) files
        mfiles = [f for f in os.listdir(exp_dir)
                  if f.lower().endswith(('.m', '.mat'))]
        if not mfiles:
            QMessageBox.information(
                self,
                "Info",
                "No .m or .mat files present in Experimental_data."
            )
            return

        def normalize_pos(pos: str) -> str | None:
            p = pos.strip()
            if not p:
                return None
            return self._canonical_phantom_position(p)

        copied = 0
        skipped = []
        details = []

        for fname in mfiles:
            path = os.path.join(exp_dir, fname)
            sample_pos = None

            # handle Matlab data files separately, they aren't plain text
            if fname.lower().endswith('.mat'):
                try:
                    from scipy.io import loadmat
                    mat = loadmat(path)
                    if 'sample_pos' in mat:
                        val = mat['sample_pos']
                        # unwrap numpy values or bytes
                        candidate = val
                        try:
                            import numpy as _np
                            if isinstance(val, (_np.ndarray, list, tuple)):
                                candidate = val.flat[0]
                        except Exception:
                            pass
                        if isinstance(candidate, bytes):
                            candidate = candidate.decode('utf-8', errors='ignore')
                        sample_pos = normalize_pos(str(candidate))
                except Exception:
                    # if scipy isn't available or loading fails, fall back silently
                    pass
            else:
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if 'sample_pos' in line:
                                m = re.search(r"sample_pos\s*=\s*['\"]([^'\"]+)['\"]", line)
                                if m:
                                    sample_pos = normalize_pos(m.group(1))
                                    break
                except Exception:
                    # ignore bad files
                    continue

            if sample_pos:
                target_dir = os.path.join(self.base_path, setup, sample_pos)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(path, os.path.join(target_dir, fname))
                details.append(f"{fname} -> {sample_pos}")
                copied += 1
            else:
                skipped.append(fname)

        msg = f"Copied {copied} file(s)."
        if details:
            msg += "\n" + "\n".join(details)
        if skipped:
            msg += "\nSkipped (no sample_pos found):\n" + "\n".join(skipped)

        QMessageBox.information(self, "Extraction Complete", msg)

    def run_comparison(self):

        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        self._refresh_compare_measured_columns()

        setup = self.setup_combo.currentText()
        gradient = self.compare_grad_combo.currentText()
        measured_column = self.compare_meas_combo.currentText()

        if measured_column == "Exp_fit":
            QMessageBox.information(
                self,
                "Exp_fit",
                "Exp_fit from Metrics dropdown is not available in Plot yet. Use 'Extract single-value metrics' for Exp_fit tables.",
            )
            return

        is_b_integrated_windowed = bool(re.search(r"_\d+(?:\.\d+)?ms$", measured_column))
        if measured_column.startswith("B_integrated") and not is_b_integrated_windowed:
            selected_window = self._ask_single_b_integrated_window()
            if selected_window is None:
                return
            measured_column = measured_column if selected_window == "All" else f"{measured_column}_{selected_window}"

        selected_plot_type = self.compare_plot_combo.currentText()
        compare_with_sim = bool(self.compare_with_sim_checkbox.isChecked())
        sim_histogram_mode = self.compare_sim_hist_mode_combo.currentText() if compare_with_sim else "Beddy_average_FOV (uT)"
        xlim_50mm = self.xlim_50mm_checkbox.isChecked() if compare_with_sim else False
        normalize_histogram = self.normalize_hist_checkbox.isChecked()
        apply_custom_hist_labels = bool(self.change_legend_checkbox.isChecked())
        custom_hist_labels = self._collect_case_custom_legends() if apply_custom_hist_labels else []
        gradient_token = f"G{gradient}"

        # normalize requested naming for plot type token
        if str(selected_plot_type).lower().startswith("hist"):
            plot_type_token = "Histogram"
        else:
            plot_type_token = "Points"
        
        try:
            active_extra_cases = []
            for case in self.additional_cases:
                if not case.get('visible', False):
                    continue
                case_base = case.get('base_path') or case['path_edit'].text().strip()
                case_setup = case['setup_combo'].currentText()
                case_phantom = self._canonical_phantom_position(case['phantom_combo'].currentText())
                if case_base and case_setup and case_phantom:
                    active_extra_cases.append({
                        'base_path': case_base,
                        'setup': case_setup,
                        'phantom': case_phantom
                    })

            compare_cases = [{
                'base_path': self.base_path,
                'setup': setup,
                'phantom': self.phantom_combo.currentText()
            }]
            if self.add_case_enabled and len(active_extra_cases) > 0:
                compare_cases.extend(active_extra_cases)

            is_multi_case_compare = len(compare_cases) > 1

            if is_multi_case_compare:
                colormap_choice, ok = QInputDialog.getItem(
                    self,
                    "Select colormap",
                    "Colormap:",
                    ["Single-color gradient", "Viridis", "Inferno"],
                    0,
                    False)
                if not ok:
                    return
            else:
                colormap_choice = "Single-color gradient"

            if compare_with_sim:
                fig = compare_with_simulation(
                    base_path=self.base_path,
                    setup=setup,
                    gradient=gradient,
                    measured_column=measured_column,
                    plot_type=selected_plot_type,
                    save_figure=False,
                    cases=compare_cases,
                    include_simulation=True,
                    colormap=colormap_choice,
                    xlim_50mm=xlim_50mm,
                    sim_histogram_mode=sim_histogram_mode,
                    normalize_histogram=normalize_histogram,
                    custom_case_labels=custom_hist_labels,
                    apply_custom_hist_labels=apply_custom_hist_labels,
                )
            else:
                fig = self._build_single_value_measured_figure(
                    compare_cases=compare_cases,
                    gradient=gradient,
                    measured_column=measured_column,
                    plot_type=selected_plot_type,
                    custom_labels=custom_hist_labels if apply_custom_hist_labels else None,
                    colormap=colormap_choice,
                )

            self._maybe_compact_dimensions(fig)
            self._maybe_customize_legends(fig)
            self._maybe_customize_fonts(fig)

            mother_folders = []
            setup_names = []
            for case in compare_cases:
                mother = os.path.basename(os.path.normpath(case.get('base_path', '')))
                stp = str(case.get('setup', '')).strip()
                if mother and mother not in mother_folders:
                    mother_folders.append(mother)
                if stp and stp not in setup_names:
                    setup_names.append(stp)

            case_tag_parts = mother_folders + setup_names
            case_tag = "_".join(case_tag_parts) if case_tag_parts else setup

            self.current_analysis_figure = fig
            self.current_analysis_image_path = None
            self.current_analysis_table_frames = None
            self.current_analysis_table_filename = None
            self.current_analysis_filename = (
                f"Measurements_{'vs_simulations_' if compare_with_sim else ''}{gradient_token}_"
                f"{plot_type_token}_{measured_column}_{case_tag}"
            )

            import tempfile
            temp_path = os.path.join(tempfile.gettempdir(), f"single_value_preview_{gradient_token}.png")
            fig.savefig(temp_path, dpi=200, bbox_inches='tight')
            pix = QPixmap(temp_path)
            self.image_label.setPixmap(pix)
            self.image_label.setMinimumHeight(380)

            QMessageBox.information(
                self,
                "Success",
                "Single-value plot generated. Use 'Save plot' to export it."
            )
            
        except FileNotFoundError as e:
            QMessageBox.critical(
                self, "Error",
                f"Missing required file:\n\n{str(e)}\n\n"
                f"Make sure you have:\n"
                f"1. Run 'Analyze' first to generate measured table\n"
                f"2. Placed simulation table in setup folder"
            )
        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Data format error:\n\n{str(e)}")
        except KeyError as e:
            QMessageBox.critical(
                self, "Error",
                f"Missing column in table:\n\n{str(e)}\n\n"
                f"This may indicate a table format issue."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Comparison failed:\n\n{str(e)}")

    def update_single_value_sim_controls(self):
        enabled = bool(getattr(self, "compare_with_sim_checkbox", None) and self.compare_with_sim_checkbox.isChecked())
        for w in [
            getattr(self, "compare_sim_hist_label", None),
            getattr(self, "compare_sim_hist_mode_combo", None),
            getattr(self, "xlim_50mm_checkbox", None),
        ]:
            if w is None:
                continue
            w.setVisible(enabled)
            w.setEnabled(enabled)

        self._update_compare_gradient_options(enabled)

    def _on_sim_phantom_type_changed(self, phantom_type):
        """Show/hide H and R controls based on phantom type selection."""
        is_cylinder = (phantom_type == "Cylinder")
        for w in (self.sim_h_label, self.sim_h_combo, self.sim_r_label, self.sim_r_combo):
            w.setVisible(is_cylinder)
        if is_cylinder:
            self._refresh_cylinder_hr_dropdowns()

    def _selected_sim_materials(self):
        if not hasattr(self, "sim_materials_list"):
            return []
        selected = [item.text().strip() for item in self.sim_materials_list.selectedItems() if item.text().strip()]
        if selected:
            return selected
        return [
            self.sim_materials_list.item(i).text().strip()
            for i in range(self.sim_materials_list.count())
            if self.sim_materials_list.item(i).text().strip()
        ]

    def _refresh_time_domain_materials(self):
        if not hasattr(self, "sim_materials_list"):
            return

        setup_name = self.setup_combo.currentText().strip() if hasattr(self, "setup_combo") else ""
        previous_selection = set(self._selected_sim_materials())
        materials = self._time_domain_sim_loader.detect_available_materials(setup_name, gradient="GX")

        self.sim_materials_list.blockSignals(True)
        self.sim_materials_list.clear()
        for material in materials:
            self.sim_materials_list.addItem(material)

        if materials:
            restored = False
            if previous_selection:
                for idx in range(self.sim_materials_list.count()):
                    item = self.sim_materials_list.item(idx)
                    if item.text() in previous_selection:
                        item.setSelected(True)
                        restored = True
            if not restored:
                for idx in range(self.sim_materials_list.count()):
                    self.sim_materials_list.item(idx).setSelected(True)
        self.sim_materials_list.blockSignals(False)

    def _on_sim_material_selection_changed(self):
        self._refresh_cylinder_hr_dropdowns()

    def _refresh_cylinder_hr_dropdowns(self):
        """Scan available Cylinder files and populate H/R dropdowns."""
        # During startup, setup changes may fire before cylinder widgets exist.
        if not hasattr(self, "sim_h_combo") or not hasattr(self, "sim_r_combo"):
            return

        setup_name = self.setup_combo.currentText().strip() if hasattr(self, "setup_combo") else ""
        selected_materials = self._selected_sim_materials()
        h_values, r_values = self._cylinder_sim_loader.detect_hr_values(
            setup_name,
            materials=selected_materials,
        )

        prev_h = self.sim_h_combo.currentText()
        prev_r = self.sim_r_combo.currentText()

        self.sim_h_combo.blockSignals(True)
        self.sim_r_combo.blockSignals(True)

        self.sim_h_combo.clear()
        self.sim_r_combo.clear()

        if h_values:
            self.sim_h_combo.addItems(h_values)
            if prev_h in h_values:
                self.sim_h_combo.setCurrentText(prev_h)
        else:
            self.sim_h_combo.addItem("(none)")

        if r_values:
            self.sim_r_combo.addItems(r_values)
            if prev_r in r_values:
                self.sim_r_combo.setCurrentText(prev_r)
        else:
            self.sim_r_combo.addItem("(none)")

        self.sim_h_combo.blockSignals(False)
        self.sim_r_combo.blockSignals(False)

    def _active_sim_loader(self):
        """Return the appropriate loader based on the selected phantom type."""
        phantom_type = getattr(self, "sim_phantom_type_combo", None)
        if phantom_type and phantom_type.currentText() == "Cylinder":
            h_str = self.sim_h_combo.currentText().strip()
            r_str = self.sim_r_combo.currentText().strip()
            self._cylinder_sim_loader.set_selected_hr(h_str, r_str)
            return self._cylinder_sim_loader
        return self._time_domain_sim_loader

    def _current_sim_case_spec(self):
        """
        Build a dict describing the currently configured sim overlay case,
        including a dedicated loader instance already configured with H/R.
        """
        phantom_type = getattr(self, "sim_phantom_type_combo", None)
        ptype = phantom_type.currentText() if phantom_type else "Point"
        offset_mode = str(getattr(self, "_time_domain_sim_offset_mode", "none")).lower()
        selected_offsets = list(getattr(self, "_time_domain_sim_selected_offsets", []))
        selected_materials = self._selected_sim_materials()

        if ptype == "Cylinder":
            h_str = self.sim_h_combo.currentText().strip()
            r_str = self.sim_r_combo.currentText().strip()
            loader = CylinderTimeDomainLoader(
                simulation_root=self._cylinder_sim_loader.simulation_root,
                time_zero_ms=self._cylinder_sim_loader.time_zero_ms,
            )
            loader.set_selected_hr(h_str, r_str)
            h_label = loader._compact_number(h_str) if h_str not in ("", "(none)") else "?"
            r_label = loader._compact_number(r_str) if r_str not in ("", "(none)") else "?"
        else:
            loader = self._time_domain_sim_loader
            h_label = ""
            r_label = ""

        return {
            "phantom_type": ptype,
            "h": h_label,
            "r": r_label,
            "offset_mode": offset_mode,
            "selected_offsets": selected_offsets,
            "selected_materials": selected_materials,
            "loader": loader,
        }

    def _add_sim_overlay_case(self):
        """Append current sim selection to the session (deduplicated). No re-plot, no colormap dialog."""
        if not self._time_domain_sim_overlay_enabled:
            return
        spec = self._current_sim_case_spec()

        existing_keys = {self._sim_overlay_spec_key(c) for c in self._sim_overlay_session_cases}
        if self._sim_overlay_spec_key(spec) not in existing_keys:
            self._sim_overlay_session_cases.append(spec)

        self._update_sim_cases_status()

    def _clear_sim_overlay_cases(self):
        """Remove all sim overlay cases and reset session colormap."""
        self._sim_overlay_session_cases = []
        self._sim_overlay_session_colormap = None
        self._sim_overlay_spec_color_map = {}
        self._sim_overlay_color_index = 0
        self._update_sim_cases_status()

    @staticmethod
    def _sim_overlay_spec_key(spec):
        return (
            spec.get("phantom_type"),
            spec.get("h"),
            spec.get("r"),
            spec.get("offset_mode"),
            tuple(sorted(spec.get("selected_offsets", []))),
            tuple(sorted(spec.get("selected_materials", []))),
        )

    @staticmethod
    def _rounded_rgba(color, ndigits=6):
        try:
            if isinstance(color, str):
                import matplotlib.colors as mcolors
                rgba = mcolors.to_rgba(color)
            else:
                rgba = tuple(color)
            return tuple(round(float(c), ndigits) for c in rgba[:4])
        except Exception:
            return None

    def _next_unused_sim_overlay_color(self, colormap_name, forbidden_colors=None):
        import matplotlib.cm as cm

        forbidden = set()
        for c in list(self._sim_overlay_spec_color_map.values()) + list(forbidden_colors or []):
            rc = self._rounded_rgba(c)
            if rc is not None:
                forbidden.add(rc)

        cmap_name = str(colormap_name or "Viridis")
        if cmap_name in ("Viridis", "Inferno"):
            cmap = cm.get_cmap(cmap_name.lower())
            upper = 0.70 if cmap_name == "Inferno" else 0.85
            slots = 256
            for i in range(slots):
                idx = (self._sim_overlay_color_index + i) % slots
                candidate = cmap((idx / max(1, slots - 1)) * upper)
                rc = self._rounded_rgba(candidate)
                if rc not in forbidden:
                    self._sim_overlay_color_index = (idx + 1) % slots
                    return candidate

        rng = np.random.default_rng()
        for _ in range(1024):
            candidate = (
                float(rng.uniform(0.05, 0.95)),
                float(rng.uniform(0.05, 0.95)),
                float(rng.uniform(0.05, 0.95)),
                1.0,
            )
            rc = self._rounded_rgba(candidate)
            if rc not in forbidden:
                return candidate
        return (0.0, 0.0, 0.0, 1.0)

    def _sim_overlay_color_for_spec(self, spec, colormap_name, forbidden_colors=None):
        key = self._sim_overlay_spec_key(spec or {})
        if key in self._sim_overlay_spec_color_map:
            return self._sim_overlay_spec_color_map[key]
        color = self._next_unused_sim_overlay_color(colormap_name, forbidden_colors=forbidden_colors)
        self._sim_overlay_spec_color_map[key] = color
        return color

    def _ensure_sim_overlay_colormap_selected(self):
        if not self._time_domain_simulation_overlay_requested():
            return True
        if getattr(self, "_sim_overlay_session_colormap", None):
            return True
        colormap_choice, ok = QInputDialog.getItem(
            self,
            "Select colormap",
            "Colormap:",
            ["Viridis", "Inferno", "Single-color gradient"],
            0,
            False,
        )
        if not ok:
            return False
        self._sim_overlay_session_colormap = colormap_choice
        self._sim_overlay_spec_color_map = {}
        self._sim_overlay_color_index = 0
        return True

    def _update_sim_cases_status(self):
        label = getattr(self, "sim_cases_status", None)
        if label is None:
            return
        n = len(self._sim_overlay_session_cases)
        if n == 0:
            label.setText("")
        elif n == 1:
            label.setText("1 sim case")
        else:
            label.setText(f"{n} sim cases")

    def update_time_domain_sim_controls(self):
        enabled = bool(
            getattr(self, "time_domain_sim_compare_checkbox", None)
            and self.time_domain_sim_compare_checkbox.isChecked()
        )
        self._time_domain_sim_overlay_enabled = enabled

        for w in [
            getattr(self, "time_domain_sim_offsets_btn", None),
            getattr(self, "time_domain_sim_offsets_status", None),
        ]:
            if w is None:
                continue
            w.setVisible(enabled)
            w.setEnabled(enabled)

        if enabled:
            self._update_time_domain_offsets_status()

    def configure_time_domain_simulation_offsets(self):
        if not self._time_domain_sim_overlay_enabled:
            return

        setup_name = self.setup_combo.currentText().strip() if hasattr(self, "setup_combo") else ""
        loader = self._active_sim_loader()
        selected_materials = self._selected_sim_materials()
        available_offsets = loader.detect_available_offsets(
            setup_name,
            materials=selected_materials,
        )

        mode_label, ok = QInputDialog.getItem(
            self,
            "Simulation offsets",
            "Offset mode:",
            ["No offsets", "Select offsets", "All offsets"],
            0,
            False,
        )
        if not ok:
            return

        if mode_label == "No offsets":
            self._time_domain_sim_offset_mode = "none"
            self._time_domain_sim_selected_offsets = []
            self._update_time_domain_offsets_status()
            return

        if mode_label == "All offsets":
            self._time_domain_sim_offset_mode = "all"
            self._time_domain_sim_selected_offsets = list(available_offsets)
            self._update_time_domain_offsets_status()
            if not available_offsets:
                QMessageBox.information(
                    self,
                    "Simulation offsets",
                    f"No simulation offset files found for {setup_name or 'the selected setup'}.",
                )
            return

        if not available_offsets:
            QMessageBox.information(
                self,
                "Simulation offsets",
                f"No simulation offset files found for {setup_name or 'the selected setup'}.",
            )
            self._time_domain_sim_offset_mode = "none"
            self._time_domain_sim_selected_offsets = []
            self._update_time_domain_offsets_status()
            return

        dlg = _SimulationOffsetSelectionDialog(
            available_offsets,
            selected_offsets=self._time_domain_sim_selected_offsets,
            parent=self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return

        selected = dlg.selected_offsets()
        if not selected:
            self._time_domain_sim_offset_mode = "none"
            self._time_domain_sim_selected_offsets = []
        else:
            self._time_domain_sim_offset_mode = "selected"
            self._time_domain_sim_selected_offsets = list(selected)
        self._update_time_domain_offsets_status()

    def _update_time_domain_offsets_status(self):
        label = getattr(self, "time_domain_sim_offsets_status", None)
        if label is None:
            return

        mode = str(getattr(self, "_time_domain_sim_offset_mode", "none")).lower()
        selected = list(getattr(self, "_time_domain_sim_selected_offsets", []))
        if mode == "all":
            text = "All offsets"
        elif mode == "selected" and selected:
            text = ", ".join(selected)
        else:
            text = "No offsets"
        label.setText(text)

    def _time_domain_simulation_overlay_requested(self):
        return bool(getattr(self, "_time_domain_sim_overlay_enabled", False))

    def _load_time_domain_simulation_overlays(self, cases, gradients, locations):
        """
        Load sim overlay curves for all cases in the session.
        If the session is empty but the overlay is enabled, auto-populate it
        from the current UI selection so the first Plot Just Works.
        Returns [] if overlay is not enabled.
        """
        if not self._time_domain_simulation_overlay_requested():
            return []

        # Auto-seed: if no cases have been added yet, treat the current UI
        # selection as the one case to show (without permanently storing it,
        # so the user can still use Add/Clear freely afterwards).
        specs = list(self._sim_overlay_session_cases)
        if not specs:
            specs = [self._current_sim_case_spec()]

        warnings = []
        all_payloads = []
        for spec in specs:
            loader = spec["loader"]
            offset_mode = spec["offset_mode"]
            selected_offsets = spec["selected_offsets"]
            selected_materials = spec.get("selected_materials", [])

            per_setup = {}
            for case in cases:
                setup_name = str(case.get("setup", "")).strip()
                if not setup_name or setup_name in per_setup:
                    continue
                payload = loader.load_plot_ready_data(
                    setup_name=setup_name,
                    gradients=gradients,
                    locations=locations,
                    offset_mode=offset_mode,
                    selected_offsets=selected_offsets,
                    materials=selected_materials,
                )
                per_setup[setup_name] = payload
                warnings.extend(payload.get("warnings", []))

            # Attach spec metadata so the plotting code can build labels
            for setup_name, payload in per_setup.items():
                payload["_spec"] = spec
            all_payloads.append(per_setup)

        self._time_domain_simulation_warning_buffer = self._dedupe_texts(warnings)
        return all_payloads

    def _dedupe_texts(self, texts):
        seen = set()
        ordered = []
        for text in texts:
            text = str(text).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    def _offset_overlay_color_map(self, offset_keys):
        unique_keys = [key for key in self._dedupe_texts(offset_keys) if key]
        if not unique_keys:
            return {}
        import matplotlib.cm as cm

        cmap = cm.get_cmap("tab10", max(1, len(unique_keys)))
        return {key: cmap(idx) for idx, key in enumerate(unique_keys)}

    @staticmethod
    def _sim_legend_label(spec, offset_key, material_name=None):
        """
        Build the legend label for a simulation curve.
          Point:    <material>_point  /  <material>_point_offset_X5
          Cylinder: <material>_cil_radius<R>_height<H>  /  <material>_cil_radius<R>_height<H>_offset_Z3
        The offset suffix always includes the axis letter and numeric value.
        """
        ptype = str(spec.get("phantom_type", "Point")) if spec else "Point"
        prefix = str(material_name or "sim").strip() or "sim"

        offset_suffix = ""
        if offset_key:
            # offset_key format: "Offset_X_5mm" / "Offset_-Y_10mm" etc.
            m = re.match(r"Offset_([XYZ])_(-?\d+(?:\.\d+)?)mm", str(offset_key), re.IGNORECASE)
            if m:
                axis = m.group(1).upper()
                val = m.group(2)
                try:
                    fval = float(val)
                    val = str(int(fval)) if fval == int(fval) else f"{fval:g}"
                except Exception:
                    pass
                offset_suffix = f"_offset_{axis}{val}"

        if ptype == "Cylinder":
            r = spec.get("r", "?")
            h = spec.get("h", "?")
            return f"{prefix}_cil_radius{r}_height{h}{offset_suffix}"
        return f"{prefix}_point{offset_suffix}"

    def _build_sim_label_color_map(self, sim_overlays_list, colormap_name):
        """Assign one unique color per simulation legend label for the current figure."""
        labels = []
        seen = set()
        for per_setup in sim_overlays_list or []:
            for payload in per_setup.values():
                spec = payload.get("_spec")
                for grad_map in payload.get("curves", {}).values():
                    for curve_list in grad_map.values():
                        for curve in curve_list:
                            label = self._sim_legend_label(
                                spec,
                                curve.get("offset_key"),
                                material_name=curve.get("material"),
                            )
                            if label and label not in seen:
                                seen.add(label)
                                labels.append(label)

        if not labels:
            return {}

        import matplotlib.cm as cm
        cmap_name = str(colormap_name or "Viridis")
        if cmap_name not in ("Viridis", "Inferno"):
            cmap_name = "Viridis"

        cmap = cm.get_cmap(cmap_name.lower())
        upper = 0.70 if cmap_name == "Inferno" else 0.85
        n_labels = len(labels)
        if n_labels == 1:
            positions = [0.5 * upper]
        else:
            positions = np.linspace(0.0, upper, n_labels)
        return {label: cmap(float(pos)) for label, pos in zip(labels, positions)}

    def _plot_time_domain_simulation_curves(
        self,
        ax,
        curves,
        measured_color=None,
        sim_color=None,
        label_color_map=None,
        offset_color_map=None,
        linewidth=1.4,
        spec=None,
    ):
        """
        Plot time-domain simulation curves.

        Colors are assigned per simulation legend label via label_color_map.
        """

        if label_color_map is None:
            label_color_map = {}

        if offset_color_map is None:
            offset_color_map = {}

        is_cylinder = (spec or {}).get("phantom_type", "Point") == "Cylinder"

        linestyle = "--" if is_cylinder else "-."

        for curve in curves:

            offset_key = curve.get("offset_key")

            label = self._sim_legend_label(spec, offset_key, material_name=curve.get("material"))
            line_color = label_color_map.get(label, "black")

            ax.plot(
                np.asarray(curve.get("time_ms", []), dtype=float),
                np.asarray(curve.get("values", []), dtype=float),
                linestyle,
                linewidth=linewidth,
                color=line_color,
                alpha=0.95,
                label=label,
            )
    def _show_time_domain_simulation_warnings(self):
        warnings = list(getattr(self, "_time_domain_simulation_warning_buffer", []))
        self._time_domain_simulation_warning_buffer = []
        if not warnings:
            return
        message = "\n".join(warnings[:12])
        if len(warnings) > 12:
            message += f"\n... and {len(warnings) - 12} more"
        QMessageBox.warning(self, "Time-domain simulations", message)

    def _update_compare_gradient_options(self, compare_with_sim):
        combo = getattr(self, "compare_grad_combo", None)
        if combo is None:
            return

        current = combo.currentText().strip()
        options = ["X", "Y", "Z"] if compare_with_sim else ["X", "Y", "Z", "All"]

        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        if current in options:
            combo.setCurrentText(current)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _single_value_gradient_list(self, gradient):
        gradient = str(gradient).strip().upper()
        if gradient == "ALL":
            return ["GX", "GY", "GZ"]
        if gradient in {"X", "GX"}:
            return ["GX"]
        if gradient in {"Y", "GY"}:
            return ["GY"]
        if gradient in {"Z", "GZ"}:
            return ["GZ"]
        return []

    def _single_value_table_gradient_token(self, gradient_token):
        token = str(gradient_token).strip().upper()
        if token.startswith("G") and len(token) >= 2:
            return token[-1]
        return token

    def _single_value_phantom_order(self, gradient_token):
        axis = str(gradient_token).strip().upper().replace("G", "")
        if axis in {"X", "Y", "Z"}:
            return [f"-{axis}", "Center", f"+{axis}"]
        return ["-X", "Center", "+X"]

    def _load_single_value_measured_table(self, case):
        case_base = case.get("base_path") or self.base_path
        case_setup = case.get("setup") or self.setup_combo.currentText()
        case_setup_key = case.get("setup_key") or case_setup.split("_")[0]
        return load_measured_table(case_base, case_setup, case_setup_key)

    def _case_display_name(self, case, index, custom_labels=None):
        custom_labels = custom_labels or []
        if index < len(custom_labels):
            label = str(custom_labels[index]).strip()
            if label:
                return label
        case_base = case.get("base_path") or ""
        case_setup = case.get("setup") or ""
        base_tail = os.path.basename(os.path.normpath(case_base)) if case_base else ""
        parts = [p for p in [base_tail, case_setup] if p]
        return "_".join(parts) if parts else f"Case {index + 1}"

    def _build_single_value_measured_figure(self, compare_cases, gradient, measured_column, plot_type, custom_labels=None, colormap="Single-color gradient"):
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm

        gradients_to_plot = self._single_value_gradient_list(gradient)
        if not gradients_to_plot:
            raise ValueError(f"Unsupported gradient selection: {gradient}")

        spatial_axes = ["X", "Y", "Z"]
        n_rows = len(gradients_to_plot)
        is_points_mode = not str(plot_type).lower().startswith("hist")
        n_cols = 4 if is_points_mode else 3
        n_cases = len(compare_cases)

        # Build per-case color palette
        if colormap in ("Viridis", "Inferno") and n_cases > 0:
            upper = 0.70 if colormap == "Inferno" else 0.85
            cmap = cm.get_cmap(colormap.lower())
            palette_colors = [cmap(pos) for pos in np.linspace(0.0, upper, max(1, n_cases))]
        else:
            palette_colors = None

        grad_base_colors = {
            "GX": np.array([0.05, 0.15, 0.55]),
            "GY": np.array([0.55, 0.05, 0.05]),
            "GZ": np.array([0.05, 0.45, 0.05]),
        }

        fig, axes = plt.subplots(
            n_rows, n_cols,
            figsize=((22 if n_cols == 4 else 18), max(4.5, 3.8 * n_rows)),
            squeeze=False,
        )

        for grad_idx, grad_token in enumerate(gradients_to_plot):
            table_grad = self._single_value_table_gradient_token(grad_token)
            grad_base = grad_base_colors.get(grad_token, np.array([0.1, 0.1, 0.5]))
            plotted_any = False

            for ax_idx, spatial_axis in enumerate(spatial_axes):
                ax = axes[grad_idx, ax_idx]
                phantom_order = [f"-{spatial_axis}", "Center", f"+{spatial_axis}"]
                x_values = list(range(len(phantom_order)))

                for case_idx, case in enumerate(compare_cases):
                    df_meas = self._load_single_value_measured_table(case)
                    if "Grad" not in df_meas.columns:
                        raise ValueError(f"Column 'Grad' not found in measured table ({case.get('setup', '')}).")
                    if "Phantom_position" not in df_meas.columns:
                        raise ValueError(f"Column 'Phantom_position' not found in measured table ({case.get('setup', '')}).")
                    if measured_column not in df_meas.columns:
                        raise ValueError(
                            f"Column '{measured_column}' not found in measured table ({case.get('setup', '')})."
                        )

                    df_meas = df_meas.copy()
                    df_meas[measured_column] = pd.to_numeric(df_meas[measured_column], errors="coerce")
                    df_filtered = df_meas[df_meas["Grad"].astype(str).str.upper() == table_grad]

                    values = []
                    for phantom_name in phantom_order:
                        row = df_filtered[df_filtered["Phantom_position"].astype(str) == phantom_name]
                        values.append(float(row.iloc[0][measured_column]) if not row.empty else np.nan)

                    label = self._case_display_name(case, case_idx, custom_labels)

                    if palette_colors:
                        color = palette_colors[case_idx]
                    else:
                        lighten = min(0.85, 0.35 * case_idx)
                        color = tuple(np.clip(grad_base + (1.0 - grad_base) * lighten, 0.0, 1.0))

                    # Show label only in first column to avoid duplicate legend entries
                    legend_label = label if ax_idx == 0 else ""

                    if str(plot_type).lower().startswith("hist"):
                        width = 0.6 / max(1, n_cases)
                        offsets = np.linspace(-0.3 + width / 2, 0.3 - width / 2, max(1, n_cases))
                        shift = offsets[case_idx] if n_cases > 1 else 0.0
                        ax.bar(
                            np.asarray(x_values, dtype=float) + shift, values,
                            width=width, alpha=0.85, color=color, label=legend_label,
                        )
                    else:
                        ax.plot(
                            x_values, values, "o-",
                            linewidth=2.4, markersize=7, color=color, label=legend_label,
                        )

                    plotted_any = True

                ax.set_xticks(x_values)
                ax.set_xticklabels(phantom_order)
                ax.set_title(f"G{grad_token[-1]} along {spatial_axis}", fontsize=10)
                ax.set_ylabel(measured_column if ax_idx == 0 else "")
                ax.set_xlabel("Phantom position" if grad_idx == n_rows - 1 else "")
                ax.grid(True, alpha=0.35)

            # For Points mode, add a 4th subplot with one histogram-summary bar per case.
            if is_points_mode:
                ax_hist = axes[grad_idx, 3]
                case_labels = []
                mean_abs_values = []
                phantom_order_all = getattr(self, "_METRICS_PHANTOM_ORDER", ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"])

                for case_idx, case in enumerate(compare_cases):
                    df_meas = self._load_single_value_measured_table(case)
                    if "Grad" not in df_meas.columns:
                        raise ValueError(f"Column 'Grad' not found in measured table ({case.get('setup', '')}).")
                    if "Phantom_position" not in df_meas.columns:
                        raise ValueError(f"Column 'Phantom_position' not found in measured table ({case.get('setup', '')}).")
                    if measured_column not in df_meas.columns:
                        raise ValueError(
                            f"Column '{measured_column}' not found in measured table ({case.get('setup', '')})."
                        )

                    df_meas = df_meas.copy()
                    df_meas[measured_column] = pd.to_numeric(df_meas[measured_column], errors="coerce")
                    df_filtered = df_meas[df_meas["Grad"].astype(str).str.upper() == table_grad]

                    abs_vals = []
                    for phantom_name in phantom_order_all:
                        row = df_filtered[df_filtered["Phantom_position"].astype(str) == phantom_name]
                        if row.empty:
                            continue
                        val = float(row.iloc[0][measured_column])
                        if np.isfinite(val):
                            abs_vals.append(abs(val))

                    mean_abs = float(np.nanmean(abs_vals)) if len(abs_vals) > 0 else np.nan
                    mean_abs_values.append(mean_abs)
                    case_labels.append(self._case_display_name(case, case_idx, custom_labels))

                    if palette_colors:
                        color = palette_colors[case_idx]
                    else:
                        lighten = min(0.85, 0.35 * case_idx)
                        color = tuple(np.clip(grad_base + (1.0 - grad_base) * lighten, 0.0, 1.0))

                    x_pos = float(case_idx)
                    height = 0.0 if not np.isfinite(mean_abs) else mean_abs
                    ax_hist.bar(x_pos, height, width=0.62, alpha=0.85, color=color)
                    if np.isfinite(mean_abs):
                        ax_hist.text(x_pos, mean_abs, f"{mean_abs:.3g}", ha="center", va="bottom", fontsize=8)

                ax_hist.set_xticks(list(range(len(case_labels))))
                ax_hist.set_xticklabels(case_labels, rotation=20, ha="right")
                ax_hist.set_title(f"G{grad_token[-1]} histogram |v| (mean of 7)", fontsize=10)
                ax_hist.set_ylabel(f"mean(|{measured_column}|)")
                ax_hist.set_xlabel("Case" if grad_idx == n_rows - 1 else "")
                ax_hist.grid(True, axis="y", alpha=0.35)

            # Legend only in the first column of this gradient row
            if plotted_any:
                axes[grad_idx, 0].legend(fontsize=8, loc="best")

        fig.tight_layout()
        return fig

    # Fixed phantom position order for single-value metrics tables
    _METRICS_PHANTOM_ORDER = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]

    def _build_single_value_metrics_frames(self, compare_cases, gradient, measured_columns, custom_labels=None):
        """Build metric tables: returns list of (grad_token, metric_name, pd.DataFrame).

        Args:
            compare_cases: list of case dicts
            gradient: gradient string ("X"/"GX"/"All")
            measured_columns: list of metric column names to build tables for
            custom_labels: optional list of custom case labels
        """
        custom_labels = custom_labels or []
        if isinstance(measured_columns, str):
            measured_columns = [measured_columns]
        gradients_to_plot = self._single_value_gradient_list(gradient)
        if not gradients_to_plot:
            raise ValueError(f"Unsupported gradient selection: {gradient}")

        phantom_order = self._METRICS_PHANTOM_ORDER
        frames = []

        for grad_token in gradients_to_plot:
            table_grad = self._single_value_table_gradient_token(grad_token)

            # Load and filter each case's dataframe once per gradient
            case_dfs = []
            for case_idx, case in enumerate(compare_cases):
                df_meas = self._load_single_value_measured_table(case)
                if "Grad" not in df_meas.columns or "Phantom_position" not in df_meas.columns:
                    raise ValueError(f"Measured table for {case.get('setup', '')} is missing Grad/Phantom_position columns.")
                df_filtered = df_meas[df_meas["Grad"].astype(str).str.upper() == table_grad].copy()
                case_label = self._case_display_name(case, case_idx, custom_labels)
                case_dfs.append((case_label, df_filtered))

            for metric in measured_columns:
                rows = {"Phantom_position": phantom_order}
                for case_label, df_filtered in case_dfs:
                    df_col = df_filtered.copy()
                    if metric in df_col.columns:
                        df_col[metric] = pd.to_numeric(df_col[metric], errors="coerce")
                    values = []
                    for phantom_name in phantom_order:
                        if metric not in df_col.columns:
                            values.append(np.nan)
                        else:
                            row = df_col[df_col["Phantom_position"].astype(str) == phantom_name]
                            values.append(float(row.iloc[0][metric]) if not row.empty else np.nan)
                    rows[case_label] = values
                frames.append((grad_token, metric, pd.DataFrame(rows)))

        return frames

    def _load_mat_curve_metrics_module(self):
        module = getattr(self, "_mat_curve_metrics_module", None)
        if module is not None:
            return module

        module_path = os.path.join(CURRENT_DIR, "Metrics", "mat_curve_metrics.py")
        if not os.path.exists(module_path):
            raise FileNotFoundError(f"Metrics helper not found: {module_path}")

        spec = importlib.util.spec_from_file_location("mat_curve_metrics", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load Metrics/mat_curve_metrics.py")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._mat_curve_metrics_module = module
        return module

    def _ask_metric_selection(self, measured_columns):
        dlg = QDialog(self)
        dlg.setWindowTitle("Select metrics")
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Choose metrics to extract:"))
        checks = []
        for name in self._build_metric_options(measured_columns):
            cb = QCheckBox(name)
            cb.setChecked(False)
            checks.append((name, cb))
            layout.addWidget(cb)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return None

        selected = [name for name, cb in checks if cb.isChecked()]
        return selected

    def _ask_b_integrated_options(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("B_integrated options")
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Mask times (ms, comma-separated):"))
        mask_input = QLineEdit()
        mask_input.setPlaceholderText("Example: 1, 3, 5, 10")
        mask_input.setText("1, 3, 5, 10")
        layout.addWidget(mask_input)

        include_default_masks = QCheckBox("Include default masks (1, 3, 5, 10 ms)")
        include_default_masks.setChecked(True)
        layout.addWidget(include_default_masks)

        curve_combo = QComboBox()
        curve_combo.addItems(["Raw (trapz)", "Fitted", "Prefiltered", "Exponential"])
        layout.addWidget(QLabel("Integrated curve"))
        layout.addWidget(curve_combo)

        pf_cutoff = QDoubleSpinBox()
        pf_cutoff.setDecimals(3)
        pf_cutoff.setRange(0.01, 0.49)
        pf_cutoff.setSingleStep(0.01)
        pf_cutoff.setValue(0.08)
        pf_order = QSpinBox()
        pf_order.setRange(1, 12)
        pf_order.setValue(4)
        layout.addWidget(QLabel("Prefilter cutoff (Wn)"))
        layout.addWidget(pf_cutoff)
        layout.addWidget(QLabel("Prefilter order"))
        layout.addWidget(pf_order)

        exp_order = QSpinBox()
        exp_order.setRange(1, 8)
        exp_order.setValue(2)
        layout.addWidget(QLabel("Exponential fit order"))
        layout.addWidget(exp_order)

        def _update_fields():
            src = curve_combo.currentText()
            use_pf = (src == "Prefiltered")
            use_exp = (src == "Exponential")
            pf_cutoff.setEnabled(use_pf)
            pf_order.setEnabled(use_pf)
            exp_order.setEnabled(use_exp)

        curve_combo.currentIndexChanged.connect(_update_fields)
        _update_fields()

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return None

        masks = []
        if include_default_masks.isChecked():
            masks.extend([1.0, 3.0, 5.0, 10.0])

        raw_text = mask_input.text().strip()
        if raw_text:
            for chunk in raw_text.split(','):
                token = chunk.strip().lower().replace("ms", "")
                if not token:
                    continue
                try:
                    masks.append(float(token))
                except Exception:
                    pass

        # Keep order while removing duplicates.
        deduped = []
        seen = set()
        for m in masks:
            key = round(float(m), 8)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(float(m))
        masks = deduped if deduped else [1.0, 3.0, 5.0, 10.0]

        curve_map = {
            "Raw (trapz)": "raw",
            "Fitted": "fitted",
            "Prefiltered": "prefiltered",
            "Exponential": "exponential fit",
        }
        selected_curve = curve_map.get(curve_combo.currentText(), "raw")

        return {
            "masks": masks,
            "method": "trapz",
            "source": selected_curve,
            "integrated_curve": curve_combo.currentText(),
            "prefilter_cutoff": float(pf_cutoff.value()),
            "prefilter_order": int(pf_order.value()),
            "exp_order": int(exp_order.value()),
        }

    def _ask_exp_fit_options(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Exp_fit options")
        layout = QVBoxLayout(dlg)

        mode_combo = QComboBox()
        mode_combo.addItems(["fixed order", "auto by RMSE% threshold"])
        layout.addWidget(QLabel("Order mode"))
        layout.addWidget(mode_combo)

        fixed_order = QSpinBox()
        fixed_order.setRange(1, 8)
        fixed_order.setValue(2)
        layout.addWidget(QLabel("Fixed order"))
        layout.addWidget(fixed_order)

        target_rmse = QDoubleSpinBox()
        target_rmse.setRange(0.01, 100.0)
        target_rmse.setDecimals(2)
        target_rmse.setValue(5.0)
        layout.addWidget(QLabel("Target RMSE%"))
        layout.addWidget(target_rmse)

        mask_combo = QComboBox()
        mask_combo.addItems(["All", "1ms", "5ms", "10ms"])
        layout.addWidget(QLabel("Integral window for fit value"))
        layout.addWidget(mask_combo)

        method_combo = QComboBox()
        method_combo.addItems(["trapz", "simpson"])
        layout.addWidget(QLabel("Integration method"))
        layout.addWidget(method_combo)

        def _update_mode():
            is_fixed = (mode_combo.currentText() == "fixed order")
            fixed_order.setEnabled(is_fixed)
            target_rmse.setEnabled(not is_fixed)

        mode_combo.currentIndexChanged.connect(_update_mode)
        _update_mode()

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return None

        return {
            "mode": mode_combo.currentText(),
            "fixed_order": int(fixed_order.value()),
            "target_rmse_percent": float(target_rmse.value()),
            "mask": mask_combo.currentText(),
            "method": method_combo.currentText(),
        }

    def _table_gradient_axis(self, grad_token):
        token = str(grad_token).upper().strip()
        if token.startswith("G") and len(token) > 1:
            return token[-1].lower()
        return token[-1].lower() if token else ""

    def _mask_to_time_ms(self, mask_name, x_rel):
        if mask_name == "All":
            if np.size(x_rel) == 0:
                return 0.0
            return float(x_rel[-1])
        if isinstance(mask_name, (int, float, np.integer, np.floating)):
            return float(mask_name)
        if isinstance(mask_name, str):
            s = mask_name.strip().lower().replace("ms", "")
            if s == "all":
                return float(x_rel[-1]) if np.size(x_rel) else 0.0
            try:
                return float(s)
            except Exception:
                pass
        return float(x_rel[-1]) if np.size(x_rel) else 0.0

    def _collect_case_mat_files(self, case, phantom_name):
        folder_path = self._resolve_case_folder_path(case["base_path"], case["setup"], phantom_name)
        if not os.path.isdir(folder_path):
            return []
        return [
            os.path.join(folder_path, f)
            for f in sorted(os.listdir(folder_path))
            if f.lower().endswith(".mat") and not f.startswith("FID")
        ]

    def _compute_curve_metric_value(self, case, grad_token, phantom_name, mode, options):
        mm = self._load_mat_curve_metrics_module()
        grad_axis = self._table_gradient_axis(grad_token)
        mat_files = self._collect_case_mat_files(case, phantom_name)
        if not mat_files:
            return np.nan, np.nan, ""

        vals = []
        rmses = []
        params = []

        for file_path in mat_files:
            try:
                Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = sequenceAnalysis(file_path)
                if str(g_axis).strip().lower() != grad_axis:
                    continue

                Be = np.asarray(Be, dtype=float)
                BeddyFitted = np.asarray(BeddyFitted, dtype=float)
                tiempo = np.asarray(tiempo, dtype=float)
                nDelays = int(nDelays)
                deadTime = float(deadTime)
                acqTime = float(acqTime)

                source_name = options.get("source", "raw")
                if mode == "b_integrated":
                    if source_name == "fitted":
                        src_curve = BeddyFitted
                    elif source_name == "prefiltered":
                        data_for_pf = {
                            "fidsmap": fidsmap,
                            "nDelays": nDelays,
                            "nReadouts": int(nReadouts),
                            "deadTime": deadTime,
                            "acqTime": acqTime,
                        }
                        src_curve = np.asarray(
                            mm.compute_prefilter_curve(
                                data_for_pf,
                                int(options.get("prefilter_order", 4)),
                                float(options.get("prefilter_cutoff", 0.08)),
                            ),
                            dtype=float,
                        )
                    elif source_name == "exponential fit":
                        recon_raw = mm.reconstruct_continuous_series(Be, tiempo, deadTime, acqTime)
                        fit_res = mm.fit_exponentials_orders(
                            recon_raw["x_rel"],
                            recon_raw["y"],
                            [int(options.get("exp_order", 2))],
                        )
                        fit_ok = [f for f in fit_res.get("fits", []) if f.get("success")]
                        if not fit_ok:
                            continue
                        chosen = fit_ok[0]
                        t_end = self._mask_to_time_ms(options.get("mask", "All"), recon_raw["x_rel"])
                        val = float(mm.integrate_until_time(
                            np.asarray(chosen["x"], dtype=float),
                            np.asarray(chosen["y_fit"], dtype=float),
                            t_end,
                            options.get("method", "trapz"),
                        ))
                        rmse_pct = chosen.get("rmse_percent", np.nan)
                        vals.append(val)
                        rmses.append(float(rmse_pct) if np.isfinite(rmse_pct) else np.nan)
                        coeffs = chosen.get("coefficients", {})
                        params.append(", ".join([f"{k}={v:.4g}" for k, v in coeffs.items()]))
                        continue
                    else:
                        src_curve = Be

                    mask_opt = options.get("mask", "All")
                    windows = []
                    if mask_opt != "All":
                        try:
                            windows = [float(mask_opt)]
                        except Exception:
                            windows = []
                    integ = mm.compute_integral_metrics_reconstructed(
                        src_curve,
                        tiempo,
                        deadTime,
                        acqTime,
                        windows,
                        options.get("method", "trapz"),
                    )
                    if mask_opt == "All":
                        val = float(integ.get("all_cumulative", np.nan))
                    else:
                        key = float(mask_opt)
                        val = float(integ.get("masked_cumulative", {}).get(key, np.nan))

                    recon_ref = mm.reconstruct_continuous_series(Be, tiempo, deadTime, acqTime)
                    recon_cmp = mm.reconstruct_continuous_series(src_curve, tiempo, deadTime, acqTime)
                    t_end = self._mask_to_time_ms(mask_opt, recon_ref["x_rel"])
                    rmse = mm.rmse_until_time(
                        np.asarray(recon_ref["x_rel"], dtype=float),
                        np.asarray(recon_ref["y"], dtype=float),
                        np.asarray(recon_cmp["x_rel"], dtype=float),
                        np.asarray(recon_cmp["y"], dtype=float),
                        t_end,
                    )
                    y_ref = np.asarray(recon_ref["y"], dtype=float)
                    if np.size(y_ref) > 0 and np.any(np.isfinite(y_ref)):
                        p2p = float(np.nanmax(y_ref) - np.nanmin(y_ref))
                    else:
                        p2p = np.nan
                    rmse_pct = float(100.0 * rmse / p2p) if np.isfinite(rmse) and np.isfinite(p2p) and p2p > 0 else np.nan
                    vals.append(val)
                    rmses.append(rmse_pct)
                    params.append("")
                else:
                    recon_raw = mm.reconstruct_continuous_series(Be, tiempo, deadTime, acqTime)
                    if options.get("mode") == "auto by RMSE% threshold":
                        mm.TARGET_RMSE_PERCENT = float(options.get("target_rmse_percent", 5.0))
                        fit_res = mm.fit_exponentials_orders(recon_raw["x_rel"], recon_raw["y"], list(range(1, 9)))
                        target_order = fit_res.get("target_order", None)
                        fit_ok = [f for f in fit_res.get("fits", []) if f.get("success")]
                        if not fit_ok:
                            continue
                        if target_order is None:
                            chosen = min(fit_ok, key=lambda d: d.get("order", 99))
                        else:
                            chosen = next((f for f in fit_ok if int(f.get("order", -1)) == int(target_order)), fit_ok[0])
                    else:
                        fit_res = mm.fit_exponentials_orders(
                            recon_raw["x_rel"],
                            recon_raw["y"],
                            [int(options.get("fixed_order", 2))],
                        )
                        fit_ok = [f for f in fit_res.get("fits", []) if f.get("success")]
                        if not fit_ok:
                            continue
                        chosen = fit_ok[0]

                    t_end = self._mask_to_time_ms(options.get("mask", "All"), np.asarray(chosen["x"], dtype=float))
                    val = float(mm.integrate_until_time(
                        np.asarray(chosen["x"], dtype=float),
                        np.asarray(chosen["y_fit"], dtype=float),
                        t_end,
                        options.get("method", "trapz"),
                    ))
                    vals.append(val)
                    rmse_pct = chosen.get("rmse_percent", np.nan)
                    rmses.append(float(rmse_pct) if np.isfinite(rmse_pct) else np.nan)
                    coeffs = chosen.get("coefficients", {})
                    params.append(", ".join([f"{k}={v:.4g}" for k, v in coeffs.items()]))
            except Exception:
                continue

        if len(vals) == 0:
            return np.nan, np.nan, ""

        value = float(np.nanmean(np.asarray(vals, dtype=float)))
        rmse_value = float(np.nanmean(np.asarray(rmses, dtype=float))) if len(rmses) else np.nan
        params_text = params[-1] if params else ""
        return value, rmse_value, params_text

    def _build_curve_metric_frames(self, compare_cases, gradient, custom_labels, mode, options):
        gradients_to_plot = self._single_value_gradient_list(gradient)
        phantom_order = self._METRICS_PHANTOM_ORDER
        frames = []

        for grad_token in gradients_to_plot:
            rows = {"Phantom_position": phantom_order}
            for case_idx, case in enumerate(compare_cases):
                case_label = self._case_display_name(case, case_idx, custom_labels)
                values = []
                rmses = []
                params = []
                for phantom_name in phantom_order:
                    val, rmse_pct, param_txt = self._compute_curve_metric_value(
                        case=case,
                        grad_token=grad_token,
                        phantom_name=phantom_name,
                        mode=mode,
                        options=options,
                    )
                    values.append(val)
                    rmses.append(rmse_pct)
                    params.append(param_txt)
                rows[case_label] = values
                rows[f"{case_label}_RMSE%"] = rmses
                if mode == "exp_fit":
                    rows[f"{case_label}_Params"] = params

            metric_name = "B_integrated"
            if mode == "b_integrated":
                mask_value = options.get('mask', 'All')
                if isinstance(mask_value, (int, float, np.integer, np.floating)):
                    mask_tag = f"{float(mask_value):g}ms"
                else:
                    mask_tag = str(mask_value)
                metric_name = f"B_integrated_{options.get('source', 'raw').replace(' ', '_')}_{mask_tag}_{options.get('method', 'trapz')}"
            elif mode == "exp_fit":
                if options.get("mode") == "fixed order":
                    metric_name = f"Exp_fit_order_{options.get('fixed_order', 2)}_{options.get('mask', 'All')}"
                else:
                    metric_name = f"Exp_fit_auto_lt_{options.get('target_rmse_percent', 5.0):.2f}pct_{options.get('mask', 'All')}"

            frames.append((grad_token, metric_name, pd.DataFrame(rows)))

        return frames

    def _frames_to_continuous_table(self, frames):
        if not frames:
            return pd.DataFrame()
        all_columns = ["Gradient", "Metric", "Phantom_position"]
        for _, _, df in frames:
            for col in df.columns:
                if col not in all_columns:
                    all_columns.append(col)

        blocks = []
        for grad_token, metric_name, df in frames:
            block = df.copy()
            block.insert(0, "Metric", metric_name)
            block.insert(0, "Gradient", grad_token)
            for col in all_columns:
                if col not in block.columns:
                    block[col] = np.nan
            blocks.append(block[all_columns])
        return pd.concat(blocks, ignore_index=True)

    def _show_single_value_metrics_dialog_continuous(self, continuous_df, title):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(1200, 780)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Continuous table format for direct copy/paste to Excel."))

        table = CopyableTableWidget()
        table.setRowCount(continuous_df.shape[0])
        table.setColumnCount(continuous_df.shape[1])
        table.setHorizontalHeaderLabels([str(c) for c in continuous_df.columns])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        for r in range(continuous_df.shape[0]):
            for c in range(continuous_df.shape[1]):
                value = continuous_df.iat[r, c]
                if isinstance(value, (int, float, np.integer, np.floating)):
                    text = "" if not np.isfinite(value) else f"{value:.6g}"
                    align = Qt.AlignRight | Qt.AlignVCenter
                else:
                    text = "" if (isinstance(value, float) and np.isnan(value)) else str(value)
                    align = Qt.AlignCenter if c <= 2 else Qt.AlignLeft | Qt.AlignVCenter
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                table.setItem(r, c, item)

        table.resizeColumnsToContents()
        layout.addWidget(table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        self.current_analysis_table_dialog = dlg
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        return dlg

    def _show_single_value_metrics_dialog(self, frames, title):
        """Display metric tables grouped by gradient, one sub-table per metric.

        frames: list of (grad_token, metric_name, pd.DataFrame)
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(980, 780)
        outer_layout = QVBoxLayout(dlg)

        hint = QLabel("Select cells and press Ctrl+C to copy to Excel.")
        outer_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        current_grad = None
        for item in frames:
            grad_token, metric_name, df = item

            if grad_token != current_grad:
                current_grad = grad_token
                grad_label = QLabel(f"<b>G{grad_token[-1]}</b>")
                grad_label.setStyleSheet("font-size: 13pt; margin-top: 10px;")
                layout.addWidget(grad_label)

            metric_label = QLabel(f"  {metric_name}")
            metric_label.setStyleSheet("font-size: 10pt; color: #444; margin-left: 12px;")
            layout.addWidget(metric_label)

            table = CopyableTableWidget()
            table.setRowCount(df.shape[0])
            table.setColumnCount(df.shape[1])
            table.setHorizontalHeaderLabels([str(c) for c in df.columns])
            table.verticalHeader().setVisible(False)
            table.setAlternatingRowColors(True)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.horizontalHeader().setStretchLastSection(False)

            for r in range(df.shape[0]):
                for c in range(df.shape[1]):
                    value = df.iat[r, c]
                    if c == 0:
                        text = str(value)
                    else:
                        text = "" if (isinstance(value, float) and np.isnan(value)) else f"{value:.6g}" if isinstance(value, (int, float, np.floating, np.integer)) else str(value)
                    item_widget = QTableWidgetItem(text)
                    if c == 0:
                        item_widget.setTextAlignment(Qt.AlignCenter)
                    else:
                        item_widget.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(r, c, item_widget)

            table.resizeColumnsToContents()
            # Cap the widget height to avoid giant tables
            row_h = table.rowHeight(0) if df.shape[0] > 0 else 22
            header_h = table.horizontalHeader().height()
            table.setMaximumHeight(header_h + row_h * df.shape[0] + 4)

            layout.addWidget(table)

        layout.addStretch(1)
        container.setLayout(layout)
        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        outer_layout.addWidget(close_btn)

        self.current_analysis_table_dialog = dlg
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        return dlg

    def refresh_simulation_cases(self):
        self.sim_case_combo.clear()

        sim_root = self.sim_root_path
        case_names = set()

        for case_name, _ in self._iter_simulation_case_dirs(sim_root):
            case_names.add(case_name)

        if not case_names:
            self.sim_case_combo.addItem("No simulation folders found.")
            return

        self.sim_case_combo.addItems(sorted(case_names))

    def _iter_simulation_case_dirs(self, sim_root):
        gradients = ["GX", "GY", "GZ"]
        preferred_containers = ["AllSimulations", "MeasuredCases"]

        for grad in gradients:
            grad_dir = os.path.join(sim_root, grad)
            if not os.path.isdir(grad_dir):
                continue

            container_names = []
            for container in preferred_containers:
                container_dir = os.path.join(grad_dir, container)
                if os.path.isdir(container_dir):
                    container_names.append(container)

            if not container_names:
                container_names = [""]

            for container in container_names:
                parent_dir = os.path.join(grad_dir, container) if container else grad_dir
                for name in os.listdir(parent_dir):
                    full = os.path.join(parent_dir, name)
                    if os.path.isdir(full):
                        yield name, full

    def _resolve_simulation_case_dir(self, sim_root, gradient, sim_case):
        grad_dir = os.path.join(sim_root, gradient)
        candidates = [
            os.path.join(grad_dir, "AllSimulations", sim_case),
            os.path.join(grad_dir, "MeasuredCases", sim_case),
            os.path.join(grad_dir, sim_case),
        ]

        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate

        return candidates[0]

    def _load_simulation_numeric_data(self, file_path):
        try:
            arr = np.genfromtxt(file_path, comments='%', invalid_raise=False)
        except Exception:
            arr = np.genfromtxt(file_path, comments='#', invalid_raise=False)

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

    def run_simulation_plot(self):
        sim_case = self.sim_case_combo.currentText().strip()
        if not sim_case or sim_case == "No simulation folders found.":
            QMessageBox.warning(self, "Plot Simulations", "No simulation folders found.")
            return

        sim_plot_type = self.sim_plot_type_combo.currentText().strip()
        file_plot_type = sim_plot_type
        plot_units = "mT" if sim_plot_type == "B0" else "uT"
        selected_gradient = self.sim_gradient_combo.currentText().strip()

        sim_root = self.sim_root_path
        gradients = ["GX", "GY", "GZ"]
        plot_axis_source = {
            "X": "X",
            "Y": "Y",
            "Z": "Z",
        }
        color_map = {
            "GX": "red",
            "GY": "green",
            "GZ": "blue"
        }

        missing_items = []
        import matplotlib.pyplot as plt

        def _apply_isometric_fov_view(ax):
            ax.set_box_aspect((1, 1, 1))
            try:
                ax.set_proj_type('ortho')
            except Exception:
                pass
            ax.view_init(elev=35.264, azim=-45)

        def _render_export_image(ax, image_path, title):
            if not os.path.isfile(image_path):
                missing_items.append(os.path.relpath(image_path, sim_root))
                ax.set_title(f"{title} (missing)")
                ax.axis('off')
                return

            try:
                img = plt.imread(image_path)
                ax.imshow(img)
                ax.set_title(title)
                ax.axis('off')
            except Exception:
                missing_items.append(f"{os.path.relpath(image_path, sim_root)} (invalid)")
                ax.set_title(f"{title} (invalid)")
                ax.axis('off')

        if selected_gradient in gradients:
            fig = plt.figure(figsize=(20, 9.0))
            ax_x = fig.add_subplot(2, 4, 1)
            ax_y = fig.add_subplot(2, 4, 2)
            ax_z = fig.add_subplot(2, 4, 3)
            ax_fov = fig.add_subplot(2, 4, 4, projection='3d')
            ax_xy = fig.add_subplot(2, 4, 5)
            ax_yz = fig.add_subplot(2, 4, 6)
            ax_xz = fig.add_subplot(2, 4, 7)
            ax_view3d = fig.add_subplot(2, 4, 8)

            grad = selected_gradient
            color = color_map[grad]
            base_dir = self._resolve_simulation_case_dir(sim_root, grad, sim_case)

            line_specs = [
                ("X", ax_x),
                ("Y", ax_y),
                ("Z", ax_z),
            ]

            for axis_name, axis_obj in line_specs:
                source_axis = plot_axis_source[axis_name]
                fpath = os.path.join(base_dir, f"{file_plot_type}_Line_{source_axis}.txt")
                if not os.path.isfile(fpath):
                    missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_Line_{source_axis}.txt")
                    axis_obj.set_title(f"Line {axis_name} (missing)")
                    axis_obj.grid(True, axis='y', alpha=0.35)
                    continue

                data = self._load_simulation_numeric_data(fpath)
                if data is None or data.shape[1] < 2:
                    missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_Line_{source_axis}.txt (invalid)")
                    axis_obj.set_title(f"Line {axis_name} (invalid)")
                    axis_obj.grid(True, axis='y', alpha=0.35)
                    continue

                xvals = data[:, 0]
                yvals = data[:, -1]
                axis_obj.plot(xvals, yvals, '-', color=color, linewidth=1.5)
                axis_obj.set_title(f"Line {axis_name}")
                axis_obj.set_xlabel(f"{axis_name} (m)")
                axis_obj.set_ylabel(f"{sim_plot_type} ({plot_units})")
                axis_obj.set_xticks([-0.1, -0.05, 0.0, 0.05, 0.1])
                axis_obj.set_xlim(-0.105, 0.105)
                axis_obj.grid(True, axis='y', alpha=0.35)

            fov_path = os.path.join(base_dir, f"{file_plot_type}_FOV.txt")
            if not os.path.isfile(fov_path):
                missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_FOV.txt")
                ax_fov.set_title("FOV (missing)")
            else:
                fov_data = self._load_simulation_numeric_data(fov_path)
                if fov_data is None or fov_data.shape[1] < 3:
                    missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_FOV.txt (invalid)")
                    ax_fov.set_title("FOV (invalid)")
                else:
                    xvals = fov_data[:, 0]
                    yvals = fov_data[:, 2]
                    zvals = fov_data[:, 1]
                    vvals = fov_data[:, -1]
                    scat = ax_fov.scatter(xvals, yvals, zvals,
                                          c=vvals, cmap='rainbow', s=6, alpha=0.8)
                    ax_fov.set_title("FOV")

                    cbar = fig.colorbar(scat, ax=ax_fov, fraction=0.03, pad=0.16)
                    cbar.set_label(f"{sim_plot_type} ({plot_units})")

            ax_fov.set_xlabel('X')
            ax_fov.set_ylabel('Z')
            ax_fov.set_zlabel('Y', labelpad=2)
            _apply_isometric_fov_view(ax_fov)

            view3d_name = 'B0_3DView.png' if sim_plot_type == 'B0' else 'Beddy_3DView.png'
            view3d_title = 'B0_3DView' if sim_plot_type == 'B0' else 'Beddy_3DView'

            export_images = [
                (ax_xy, os.path.join(base_dir, 'B_universe_XY.png'), 'B_universe_XY'),
                (ax_yz, os.path.join(base_dir, 'B_universe_YZ.png'), 'B_universe_YZ'),
                (ax_xz, os.path.join(base_dir, 'B_universe_XZ.png'), 'B_universe_XZ'),
                (ax_view3d, os.path.join(base_dir, view3d_name), view3d_title),
            ]
            for ax_img, image_path, title in export_images:
                _render_export_image(ax_img, image_path, title)

            fig.suptitle(f"{sim_plot_type} - {sim_case} - {selected_gradient}")
            fig.tight_layout()
            self.image_label.setMinimumHeight(700)

        else:
            fig = plt.figure(figsize=(18, 11))
            top_axes = {
                "X": fig.add_subplot(3, 3, 1),
                "Y": fig.add_subplot(3, 3, 2),
                "Z": fig.add_subplot(3, 3, 3)
            }
            fov_axes = {
                "GX": fig.add_subplot(3, 3, 4, projection='3d'),
                "GY": fig.add_subplot(3, 3, 5, projection='3d'),
                "GZ": fig.add_subplot(3, 3, 6, projection='3d')
            }
            value_axes = {
                "GX": fig.add_subplot(3, 3, 7),
                "GY": fig.add_subplot(3, 3, 8),
                "GZ": fig.add_subplot(3, 3, 9)
            }

            for axis_name, axis_obj in top_axes.items():
                for grad in gradients:
                    source_axis = plot_axis_source[axis_name]
                    base_dir = self._resolve_simulation_case_dir(sim_root, grad, sim_case)
                    fpath = os.path.join(base_dir, f"{file_plot_type}_Line_{source_axis}.txt")
                    if not os.path.isfile(fpath):
                        missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_Line_{source_axis}.txt")
                        continue

                    data = self._load_simulation_numeric_data(fpath)
                    if data is None or data.shape[1] < 2:
                        missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_Line_{source_axis}.txt (invalid)")
                        continue

                    xvals = data[:, 0]
                    yvals = data[:, -1]
                    axis_obj.plot(xvals, yvals, '-', color=color_map[grad], linewidth=1.4, label=grad)

                axis_obj.set_title(f"Line {axis_name}")
                axis_obj.set_xlabel(f"{axis_name} (m)")
                axis_obj.set_ylabel(f"{sim_plot_type} ({plot_units})")
                axis_obj.set_xticks([-0.1, -0.05, 0.0, 0.05, 0.1])
                axis_obj.set_xlim(-0.105, 0.105)
                axis_obj.grid(True, axis='y', alpha=0.35)
                handles, labels = axis_obj.get_legend_handles_labels()
                if labels:
                    unique = dict(zip(labels, handles))
                    axis_obj.legend(unique.values(), unique.keys(), fontsize=9)

            for grad in gradients:
                ax_fov = fov_axes[grad]
                ax_val = value_axes[grad]
                base_dir = self._resolve_simulation_case_dir(sim_root, grad, sim_case)
                fov_path = os.path.join(base_dir, f"{file_plot_type}_FOV.txt")
                if not os.path.isfile(fov_path):
                    missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_FOV.txt")
                    ax_fov.set_title(f"FOV {grad} (missing)")
                    ax_val.set_title(f"Values {grad} (missing)")
                    ax_val.grid(True)
                    continue

                fov_data = self._load_simulation_numeric_data(fov_path)
                if fov_data is None or fov_data.shape[1] < 3:
                    missing_items.append(f"{grad}/{sim_case}/{file_plot_type}_FOV.txt (invalid)")
                    ax_fov.set_title(f"FOV {grad} (invalid)")
                    ax_val.set_title(f"Values {grad} (invalid)")
                    ax_val.grid(True)
                    continue

                xvals = fov_data[:, 0]
                yvals = fov_data[:, 2]
                zvals = fov_data[:, 1]
                vvals = fov_data[:, -1]

                scat = ax_fov.scatter(xvals, yvals, zvals,
                                      c=vvals, cmap='rainbow', s=6, alpha=0.8, label=grad)
                ax_fov.set_title(f"FOV {grad}")
                ax_fov.legend(loc='best', fontsize=8)
                ax_fov.set_xlabel('X')
                ax_fov.set_ylabel('Z')
                ax_fov.set_zlabel('Y', labelpad=2)
                _apply_isometric_fov_view(ax_fov)

                cbar = fig.colorbar(scat, ax=ax_fov, fraction=0.03, pad=0.16)
                cbar.set_label(f"{sim_plot_type} ({plot_units})")

                ax_val.plot(np.arange(len(vvals)), vvals, '-', color=color_map[grad], linewidth=1.0)
                ax_val.set_title(f"Values {grad} (last col)")
                ax_val.set_xlabel("Point")
                ax_val.set_ylabel(f"{sim_plot_type} ({plot_units})")
                ax_val.grid(True)

            fig.suptitle(f"{sim_plot_type} - {sim_case} - All gradients")
            fig.tight_layout()
            self.image_label.setMinimumHeight(650)

        try:
            import tempfile
            tmp_file = os.path.join(tempfile.gettempdir(), "simulations_plot.png")
            self._maybe_compact_dimensions(fig)
            self._maybe_customize_legends(fig)
            self._maybe_customize_fonts(fig)
            fig.savefig(tmp_file, dpi=200, bbox_inches='tight')
            pix = QPixmap(tmp_file)
            self.image_label.setPixmap(pix)
            self.current_analysis_figure = fig
            self.current_analysis_image_path = None
            self.current_analysis_filename = f"Simulations_{sim_plot_type}_{sim_case}_{selected_gradient}"
        except Exception as e:
            QMessageBox.critical(self, "Plot Simulations", f"Failed to render simulation plot:\n{e}")
            try:
                plt.close(fig)
            except Exception:
                pass
            return

        if missing_items:
            unique_missing = sorted(set(missing_items))
            QMessageBox.warning(
                self,
                "Plot Simulations",
                "Some files were missing or invalid and were skipped:\n\n" + "\n".join(unique_missing)
            )

    def compare_simulation_metrics(self):
        """Compare simulation metrics from AllSimulations/Simulations_extracted_data.txt."""
        try:
            import matplotlib.pyplot as plt
            import tempfile

            def _read_summary_table(summary_path):
                with open(summary_path, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
                if not lines:
                    return None, None

                header = [tok.strip().strip('"') for tok in re.split(r"\t+", lines[0]) if tok.strip()]
                if len(header) < 2:
                    return None, None

                metrics = []
                data = []
                for line in lines[1:]:
                    parts = [tok.strip().strip('"') for tok in re.split(r"\t+", line)]
                    if len(parts) < 2:
                        continue
                    metric_name = parts[0]
                    row = []
                    for v in parts[1:len(header)]:
                        try:
                            row.append(float(str(v).replace(",", ".")))
                        except Exception:
                            row.append(np.nan)
                    if not row:
                        continue
                    metrics.append(metric_name)
                    data.append(row)

                if not metrics:
                    return None, None

                df = pd.DataFrame(data, index=metrics, columns=header[1:])
                return df, header[1:]

            selected_gradient = self.sim_gradient_combo.currentText().strip()
            gradients = ["GX", "GY", "GZ"] if selected_gradient == "All" else [selected_gradient]

            summaries = {}
            for grad in gradients:
                summary_path = os.path.join(
                    self.sim_root_path,
                    grad,
                    "AllSimulations",
                    "Simulations_extracted_data.txt",
                )
                if not os.path.isfile(summary_path):
                    continue
                df, _ = _read_summary_table(summary_path)
                if df is not None and not df.empty:
                    summaries[grad] = (df, summary_path)

            if not summaries:
                QMessageBox.warning(
                    self,
                    "Compare metrics",
                    "No Simulations_extracted_data.txt found in AllSimulations for the selected gradient(s).",
                )
                return

            # Build available simulated case list from loaded summaries.
            available_cases = []
            seen_cases = set()
            for grad in summaries:
                df, _src = summaries[grad]
                for case_name in df.columns:
                    case_name = str(case_name).strip()
                    if not case_name:
                        continue
                    low = case_name.lower()
                    if low not in seen_cases:
                        seen_cases.add(low)
                        available_cases.append(case_name)

            if not available_cases:
                QMessageBox.warning(self, "Compare metrics", "No simulated cases found in AllSimulations summary.")
                return

            # Let user choose simulated cases (multi-select), like stable behavior.
            case_dialog = QDialog(self)
            case_dialog.setWindowTitle("Compare metrics - Select simulated cases")
            dlg_layout = QVBoxLayout(case_dialog)
            dlg_layout.addWidget(QLabel("Select one or more simulated cases (AllSimulations):"))

            case_list = QListWidget()
            case_list.setSelectionMode(QListWidget.MultiSelection)
            case_list.addItems(sorted(available_cases, key=lambda x: x.lower()))
            case_list.setMinimumWidth(420)
            case_list.setMinimumHeight(280)
            dlg_layout.addWidget(case_list)

            # Preserve the exact order in which the user selects cases.
            selection_order = []
            selected_now = set()

            def _on_case_selection_changed():
                nonlocal selected_now, selection_order
                current = set()
                for i in range(case_list.count()):
                    item = case_list.item(i)
                    if item.isSelected():
                        current.add(item.text())

                newly_selected = [name for name in current if name not in selected_now]
                newly_deselected = [name for name in selected_now if name not in current]

                for name in newly_selected:
                    selection_order.append(name)
                if newly_deselected:
                    selection_order = [name for name in selection_order if name not in newly_deselected]

                selected_now = current

            case_list.itemSelectionChanged.connect(_on_case_selection_changed)

            btn_row = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Cancel")
            btn_row.addStretch()
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(cancel_btn)
            dlg_layout.addLayout(btn_row)

            ok_btn.clicked.connect(case_dialog.accept)
            cancel_btn.clicked.connect(case_dialog.reject)

            if case_dialog.exec_() != QDialog.Accepted:
                return

            selected_cases = [name for name in selection_order if name in {it.text() for it in case_list.selectedItems()}]
            if not selected_cases:
                selected_cases = [item.text() for item in case_list.selectedItems()]
            if not selected_cases:
                QMessageBox.warning(self, "Compare metrics", "Select at least one simulated case.")
                return

            first_grad = next(iter(summaries.keys()))
            metric_names = list(summaries[first_grad][0].index)
            if not metric_names:
                QMessageBox.warning(self, "Compare metrics", "No metrics found in summary table.")
                return

            default_idx = 0
            for i, m in enumerate(metric_names):
                if "Beddy_average_FOV" in m:
                    default_idx = i
                    break

            metric_name, ok = QInputDialog.getItem(
                self,
                "Compare metrics",
                "Metric:",
                metric_names,
                default_idx,
                False,
            )
            if not ok:
                return

            colormap_choice, ok = QInputDialog.getItem(
                self,
                "Compare metrics",
                "Colormap:",
                ["Single color", "Viridis", "Inferno"],
                0,
                False,
            )
            if not ok:
                return

            case_color_by_norm = {}
            if colormap_choice in ("Viridis", "Inferno") and len(selected_cases) > 0:
                import matplotlib.cm as cm
                cmap = cm.get_cmap(colormap_choice.lower())
                upper = 0.70 if colormap_choice == "Inferno" else 0.85
                sample_range = np.linspace(0.0, upper, len(selected_cases))
                palette = [cmap(pos) for pos in sample_range]
                for case_name, color in zip(selected_cases, palette):
                    case_color_by_norm[case_name.strip().lower()] = color
            else:
                for case_name in selected_cases:
                    case_color_by_norm[case_name.strip().lower()] = "steelblue"

            n = len(summaries)
            fig, axes = plt.subplots(1, n, figsize=(6.8 * n, 5.0), constrained_layout=True)
            if n == 1:
                axes = [axes]

            for ax, grad in zip(axes, summaries.keys()):
                df, _src = summaries[grad]
                if metric_name not in df.index:
                    ax.set_title(f"{grad} - metric missing")
                    ax.axis("off")
                    continue

                values = df.loc[metric_name].astype(float)
                index_map = {str(name).strip().lower(): name for name in values.index}
                labels = []
                for selected_name in selected_cases:
                    key = index_map.get(selected_name.strip().lower())
                    if key is not None:
                        labels.append(key)
                if not labels:
                    ax.set_title(f"{grad} - no selected cases")
                    ax.axis("off")
                    continue
                yvals = np.array([values[name] for name in labels], dtype=float)
                bar_colors = [case_color_by_norm.get(str(name).strip().lower(), "steelblue") for name in labels]

                x = np.arange(len(labels))
                bars = ax.bar(x, yvals, color=bar_colors, alpha=0.9)
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=25, ha="right")
                ax.set_ylabel(metric_name)
                ax.set_title(f"{grad} - {metric_name}")
                ax.grid(True, axis="y", linestyle="--", alpha=0.45)

                for b, v in zip(bars, yvals):
                    if np.isfinite(v):
                        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)

            tmp_file = os.path.join(tempfile.gettempdir(), "simulation_metrics_compare.png")
            self._maybe_compact_dimensions(fig)
            self._maybe_customize_fonts(fig)
            fig.savefig(tmp_file, dpi=220, bbox_inches='tight')
            pix = QPixmap(tmp_file)
            self.image_label.setPixmap(pix)
            self.current_analysis_figure = fig
            self.current_analysis_image_path = None
            self.current_analysis_filename = f"SimulationMetrics_{metric_name}_{selected_gradient}"
        except Exception as e:
            QMessageBox.critical(self, "Compare metrics", f"Failed to compare metrics:\n{e}")

    # ---------------------------------------------------------
    # compare plots support methods
    # ---------------------------------------------------------

    def compare_drop_event(self, event):
        """Handle .mat files dropped into the central plot area."""
        try:
            if not event.mimeData().hasUrls():
                print("[DEBUG] No URLs in drop event")
                event.ignore()
                return
            
            event.acceptProposedAction()
            added_count = 0
            
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                print(f"[DEBUG] Processing: {file_path}")
                
                if not os.path.isfile(file_path):
                    print(f"[DEBUG]   - Not a file")
                    continue
                
                if not file_path.lower().endswith('.mat'):
                    print(f"[DEBUG]   - Not .mat")
                    continue
                
                # Generate default label from file name
                file_name = os.path.basename(file_path)
                default_label = os.path.splitext(file_name)[0]
                
                # Create custom widget for this item
                item_widget = CompareFileItemWidget(file_path, default_label)
                
                # Set up remove callback
                def make_remove_callback(gui):
                    def remove_item(path):
                        # Find and remove the item from the list
                        for i in range(gui.compare_file_list.count()):
                            item = gui.compare_file_list.item(i)
                            w = gui.compare_file_list.itemWidget(item)
                            if w and hasattr(w, 'file_path') and w.file_path == path:
                                gui.compare_file_list.takeItem(i)
                                break
                        # Rebuild the compare_items list from current widgets
                        gui._rebuild_compare_items()
                        # Update the plot
                        gui.update_compare_plot()
                    return remove_item
                
                item_widget.remove_callback = make_remove_callback(self)
                
                # Add to list widget
                list_item = QListWidgetItem(self.compare_file_list)
                list_item.setSizeHint(item_widget.sizeHint())
                self.compare_file_list.setItemWidget(list_item, item_widget)
                
                added_count += 1
                print(f"[DEBUG]   - Added as '{default_label}'")
            
            if added_count > 0:
                print(f"[DEBUG] Rebuilding compare items and updating plot...")
                self._rebuild_compare_items()
                self.update_compare_plot()
                
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()

    def _rebuild_compare_items(self):
        """Rebuild the compare_items list from current widgets."""
        self.compare_items.clear()
        for i in range(self.compare_file_list.count()):
            item = self.compare_file_list.item(i)
            widget = self.compare_file_list.itemWidget(item)
            if widget and isinstance(widget, CompareFileItemWidget):
                file_path = widget.file_path
                label = widget.get_label()
                self.compare_items.append((file_path, label))
        print(f"[DEBUG] Rebuilt compare_items: {len(self.compare_items)} items")

    def clear_compare_files(self):
        """Empty the compare-items list and clear the list widget + image."""
        self.compare_items.clear()
        self.compare_file_list.clear()
        # clear preview area
        self.image_label.clear()

    def _generate_compare_figure(self):
        """Build and return a matplotlib Figure for the current compare_items.

        This replicates the plotting logic used originally in update_compare_plot.
        Returns None if there are no items or if plotting fails.
        """
        # Rebuild compare_items from current widgets (to get latest labels)
        self._rebuild_compare_items()
        
        if not self.compare_items:
            return None
        import matplotlib.pyplot as plt
        import numpy as np

        colors_palette = self._make_distinct_colors(len(self.compare_items))

        fig = plt.figure(figsize=(10, 6))
        line_width = self._time_domain_curve_line_width()
        any_legend = False

        for file_idx, (path, label) in enumerate(self.compare_items):
            try:
                Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(path)
                color = colors_palette[file_idx]
                legend_added = False

                for n in range(nDelays):
                    delay_offset = n * (deadTime + acqTime)
                    tiempo_corr = tiempo + delay_offset

                    if not legend_added:
                        plt.plot(tiempo_corr, Be[n, :], 'o', markersize=5,
                                 color=color, alpha=0.4, label=label)
                        legend_added = True
                        any_legend = True
                    else:
                        plt.plot(tiempo_corr, Be[n, :], 'o', markersize=5,
                                 color=color, alpha=0.4)

                    plt.plot(
                        tiempo_corr,
                        BeddyFitted[n, :],
                        '-',
                        color=color,
                        alpha=0.8,
                        linewidth=line_width,
                    )

                    if n == 0:
                        y0_measured = Be[n, 0]
                        y0_fitted = BeddyFitted[n, 0]
                        x0 = tiempo_corr[0]

                        plt.annotate(f"{y0_measured:.2f}",
                                     (x0, y0_measured),
                                     textcoords="offset points", xytext=(20, 12),
                                     ha='left', fontsize=11, color=color, fontweight='bold')

                        plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                                     (x0, y0_measured),
                                     textcoords="offset points", xytext=(30, 12),
                                     ha='left', fontsize=11, color='gray', fontweight='bold')
            except Exception as e:
                print(f"[ERROR] Unable to process '{path}': {e}")
                import traceback
                traceback.print_exc()

        if any_legend:
            plt.legend(fontsize=11)
        plt.title("Beddy Measured - Comparison", fontsize=13)
        plt.xlabel("Time (ms)", fontsize=12)
        plt.ylabel("Beddy (µT)", fontsize=12)
        plt.grid(True)
        plt.tight_layout()
        self._maybe_compact_dimensions(fig)
        self._maybe_customize_legends(fig)
        self._maybe_customize_fonts(fig)
        return fig

    def save_compare_plot(self):
        """Prompt user for filename and save the current compare figure."""
        if not self.compare_items:
            QMessageBox.information(self, "Save Plot", "No files to plot.")
            return

        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Save Comparison Plot",
            "",
            "PNG Image (*.png);;All Files (*)"
        )
        if not fname:
            return
        
        fig = self._generate_compare_figure()
        if fig is not None:
            try:
                fig.savefig(fname, dpi=300, bbox_inches='tight')
                QMessageBox.information(self, "Save Plot", f"Plot saved to {fname}")
            except Exception as e:
                QMessageBox.critical(self, "Save Plot",
                                     f"Failed to save plot:\n{e}")
            finally:
                import matplotlib.pyplot as plt
                plt.close(fig)

    def update_compare_plot(self):
        """Rebuild overlay plot from all stored compare_items.
        
        Replicates the exact format from measured_analysis.py:
        - Points for measured data
        - Fitted curves
        - Annotations with measured/fitted values
        """
        try:
            # Rebuild compare_items from current widgets (to get latest labels)
            self._rebuild_compare_items()
            
            print(f"[DEBUG] update_compare_plot: {len(self.compare_items)} items")
            if not self.compare_items:
                return
            
            import matplotlib.pyplot as plt
            import numpy as np
            
            colors_palette = self._make_distinct_colors(len(self.compare_items))
            
            plt.figure(figsize=(10, 6))
            line_width = self._time_domain_curve_line_width()
            
            any_legend = False
            for file_idx, (path, label) in enumerate(self.compare_items):
                try:
                    print(f"[DEBUG] Plotting: {label} from {path}")
                    Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(path)
                    
                    # Pick a color for this file
                    color = colors_palette[file_idx]
                    
                    # Plot all delays (like nDelay_selected == "all")
                    legend_added = False
                    for n in range(nDelays):
                        delay_offset = n * (deadTime + acqTime)
                        tiempo_corr = tiempo + delay_offset
                        
                        # Plot measured data points
                        if not legend_added:
                            plt.plot(tiempo_corr, Be[n, :], 'o', markersize=5, 
                                   color=color, alpha=0.4, label=label)
                            legend_added = True
                            any_legend = True
                        else:
                            plt.plot(tiempo_corr, Be[n, :], 'o', markersize=5, 
                                   color=color, alpha=0.4)
                        
                        # Plot fitted curve
                        plt.plot(
                            tiempo_corr,
                            BeddyFitted[n, :],
                            '-',
                            color=color,
                            alpha=0.8,
                            linewidth=line_width,
                        )
                        
                        # Annotate only first point of first delay (n=0)
                        if n == 0:
                            y0_measured = Be[n, 0]
                            y0_fitted = BeddyFitted[n, 0]
                            x0 = tiempo_corr[0]
                            
                            # Measured value in file color (bold)
                            plt.annotate(f"{y0_measured:.2f}",
                                       (x0, y0_measured),
                                       textcoords="offset points", xytext=(20, 12),
                                       ha='left', fontsize=11, color=color, fontweight='bold')
                            
                            # Fitted value in gray (slash separates)
                            plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                                       (x0, y0_measured),
                                       textcoords="offset points", xytext=(30, 12),
                                       ha='left', fontsize=11, color='gray', fontweight='bold')
                    
                    plotted_count = nDelays
                    print(f"[DEBUG] Plotted {label}: {plotted_count} delays")
                    
                except Exception as e:
                    print(f"[ERROR] Failed to plot {label}: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Configure plot
            if any_legend:
                plt.legend(fontsize=11)
            plt.title("Beddy Measured - Comparison", fontsize=13)
            plt.xlabel("Time (ms)", fontsize=12)
            plt.ylabel("Beddy (µT)", fontsize=12)
            plt.grid(True)
            plt.tight_layout()

            fig = plt.gcf()
            self._maybe_compact_dimensions(fig)
            self._maybe_customize_legends(fig)
            self._maybe_customize_fonts(fig)
            
            # Save to temporary file and display
            import tempfile, os
            tmp_file = os.path.join(tempfile.gettempdir(), "compare_plot.png")
            plt.savefig(tmp_file, dpi=300, bbox_inches='tight')
            plt.close()
            
            pix = QPixmap(tmp_file)
            self.image_label.setPixmap(pix)
            print(f"[DEBUG] Plot displayed successfully")
                
        except Exception as e:
            print(f"[ERROR] update_compare_plot: {e}")
            import traceback
            traceback.print_exc()
    # =========================================================
    # ANALYSIS CALL
    # =========================================================

    # remove resizeEvent scaling; ZoomLabel handles zooming itself
    # def resizeEvent(self, event):
    #     super().resizeEvent(event)
    #     # rescale image when the window is resized
    #     if hasattr(self, 'current_pixmap') and not self.current_pixmap.isNull():
    #         self.image_label.setPixmap(
    #             self.current_pixmap.scaled(
    #                 self.image_label.width(),
    #                 self.image_label.height(),
    #                 Qt.KeepAspectRatio,
    #                 Qt.SmoothTransformation
    #             )
    #         )

    def reset_zoom(self):
        if self.analysis_toolbar is not None and self.analysis_canvas is not None:
            self.analysis_toolbar.home()
            self._sync_plot_limit_controls_from_axes()
            return

        # restore zoom on the image label
        if isinstance(self.image_label, ZoomLabel):
            self.image_label.reset_zoom()

    def _set_plot_pan_mode(self, enabled):
        if isinstance(getattr(self, "image_label", None), ZoomLabel):
            self.image_label.set_pan_enabled(enabled)

    def _collect_case_custom_legends(self):
        labels = []

        case1 = getattr(self, "case1_legend_input", None)
        if case1 is not None:
            txt = case1.text().strip()
            if txt:
                labels.append(txt)

        for case in getattr(self, "additional_cases", []):
            if not case.get('visible', False):
                continue
            legend_input = case.get('legend_input')
            if legend_input is None:
                continue
            txt = legend_input.text().strip()
            if txt:
                labels.append(txt)

        return labels

    def _apply_custom_legends_to_figure(self, fig, labels):
        if fig is None or not labels:
            return

        def _split_suffix(text):
            t = str(text or "").strip()
            # Exponential fit labels may carry params after a separator.
            if "_exp_fit" in t:
                idx = t.find("_exp_fit")
                base = t[:idx]
                suffix = t[idx:]
                return base, suffix
            if t.endswith("_fitted"):
                return t[:-7], "_fitted"
            return t, ""

        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is None:
                continue

            text_items = legend.get_texts()
            if not text_items:
                continue

            mapping = {}
            next_idx = 0
            for txt_obj in text_items:
                current = txt_obj.get_text().strip()
                base, suffix = _split_suffix(current)
                if base not in mapping:
                    if next_idx < len(labels):
                        mapping[base] = labels[next_idx]
                        next_idx += 1
                    else:
                        mapping[base] = base
                txt_obj.set_text(f"{mapping[base]}{suffix}")

    def _maybe_customize_legends(self, fig):
        """Apply custom legend names from fixed text fields when enabled."""
        if fig is None:
            return
        compare_checkbox = getattr(self, "change_legend_checkbox", None)
        analyze_checkbox = getattr(self, "analyze_change_legend_checkbox", None)

        compare_checked = bool(compare_checkbox and compare_checkbox.isChecked())
        analyze_checked = bool(analyze_checkbox and analyze_checkbox.isChecked())
        if not (compare_checked or analyze_checked):
            return

        labels = self._collect_case_custom_legends()
        self._apply_custom_legends_to_figure(fig, labels)

    def _maybe_compact_dimensions(self, fig):
        """Optionally adjust subplot dimensions via user input dialog."""
        if fig is None:
            return

        compare_checkbox = getattr(self, "change_dimensions_checkbox", None)
        analyze_checkbox = getattr(self, "analyze_change_dimensions_checkbox", None)

        compare_checked = bool(compare_checkbox and compare_checkbox.isChecked())
        analyze_checked = bool(analyze_checkbox and analyze_checkbox.isChecked())
        if not (compare_checked or analyze_checked):
            return

        try:
            # Ask user for width multiplier
            width_val, ok_w = QInputDialog.getDouble(
                self,
                "Change Dimensions",
                "Width multiplier (e.g., 0.65):",
                value=0.65,
                min=0.2,
                max=2.0,
                decimals=2
            )
            if not ok_w:
                return

            # Ask user for height multiplier
            height_val, ok_h = QInputDialog.getDouble(
                self,
                "Change Dimensions",
                "Height multiplier (e.g., 1.25):",
                value=1.25,
                min=0.5,
                max=3.0,
                decimals=2
            )
            if not ok_h:
                return

            w, h = fig.get_size_inches()
            new_w = float(w) * width_val
            new_h = float(h) * height_val
            fig.set_size_inches(new_w, new_h, forward=True)

            # Let matplotlib recalculate margins so nothing gets clipped
            try:
                fig.tight_layout(pad=2.0)
            except Exception:
                pass
        except Exception:
            pass

    def _default_plot_parameters(self):
        return {
            "font_size": 12,
            "xytext_x": 20.0,
            "xytext_y": 12.0,
            "marker_size": 5.0,
            "line_width": 1.5,
        }

    def _load_plot_parameters(self):
        params = self._default_plot_parameters()
        settings = getattr(self, "settings", None)
        if settings is None:
            return params

        try:
            params["font_size"] = int(settings.value("plot_params/font_size", params["font_size"]))
        except Exception:
            pass
        try:
            params["xytext_x"] = float(settings.value("plot_params/xytext_x", params["xytext_x"]))
        except Exception:
            pass
        try:
            params["xytext_y"] = float(settings.value("plot_params/xytext_y", params["xytext_y"]))
        except Exception:
            pass
        try:
            params["marker_size"] = float(settings.value("plot_params/marker_size", params["marker_size"]))
        except Exception:
            pass
        try:
            params["line_width"] = float(settings.value("plot_params/line_width", params["line_width"]))
        except Exception:
            pass
        return params

    def _save_plot_parameters(self, params):
        settings = getattr(self, "settings", None)
        if settings is None:
            return
        settings.setValue("plot_params/font_size", int(params.get("font_size", 12)))
        settings.setValue("plot_params/xytext_x", float(params.get("xytext_x", 20.0)))
        settings.setValue("plot_params/xytext_y", float(params.get("xytext_y", 12.0)))
        settings.setValue("plot_params/marker_size", float(params.get("marker_size", 5.0)))
        settings.setValue("plot_params/line_width", float(params.get("line_width", 1.5)))

    def _time_domain_curve_line_width(self):
        params = self._load_plot_parameters()
        try:
            return float(params.get("line_width", 1.5))
        except Exception:
            return 1.5

    def _apply_plot_parameters_to_figure(self, fig, params):
        import matplotlib

        if fig is None:
            return

        font_size = int(params.get("font_size", 12))
        marker_size = float(params.get("marker_size", 5.0))
        xytext_x = float(params.get("xytext_x", 20.0))
        xytext_y = float(params.get("xytext_y", 12.0))

        # Preserve current legend marker appearance before changing plot markers.
        legend_marker_sizes = {}
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is None:
                continue
            handles = list(getattr(legend, "legend_handles", []))
            if not handles and hasattr(legend, "legendHandles"):
                handles = list(getattr(legend, "legendHandles", []))
            sizes = []
            for h in handles:
                if hasattr(h, "get_markersize"):
                    try:
                        sizes.append(float(h.get_markersize()))
                    except Exception:
                        sizes.append(np.nan)
                else:
                    sizes.append(np.nan)
            legend_marker_sizes[id(ax)] = sizes

        for ax in fig.axes:
            ax.title.set_fontsize(font_size)
            ax.xaxis.label.set_fontsize(font_size)
            ax.yaxis.label.set_fontsize(font_size)
            ax.tick_params(axis='both', labelsize=font_size)

            legend = ax.get_legend()
            if legend is not None:
                for txt in legend.get_texts():
                    txt.set_fontsize(font_size)
                legend_title = legend.get_title()
                if legend_title is not None:
                    legend_title.set_fontsize(font_size)

            # Apply point size only to plotted markers.
            for line in ax.get_lines():
                marker = line.get_marker()
                if marker not in (None, "", "None", " "):
                    line.set_markersize(marker_size)

            # Move annotations according to xytext and set their font.
            for txt in ax.texts:
                txt.set_fontsize(font_size)
                if isinstance(txt, matplotlib.text.Annotation):
                    try:
                        txt.set_position((xytext_x, xytext_y))
                        txt.set_ha('left')
                    except Exception:
                        pass

            # Restore legend marker size so legend readability stays unchanged.
            if legend is not None:
                handles = list(getattr(legend, "legend_handles", []))
                if not handles and hasattr(legend, "legendHandles"):
                    handles = list(getattr(legend, "legendHandles", []))
                old_sizes = legend_marker_sizes.get(id(ax), [])
                for idx, h in enumerate(handles):
                    if not hasattr(h, "set_markersize"):
                        continue
                    if idx < len(old_sizes) and np.isfinite(old_sizes[idx]):
                        h.set_markersize(float(old_sizes[idx]))

        if getattr(fig, "_suptitle", None) is not None:
            fig._suptitle.set_fontsize(font_size)
        for txt in fig.texts:
            txt.set_fontsize(font_size)

        fig.canvas.draw_idle()

    def _maybe_customize_fonts(self, fig):
        """Optionally customize plot parameters (font, xytext offset, marker size)."""
        if fig is None:
            return

        compare_checkbox = getattr(self, "change_font_checkbox", None)
        analyze_checkbox = getattr(self, "analyze_change_font_checkbox", None)

        compare_checked = bool(compare_checkbox and compare_checkbox.isChecked())
        analyze_checked = bool(analyze_checkbox and analyze_checkbox.isChecked())
        if not (compare_checked or analyze_checked):
            return

        try:
            current = self._load_plot_parameters()
            dlg = _ChangePlotParametersDialog(initial_values=current, parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return

            params = dlg.values()
            self._save_plot_parameters(params)
            self._apply_plot_parameters_to_figure(fig, params)
        except Exception as e:
            QMessageBox.warning(self, "Plot Parameters", f"Error: {e}")

    def update_gradient_options(self):
        """Update gradient dropdown based on plot type."""
        plot_type = self.plot_combo.currentText()
        
        # Temporarily disconnect to avoid triggering events
        self.gradient_combo.blockSignals(True)
        
        if plot_type in ["FID", "Phase"]:
            # No "All" option for FID and Phase
            self.gradient_combo.clear()
            self.gradient_combo.addItems(["GX", "GY", "GZ"])
        else:
            # Beddy allows "All"
            self.gradient_combo.clear()
            self.gradient_combo.addItems(["GX", "GY", "GZ", "All"])
        
        self.gradient_combo.blockSignals(False)

    def save_current_analysis_plot(self):
        """Save the current analysis figure to file."""
        has_table = self.current_analysis_table_frames is not None and len(self.current_analysis_table_frames) > 0
        has_figure = self.current_analysis_figure is not None
        has_image = self.current_analysis_image_path is not None and os.path.exists(self.current_analysis_image_path)

        if not has_table and not has_figure and not has_image:
            pix = self.image_label.pixmap() if hasattr(self.image_label, 'pixmap') else None
            has_image = pix is not None and not pix.isNull()

        if not has_table and not has_figure and not has_image:
            QMessageBox.warning(self, "Save Plot", "No plot to save. Run Plot first.")
            return

        if has_table:
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Save Analysis Table",
                f"{self.current_analysis_table_filename or self.current_analysis_filename or 'single_value_metrics'}.csv",
                "CSV Files (*.csv);;All Files (*)"
            )

            if not fname:
                return

            try:
                combined_frames = []
                for item in self.current_analysis_table_frames:
                    # Support both old (grad, df) and new (grad, metric, df) tuple formats
                    if len(item) == 3:
                        grad_token, metric_name, df = item
                    else:
                        grad_token, df = item
                        metric_name = ""
                    df_to_save = df.copy()
                    if metric_name:
                        df_to_save.insert(0, "Metric", metric_name)
                    df_to_save.insert(0, "Gradient", grad_token)
                    combined_frames.append(df_to_save)
                combined = pd.concat(combined_frames, ignore_index=True)
                combined.to_csv(fname, index=False)
                QMessageBox.information(self, "Save Plot", f"Table saved to {fname}")
            except Exception as e:
                QMessageBox.critical(self, "Save Plot", f"Failed to save table:\n{e}")
            return

        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Save Analysis Plot",
            f"{self.current_analysis_filename}.png",
            "PNG Image (*.png);;All Files (*)"
        )

        if not fname:
            return

        try:
            if self.current_analysis_figure is not None:
                self.current_analysis_figure.savefig(fname, dpi=300, bbox_inches='tight')
            elif self.current_analysis_image_path is not None and os.path.exists(self.current_analysis_image_path):
                shutil.copyfile(self.current_analysis_image_path, fname)
            else:
                pix = self.image_label.pixmap()
                if pix is None or pix.isNull():
                    raise RuntimeError("No rendered image available to save")
                pix.save(fname, "PNG")
            QMessageBox.information(self, "Save Plot", f"Plot saved to {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Save Plot", f"Failed to save:\n{e}")

    def _get_plot_active_cases(self):
        cases = []

        base = (self.base_path or self.path_edit.text().strip()) if hasattr(self, 'path_edit') else self.base_path
        setup = self.setup_combo.currentText().strip() if hasattr(self, 'setup_combo') else ""
        if base and setup:
            cases.append({'base_path': base, 'setup': setup})

        for case in self.additional_cases:
            if not case.get('visible', False):
                continue
            case_base = case.get('base_path') or case['path_edit'].text().strip()
            case_setup = case['setup_combo'].currentText().strip()
            if case_base and case_setup:
                cases.append({'base_path': case_base, 'setup': case_setup})

        return cases

    def _list_case_phantom_positions(self, base_path, setup_name):
        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        setup_path = os.path.join(base_path, setup_name)
        if not os.path.isdir(setup_path):
            return []

        candidates = [
            f for f in os.listdir(setup_path)
            if os.path.isdir(os.path.join(setup_path, f)) and f != "Experimental_data"
        ]
        normalized = []
        for name in candidates:
            canonical = self._canonical_phantom_position(name)
            if canonical in defaults and canonical not in normalized:
                normalized.append(canonical)

        return [p for p in defaults if p in normalized]

    def refresh_plot_phantom_dropdown(self):
        if not hasattr(self, 'plot_phantom_combo') or self._plot_phantom_sync_in_progress:
            return

        previous = self.plot_phantom_combo.currentText().strip()
        self.plot_phantom_combo.blockSignals(True)
        self.plot_phantom_combo.clear()

        active_cases = self._get_plot_active_cases()
        available_union = set()
        available_intersection = None
        for case in active_cases:
            current_positions = set(self._list_case_phantom_positions(case['base_path'], case['setup']))
            available_union |= current_positions
            available_intersection = current_positions if available_intersection is None else (available_intersection & current_positions)

        selected_case_phantoms = []
        if hasattr(self, 'phantom_combo'):
            selected_case_phantoms.append(self._canonical_phantom_position(self.phantom_combo.currentText()))
        for case in getattr(self, 'additional_cases', []):
            if not case.get('visible', False):
                continue
            selected_case_phantoms.append(
                self._canonical_phantom_position(case['phantom_combo'].currentText())
            )

        unique_selected = {p for p in selected_case_phantoms if p}

        defaults = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        ordered = [p for p in defaults if p in available_union]
        if len(unique_selected) > 1:
            ordered.append("Different")
        ordered.append("All")
        self.plot_phantom_combo.addItems(ordered)

        default_value = ""
        if previous == "All" and "All" in ordered:
            default_value = "All"

        if not default_value and len(unique_selected) > 1 and "Different" in ordered:
            default_value = "Different"

        if not default_value and len(unique_selected) == 1:
            only_selected = next(iter(unique_selected))
            if only_selected in ordered:
                default_value = only_selected

        if not default_value and hasattr(self, 'global_phantom_combo'):
            g = self.global_phantom_combo.currentText().strip()
            if g and g in ordered:
                default_value = g

        if not default_value and available_intersection and len(available_intersection) == 1:
            only = next(iter(available_intersection))
            if only in ordered:
                default_value = only

        if not default_value and previous in ordered:
            default_value = previous

        if not default_value and hasattr(self, 'phantom_combo'):
            local = self._canonical_phantom_position(self.phantom_combo.currentText())
            if local in ordered:
                default_value = local

        if default_value:
            self.plot_phantom_combo.setCurrentText(default_value)
        elif ordered:
            self.plot_phantom_combo.setCurrentIndex(0)

        self.plot_phantom_combo.blockSignals(False)

    def apply_plot_phantom_selection(self):
        if self._plot_phantom_sync_in_progress:
            return

        selected = self.plot_phantom_combo.currentText().strip()
        if not selected or selected in ("All", "Different"):
            return

        target = self._canonical_phantom_position(selected)
        self._plot_phantom_sync_in_progress = True
        try:
            idx_main = self.phantom_combo.findText(target)
            if idx_main >= 0:
                self.phantom_combo.setCurrentIndex(idx_main)

            for case in self.additional_cases:
                if not case.get('visible', False):
                    continue
                combo = case['phantom_combo']
                idx = combo.findText(target)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            self._plot_phantom_sync_in_progress = False

        self.refresh_plot_phantom_dropdown()

    def extract_filter_metrics(self):
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        setup = self.setup_combo.currentText()
        phantom = self._canonical_phantom_position(self.phantom_combo.currentText())
        gradient = self.gradient_combo.currentText()
        ndelay = self.ndelay_combo.currentText()

        cutoff_values = [0.12, 0.10, 0.08, 0.06, 0.04]
        order_values = [1, 2, 4, 8]

        try:
            result = extract_filter_metrics_sweep(
                base_path=self.base_path,
                setup=setup,
                phantom_position=phantom,
                gradient_selected=gradient,
                nDelay_selected=ndelay,
                cutoff_values=cutoff_values,
                order_values=order_values
            )

            msg = (
                f"Sweep completed.\n"
                f"Rows: {result.get('row_count', 0)}\n"
                f"CSV: {result.get('csv_path', '')}\n"
                f"Heatmaps: {len(result.get('heatmap_paths', []))}"
            )
            QMessageBox.information(self, "Extract filter metrics", msg)
        except Exception as e:
            QMessageBox.critical(self, "Extract filter metrics", f"Failed:\n{e}")

    def extract_single_value_metrics(self):
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        self._refresh_compare_measured_columns()

        setup = self.setup_combo.currentText()
        gradient = self.compare_grad_combo.currentText()
        compare_with_sim = bool(self.compare_with_sim_checkbox.isChecked())
        custom_hist_labels = self._collect_case_custom_legends() if self.change_legend_checkbox.isChecked() else []

        # Collect all available measured-table columns.
        all_measured_columns = [
            self.compare_meas_combo.itemText(i)
            for i in range(self.compare_meas_combo.count())
            if self.compare_meas_combo.itemText(i).strip()
        ]
        if not all_measured_columns:
            QMessageBox.warning(self, "Warning", "No measured columns available.")
            return

        all_measured_columns_raw = [
            str(c).strip() for c in getattr(self, "_compare_measured_raw_columns", [])
            if str(c).strip()
        ]
        if not all_measured_columns_raw:
            all_measured_columns_raw = list(all_measured_columns)

        try:
            active_extra_cases = []
            for case in self.additional_cases:
                if not case.get('visible', False):
                    continue
                case_base = case.get('base_path') or case['path_edit'].text().strip()
                case_setup = case['setup_combo'].currentText()
                case_phantom = self._canonical_phantom_position(case['phantom_combo'].currentText())
                if case_base and case_setup and case_phantom:
                    active_extra_cases.append({
                        'base_path': case_base,
                        'setup': case_setup,
                        'phantom': case_phantom
                    })

            compare_cases = [{
                'base_path': self.base_path,
                'setup': setup,
                'phantom': self.phantom_combo.currentText()
            }]
            if self.add_case_enabled and len(active_extra_cases) > 0:
                compare_cases.extend(active_extra_cases)

            selected_metrics = self._ask_metric_selection(all_measured_columns)
            if selected_metrics is None:
                return

            selected_metrics = [m for m in selected_metrics if str(m).strip()]
            if not selected_metrics:
                QMessageBox.warning(self, "Warning", "No metrics selected.")
                return

            selected_metrics = self._expand_b_integrated_metrics_by_windows(selected_metrics, all_measured_columns_raw)
            if selected_metrics is None:
                return

            selected_metrics = self._with_rmse_companions(selected_metrics, all_measured_columns_raw)

            frames = []

            # Standard table-driven metrics.
            std_metrics = [m for m in selected_metrics if m in all_measured_columns_raw and m != "Exp_fit"]
            if std_metrics:
                frames.extend(
                    self._build_single_value_metrics_frames(
                        compare_cases=compare_cases,
                        gradient=gradient,
                        measured_columns=std_metrics,
                        custom_labels=custom_hist_labels,
                    )
                )

            # Special Exp_fit workflow.
            if "Exp_fit" in selected_metrics:
                exp_options = self._ask_exp_fit_options()
                if exp_options is None:
                    return
                frames.extend(
                    self._build_curve_metric_frames(
                        compare_cases=compare_cases,
                        gradient=gradient,
                        custom_labels=custom_hist_labels,
                        mode="exp_fit",
                        options=exp_options,
                    )
                )

            if not frames:
                QMessageBox.warning(self, "Warning", "No metrics could be generated.")
                return

            continuous_df = self._frames_to_continuous_table(frames)

            self.current_analysis_figure = None
            self.current_analysis_image_path = None
            self.current_analysis_table_frames = frames
            self.current_analysis_table_filename = (
                f"Measurements_{'vs_simulations_' if compare_with_sim else ''}"
                f"G{gradient}_AllMetrics_Table"
            )
            self.current_analysis_filename = self.current_analysis_table_filename

            self._show_single_value_metrics_dialog_continuous(
                continuous_df,
                title=f"Single-value metrics — G{gradient} (continuous)",
            )
        except FileNotFoundError as e:
            QMessageBox.critical(
                self, "Error",
                f"Missing required file:\n\n{str(e)}\n\n"
                f"Make sure you have:\n"
                f"1. Run 'Analyze' first to generate measured table"
            )
        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Data format error:\n\n{str(e)}")
        except KeyError as e:
            QMessageBox.critical(
                self, "Error",
                f"Missing column in table:\n\n{str(e)}\n\n"
                f"This may indicate a table format issue."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Metrics extraction failed:\n\n{str(e)}")

    def _lighten_color(self, color, amount):
        import matplotlib.colors as mcolors
        rgb = np.array(mcolors.to_rgb(color), dtype=float)
        amount = float(np.clip(amount, -1.0, 1.0))
        if amount >= 0:
            new_rgb = rgb + (1.0 - rgb) * amount
        else:
            new_rgb = rgb * (1.0 + amount)
        return tuple(new_rgb)

    def _make_distinct_colors(self, n_colors):
        if n_colors <= 0:
            return []
        import matplotlib.cm as cm
        cmap = cm.get_cmap("hsv")
        return [cmap(i / max(1, n_colors)) for i in range(n_colors)]

    def _resolve_case_folder_path(self, case_path, case_setup, case_phantom):
        setup_name = str(case_setup or "").strip()
        phantom_name = str(case_phantom or "").strip()

        candidates = [
            os.path.join(case_path, setup_name, phantom_name),
        ]

        case_tail = os.path.basename(os.path.normpath(case_path)).lower()
        if case_tail == setup_name.lower():
            candidates.append(os.path.join(case_path, phantom_name))

        seen = set()
        for p in candidates:
            p_norm = os.path.normpath(p)
            if p_norm in seen:
                continue
            seen.add(p_norm)
            if os.path.isdir(p_norm):
                return p_norm

        return os.path.normpath(candidates[0])

    def _make_palette_colors(self, n_cases, colormap):
        """
        Return a list of n_cases RGBA colors sampled from `colormap`, starting
        at self._plot_session_color_index and advancing it so the next call
        continues from the next free slot.

        Returns None for "Single-color gradient" (callers use per-axis tinting).
        """
        KNOWN = ("Viridis", "Inferno", "Plasma", "Magma", "Cividis")
        if colormap not in KNOWN or n_cases == 0:
            return None
        import matplotlib.cm as cm
        cmap = cm.get_cmap(colormap.lower())
        upper = 0.70 if colormap == "Inferno" else 0.85
        # Golden-ratio stepping minimizes repeats across long sessions.
        phi = 0.6180339887498949
        start = int(self._plot_session_color_index)
        positions = [(((start + i) * phi) % 1.0) * upper for i in range(n_cases)]
        self._plot_session_color_index = start + n_cases
        return [cmap(p) for p in positions]

    def _show_analysis_figure(self, fig):
        if fig is None:
            return

        self.current_analysis_figure = fig

        self.plot_xlim_min_spin.setEnabled(True)
        self.plot_xlim_max_spin.setEnabled(True)
        self.plot_ylim_min_spin.setEnabled(True)
        self.plot_ylim_max_spin.setEnabled(True)
        self.plot_auto_limits_btn.setEnabled(True)
        self._sync_plot_limit_controls_from_axes()

    def _current_analysis_axes(self):
        if self.analysis_canvas is not None and self.analysis_canvas.figure is not None:
            return [ax for ax in self.analysis_canvas.figure.axes if ax is not None]
        fig = getattr(self, "current_analysis_figure", None)
        if fig is None:
            return []
        return [ax for ax in fig.axes if ax is not None]

    def _refresh_image_from_current_figure(self):
        fig = getattr(self, "current_analysis_figure", None)
        if fig is None:
            return
        import tempfile
        tmp_file = os.path.join(tempfile.gettempdir(), "analysis_live_view.png")
        fig.savefig(tmp_file, dpi=200)
        self.image_label.setPixmap(QPixmap(tmp_file))

    def _sync_plot_limit_controls_from_axes(self):
        if self._updating_plot_limits:
            return
        axes = self._current_analysis_axes()
        if not axes:
            return

        xmins, xmaxs, ymins, ymaxs = [], [], [], []
        for ax in axes:
            xl = ax.get_xlim()
            yl = ax.get_ylim()
            xmins.append(float(min(xl)))
            xmaxs.append(float(max(xl)))
            ymins.append(float(min(yl)))
            ymaxs.append(float(max(yl)))

        xmin, xmax = min(xmins), max(xmaxs)
        ymin, ymax = min(ymins), max(ymaxs)
        xspan = max(1e-6, xmax - xmin)
        yspan = max(1e-6, ymax - ymin)

        self._updating_plot_limits = True
        try:
            self.plot_xlim_min_spin.setRange(xmin - xspan * 3.0, xmax)
            self.plot_xlim_max_spin.setRange(xmin, xmax + xspan * 3.0)
            self.plot_ylim_min_spin.setRange(ymin - yspan * 3.0, ymax)
            self.plot_ylim_max_spin.setRange(ymin, ymax + yspan * 3.0)

            self.plot_xlim_min_spin.setValue(xmin)
            self.plot_xlim_max_spin.setValue(xmax)
            self.plot_ylim_min_spin.setValue(ymin)
            self.plot_ylim_max_spin.setValue(ymax)
        finally:
            self._updating_plot_limits = False

    def _on_plot_limits_changed(self):
        if self._updating_plot_limits:
            return
        axes = self._current_analysis_axes()
        if not axes:
            return

        xmin = float(self.plot_xlim_min_spin.value())
        xmax = float(self.plot_xlim_max_spin.value())
        ymin = float(self.plot_ylim_min_spin.value())
        ymax = float(self.plot_ylim_max_spin.value())
        if not (xmin < xmax and ymin < ymax):
            return

        for ax in axes:
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)
        if self.analysis_canvas is not None:
            self.analysis_canvas.draw_idle()
        else:
            self._refresh_image_from_current_figure()

    def _reset_plot_limits_auto(self):
        axes = self._current_analysis_axes()
        if not axes:
            return
        for ax in axes:
            ax.relim()
            ax.autoscale_view()
        if self.analysis_canvas is not None:
            self.analysis_canvas.draw_idle()
        else:
            self._refresh_image_from_current_figure()
        self._sync_plot_limit_controls_from_axes()

    def _reset_plot_session(self):
        """Reset the sim overlay session and measured-data color counter."""
        self._sim_overlay_session_cases = []
        self._sim_overlay_session_colormap = None
        self._sim_overlay_spec_color_map = {}
        self._sim_overlay_color_index = 0
        self._plot_session_color_index = 0

    def _run_beddy_multi_case(
        self,
        cases,
        gradient,
        ndelay,
        apply_filter,
        beprefilter_cutoff,
        beprefilter_order,
        colormap="Single-color gradient",
        use_subplots=False,
        save_dir=None,
        save_plot=False,
        return_figure=False,
    ):
        import matplotlib.pyplot as plt
        from scipy import signal

        base_colors = {
            'x': 'midnightblue',
            'y': 'darkred',
            'z': 'darkgreen'
        }

        palette_colors = self._make_palette_colors(len(cases), colormap)

        include_fitted_legend = bool(apply_filter)

        if gradient == "All":
            grad_list = ['x', 'y', 'z']
        else:
            grad_list = [gradient[-1].lower()]

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

        line_width = self._time_domain_curve_line_width()

        sim_overlays_list = []   # list of per-setup dicts, one per accumulated spec
        sim_offset_colors = {}
        sim_label_colors = {}
        if self._time_domain_simulation_overlay_requested():
            requested_gradients = ["GX", "GY", "GZ"] if gradient == "All" else [f"G{gradient[-1].upper()}"]
            requested_locations = [self._canonical_phantom_position(case.get("phantom", "Center")) for case in cases]
            sim_overlays_list = self._load_time_domain_simulation_overlays(
                cases=cases,
                gradients=requested_gradients,
                locations=requested_locations,
            )
            sim_cmap_name = getattr(self, "_sim_overlay_session_colormap", None) or "Viridis"
            sim_label_colors = self._build_sim_label_color_map(sim_overlays_list, sim_cmap_name)
            all_offset_keys = []
            for per_setup in sim_overlays_list:
                for payload in per_setup.values():
                    for grad_map in payload.get("curves", {}).values():
                        for curve_list in grad_map.values():
                            all_offset_keys.extend(
                                curve.get("offset_key") for curve in curve_list if curve.get("offset_key")
                            )
            sim_offset_colors = self._offset_overlay_color_map(all_offset_keys)

        if use_subplots and gradient == "All":
            fig, axes = plt.subplots(1, 3, figsize=(18, 5))
            fig.subplots_adjust(wspace=0.35)
            grad_to_axis = {'x': 0, 'y': 1, 'z': 2}
        else:
            fig = plt.figure(figsize=(10, 6))
            axes = None
            grad_to_axis = {'x': 0, 'y': 1, 'z': 2}  # not used, but define for consistency
            axes = None
            any_legend = False

        for case_idx, case in enumerate(cases):
            case_path = case['base_path']
            case_setup = case['setup']
            case_phantom = case['phantom']
            case_path_tail = os.path.basename(os.path.normpath(case_path))
            lighten_amount = -0.2 + (case_idx / (len(cases) - 1)) * 0.8 if len(cases) > 1 else 0.0

            folder_path = self._resolve_case_folder_path(case_path, case_setup, case_phantom)
            data_by_axis = {'x': [], 'y': [], 'z': []}

            if not os.path.isdir(folder_path):
                continue

            for fname in os.listdir(folder_path):
                if not fname.endswith(".mat") or fname.startswith("FID"):
                    continue
                file_path = os.path.join(folder_path, fname)
                try:
                    Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = sequenceAnalysis(file_path)
                    g = str(g_axis).lower()

                    BePrefilter = None
                    if apply_filter:
                        gammaB = 42.577e6
                        timeFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)
                        BePrefilter = np.full_like(Be, np.nan)
                        cutoff = float(np.clip(beprefilter_cutoff, 0.01, 0.49))
                        sos = signal.butter(int(beprefilter_order), cutoff, output='sos')

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
                            BePrefilter[n, :] = (1 / (4 * np.pi * gammaB)) * np.gradient(filt_diff, timeFID * 1e-3) * 1e6

                    if g in data_by_axis:
                        data_by_axis[g].append({
                            'tiempo': tiempo,
                            'Beddy': Be,
                            'BeddyFitted': BeddyFitted,
                            'BePrefilter': BePrefilter,
                            'deadTime': deadTime,
                            'acqTime': acqTime
                        })
                except Exception:
                    continue

            for g in grad_list:
                if not data_by_axis[g]:
                    continue

                current_ax = axes[grad_to_axis[g]] if axes is not None else plt

                if palette_colors is not None:
                    color = palette_colors[case_idx]
                else:
                    lighten_amount = -0.35 + (case_idx / max(1, len(cases) - 1)) * 0.85 if len(cases) > 1 else 0.0
                    color = self._lighten_color(base_colors[g], lighten_amount)
                legend_added = False
                prefilter_label_added = False
                firstpoint_label_added = False
                fitted_label_added = False
                case_label = f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}"

                for data in data_by_axis[g]:
                    tiempo = data['tiempo']
                    Beddy = data['Beddy']
                    BeddyFitted = data['BeddyFitted']
                    BePrefilter = data['BePrefilter']
                    deadTime = data['deadTime']
                    acqTime = data['acqTime']
                    nDelays = Beddy.shape[0]
                    point_zorder = 30 - case_idx

                    if ndelay_selected == "all" or (isinstance(ndelay_selected, int) and ndelay_selected >= nDelays):
                        delay_indices = list(range(nDelays))
                    else:
                        delay_indices = [ndelay_selected]

                    for n in delay_indices:
                        delay_offset = n * (deadTime + acqTime)
                        tiempo_corr = tiempo + delay_offset

                        if apply_filter and BePrefilter is not None:
                            if not prefilter_label_added:
                                current_ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=line_width, zorder=10,
                                         label=f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}_Prefiltered")
                                prefilter_label_added = True
                            else:
                                current_ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=line_width, zorder=10)
                        if not legend_added:
                            current_ax.plot(
                                tiempo_corr,
                                Beddy[n, :],
                                'o',
                                markersize=5,
                                color=color,
                                markerfacecolor=color,
                                markeredgecolor=color,
                                markeredgewidth=0.6,
                                alpha=1.0,
                                zorder=point_zorder,
                                label=case_label
                            )
                            legend_added = True
                        else:
                            current_ax.plot(
                                tiempo_corr,
                                Beddy[n, :],
                                'o',
                                markersize=5,
                                color=color,
                                markerfacecolor=color,
                                markeredgecolor=color,
                                markeredgewidth=0.6,
                                alpha=1.0,
                                zorder=point_zorder
                            )

                        if not firstpoint_label_added:
                            y0_measured = Beddy[n, 0]
                            x0 = tiempo_corr[0]
                            current_ax.annotate(
                                f"{y0_measured:.2f}",
                                (x0, y0_measured),
                                textcoords="offset points",
                                xytext=(20, 12),
                                ha='left',
                                fontsize=10,
                                color=color,
                                fontweight='bold'
                            )
                            firstpoint_label_added = True

                        if include_fitted_legend and (not fitted_label_added):
                            current_ax.plot(
                                tiempo_corr,
                                BeddyFitted[n, :],
                                '-',
                                color=color,
                                alpha=0.8,
                                linewidth=line_width,
                                label=f"{case_label}_fitted",
                            )
                            fitted_label_added = True
                        else:
                            current_ax.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8, linewidth=line_width)

                if sim_overlays_list:
                    gradient_token = f"G{g.upper()}"
                    for per_setup in sim_overlays_list:
                        payload = per_setup.get(case_setup, {})
                        sim_curves = (
                            payload.get("curves", {})
                            .get(gradient_token, {})
                            .get(self._canonical_phantom_position(case_phantom), [])
                        )
                        if sim_curves:
                            self._plot_time_domain_simulation_curves(
                                current_ax,
                                sim_curves,
                                label_color_map=sim_label_colors,
                                offset_color_map=sim_offset_colors,
                                linewidth=line_width,
                                spec=payload.get("_spec"),
                            )

        if axes is not None:
            grad_names = ['GX', 'GY', 'GZ']
            for i, ax in enumerate(axes):
                ax.legend(fontsize=9)
                ax.set_title(f"Beddy Measured - {grad_names[i]}", fontsize=13)
                ax.set_xlabel("Time (ms)", fontsize=12)
                ax.set_ylabel("Beddy (µT)", fontsize=12)
                ax.grid(True)
            plt.tight_layout()
        else:
            plt.legend(fontsize=9)
            plt.title(f"Beddy Measured - {gradient}", fontsize=13)
            plt.xlabel("Time (ms)", fontsize=12)
            plt.ylabel("Beddy (µT)", fontsize=12)
            plt.grid(True)
            plt.tight_layout()

        setups_joined = "_".join([c['setup'] for c in cases])
        filtered_tag = "_filtered" if apply_filter else ""
        subplot_tag = "_subplots" if axes is not None else ""
        filename = f"Beddy_measured{filtered_tag}{subplot_tag}_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}.png"
        if save_plot and save_dir and os.path.isdir(save_dir):
            output_path = os.path.join(save_dir, filename)
        else:
            import tempfile
            output_path = os.path.join(tempfile.gettempdir(), filename)
        self._maybe_compact_dimensions(fig)
        self._maybe_customize_legends(fig)
        self._maybe_customize_fonts(fig)
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        if return_figure:
            return output_path, fig
        plt.close(fig)
        return output_path

    def _run_beddy_multi_case_all_phantoms(
        self,
        cases,
        gradient,
        ndelay,
        apply_filter,
        beprefilter_cutoff,
        beprefilter_order,
        colormap="Single-color gradient",
        save_dir=None,
        save_plot=False,
        return_figure=False,
    ):
        import matplotlib.pyplot as plt
        from scipy import signal

        positions = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        base_colors = {'x': 'midnightblue', 'y': 'darkred', 'z': 'darkgreen'}

        palette_colors = self._make_palette_colors(len(cases), colormap)

        include_fitted_legend = bool(apply_filter)

        if gradient == "All":
            grad_list = ['x', 'y', 'z']
        else:
            grad_list = [gradient[-1].lower()]

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

        line_width = self._time_domain_curve_line_width()

        sim_overlays_list = []
        sim_offset_colors = {}
        sim_label_colors = {}
        if self._time_domain_simulation_overlay_requested():
            requested_gradients = ["GX", "GY", "GZ"] if gradient == "All" else [f"G{gradient[-1].upper()}"]
            sim_overlays_list = self._load_time_domain_simulation_overlays(
                cases=cases,
                gradients=requested_gradients,
                locations=positions,
            )
            sim_cmap_name = getattr(self, "_sim_overlay_session_colormap", None) or "Viridis"
            sim_label_colors = self._build_sim_label_color_map(sim_overlays_list, sim_cmap_name)
            all_offset_keys = []
            for per_setup in sim_overlays_list:
                for payload in per_setup.values():
                    for grad_map in payload.get("curves", {}).values():
                        for curve_list in grad_map.values():
                            all_offset_keys.extend(
                                curve.get("offset_key") for curve in curve_list if curve.get("offset_key")
                            )
            sim_offset_colors = self._offset_overlay_color_map(all_offset_keys)

        if gradient == "All":
            fig, axes = plt.subplots(len(positions), 3, figsize=(18, 3 * len(positions)), squeeze=False)
            grad_to_col = {'x': 0, 'y': 1, 'z': 2}
        else:
            fig, axes = plt.subplots(len(positions), 1, figsize=(10, 3 * len(positions)), squeeze=False)
            grad_to_col = {'x': 0, 'y': 0, 'z': 0}

        for pos_idx, position in enumerate(positions):
            plotted_any = {'x': False, 'y': False, 'z': False}

            for case_idx, case in enumerate(cases):
                case_path = case['base_path']
                case_setup = case['setup']
                case_path_tail = os.path.basename(os.path.normpath(case_path))
                folder_path = self._resolve_case_folder_path(case_path, case_setup, position)

                if not os.path.isdir(folder_path):
                    continue

                data_by_axis = {'x': [], 'y': [], 'z': []}
                for fname in os.listdir(folder_path):
                    if not fname.endswith(".mat") or fname.startswith("FID"):
                        continue
                    file_path = os.path.join(folder_path, fname)
                    try:
                        Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, fidsmap, nReadouts = sequenceAnalysis(file_path)
                        g = str(g_axis).lower()

                        BePrefilter = None
                        if apply_filter:
                            gammaB = 42.577e6
                            timeFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)
                            BePrefilter = np.full_like(Be, np.nan)
                            cutoff = float(np.clip(beprefilter_cutoff, 0.01, 0.49))
                            sos = signal.butter(int(beprefilter_order), cutoff, output='sos')

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
                                BePrefilter[n, :] = (1 / (4 * np.pi * gammaB)) * np.gradient(filt_diff, timeFID * 1e-3) * 1e6

                        if g in data_by_axis:
                            data_by_axis[g].append({
                                'tiempo': tiempo,
                                'Beddy': Be,
                                'BeddyFitted': BeddyFitted,
                                'BePrefilter': BePrefilter,
                                'deadTime': deadTime,
                                'acqTime': acqTime,
                            })
                    except Exception:
                        continue

                for g in grad_list:
                    if not data_by_axis[g]:
                        continue

                    plotted_any[g] = True
                    ax = axes[pos_idx, grad_to_col[g]]
                    if palette_colors is not None:
                        color = palette_colors[case_idx]
                    else:
                        lighten_amount = -0.35 + (case_idx / max(1, len(cases) - 1)) * 0.85 if len(cases) > 1 else 0.0
                        color = self._lighten_color(base_colors[g], lighten_amount)

                    legend_added = False
                    prefilter_label_added = False
                    firstpoint_label_added = False
                    fitted_label_added = False
                    case_label = f"G{g.upper()}_{case_setup}_{position}_{case_path_tail}"

                    for data in data_by_axis[g]:
                        tiempo = data['tiempo']
                        Beddy = data['Beddy']
                        BeddyFitted = data['BeddyFitted']
                        BePrefilter = data['BePrefilter']
                        deadTime = data['deadTime']
                        acqTime = data['acqTime']
                        nDelays = Beddy.shape[0]
                        point_zorder = 30 - case_idx

                        if ndelay_selected == "all" or (isinstance(ndelay_selected, int) and ndelay_selected >= nDelays):
                            delay_indices = list(range(nDelays))
                        else:
                            delay_indices = [ndelay_selected]

                        for n in delay_indices:
                            delay_offset = n * (deadTime + acqTime)
                            tiempo_corr = tiempo + delay_offset

                            if apply_filter and BePrefilter is not None:
                                if not prefilter_label_added:
                                    ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=line_width, zorder=10,
                                            label=f"{case_label}_Prefiltered")
                                    prefilter_label_added = True
                                else:
                                    ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=line_width, zorder=10)

                            if not legend_added:
                                ax.plot(tiempo_corr, Beddy[n, :], 'o', markersize=5, color=color, markerfacecolor=color,
                                        markeredgecolor=color, markeredgewidth=0.6, alpha=1.0, zorder=point_zorder,
                                        label=case_label)
                                legend_added = True
                            else:
                                ax.plot(tiempo_corr, Beddy[n, :], 'o', markersize=5, color=color, markerfacecolor=color,
                                        markeredgecolor=color, markeredgewidth=0.6, alpha=1.0, zorder=point_zorder)

                            if not firstpoint_label_added:
                                y0_measured = Beddy[n, 0]
                                x0 = tiempo_corr[0]
                                ax.annotate(f"{y0_measured:.2f}", (x0, y0_measured), textcoords="offset points", xytext=(20, 12),
                                            ha='left', fontsize=9, color=color, fontweight='bold')
                                firstpoint_label_added = True

                            if include_fitted_legend and (not fitted_label_added):
                                ax.plot(
                                    tiempo_corr,
                                    BeddyFitted[n, :],
                                    '-',
                                    color=color,
                                    alpha=0.8,
                                    linewidth=line_width,
                                    label=f"{case_label}_fitted",
                                )
                                fitted_label_added = True
                            else:
                                ax.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8, linewidth=line_width)

                    if sim_overlays_list:
                        gradient_token = f"G{g.upper()}"
                        for per_setup in sim_overlays_list:
                            payload = per_setup.get(case_setup, {})
                            sim_curves = (
                                payload.get("curves", {})
                                .get(gradient_token, {})
                                .get(position, [])
                            )
                            if sim_curves:
                                self._plot_time_domain_simulation_curves(
                                    ax,
                                    sim_curves,
                                    label_color_map=sim_label_colors,
                                    offset_color_map=sim_offset_colors,
                                    linewidth=line_width,
                                    spec=payload.get("_spec"),
                                )

            if gradient == "All":
                for g in ['x', 'y', 'z']:
                    axg = axes[pos_idx, grad_to_col[g]]
                    axg.set_title(f"{position} - G{g.upper()}", fontsize=10)
                    axg.set_xlabel("Time (ms)", fontsize=9)
                    axg.set_ylabel("Beddy (uT)", fontsize=9)
                    axg.grid(True)
                    if plotted_any[g]:
                        axg.legend(fontsize=7)
            else:
                ax = axes[pos_idx, 0]
                ax.set_title(f"{position}", fontsize=11)
                ax.set_xlabel("Time (ms)", fontsize=10)
                ax.set_ylabel("Beddy (uT)", fontsize=10)
                ax.grid(True)
                if any(plotted_any.values()):
                    ax.legend(fontsize=8)

        fig.tight_layout()

        setups_joined = "_".join([c['setup'] for c in cases])
        filtered_tag = "_filtered" if apply_filter else ""
        filename = f"Beddy_measured{filtered_tag}_AllPhantoms_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}.png"
        if save_plot and save_dir and os.path.isdir(save_dir):
            output_path = os.path.join(save_dir, filename)
        else:
            import tempfile
            output_path = os.path.join(tempfile.gettempdir(), filename)

        self._maybe_compact_dimensions(fig)
        self._maybe_customize_legends(fig)
        self._maybe_customize_fonts(fig)
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        if return_figure:
            return output_path, fig
        plt.close(fig)
        return output_path

    def _ask_time_domain_expfit_plot_options(self):
        mode, ok = QInputDialog.getItem(
            self,
            "Exponential fit",
            "Order mode:",
            ["Fixed order", "Auto by RMSE%"],
            0,
            False,
        )
        if not ok:
            return None

        if mode == "Fixed order":
            order, ok = QInputDialog.getInt(
                self,
                "Exponential fit",
                "Fixed order:",
                value=2,
                min=1,
                max=10,
                step=1,
            )
            if not ok:
                return None
            return {"mode": "fixed", "order": int(order), "target": 5.0, "max_order": 8}

        target, ok = QInputDialog.getDouble(
            self,
            "Exponential fit",
            "Target RMSE%:",
            value=5.0,
            min=0.01,
            max=100.0,
            decimals=2,
        )
        if not ok:
            return None
        max_order, ok = QInputDialog.getInt(
            self,
            "Exponential fit",
            "Max order for auto search:",
            value=8,
            min=1,
            max=12,
            step=1,
        )
        if not ok:
            return None
        return {"mode": "auto", "order": 2, "target": float(target), "max_order": int(max_order)}

    def _run_beddy_exponential_fit_plot(
        self,
        cases,
        gradient,
        ndelay,
        options,
        colormap="Single-color gradient",
        use_subplots=False,
        save_dir=None,
        save_plot=False,
        return_figure=False,
    ):
        import matplotlib.pyplot as plt
        import tempfile

        mm = self._load_mat_curve_metrics_module()

        base_colors = {
            'x': 'midnightblue',
            'y': 'darkred',
            'z': 'darkgreen'
        }

        palette_colors = None
        if colormap in ("Viridis", "Inferno") and len(cases) > 0:
            import matplotlib.cm as cm
            cmap = cm.get_cmap(colormap.lower())
            upper = 0.70 if colormap == "Inferno" else 0.85
            sample_range = np.linspace(0.0, upper, len(cases))
            palette_colors = [cmap(pos) for pos in sample_range]

        if gradient == "All":
            grad_list = ['x', 'y', 'z']
        else:
            grad_list = [gradient[-1].lower()]

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

        if use_subplots and gradient == "All":
            fig, axes = plt.subplots(1, 3, figsize=(18, 5))
            fig.subplots_adjust(wspace=0.35)
            grad_to_axis = {'x': 0, 'y': 1, 'z': 2}
        else:
            fig = plt.figure(figsize=(10, 6))
            axes = None
            grad_to_axis = {'x': 0, 'y': 1, 'z': 2}

        plotted_any = False

        for case_idx, case in enumerate(cases):
            case_path = case['base_path']
            case_setup = case['setup']
            case_phantom = case['phantom']
            case_path_tail = os.path.basename(os.path.normpath(case_path))
            folder_path = self._resolve_case_folder_path(case_path, case_setup, case_phantom)

            if not os.path.isdir(folder_path):
                continue

            if palette_colors is not None:
                color_by_axis = {g: palette_colors[case_idx] for g in ['x', 'y', 'z']}
            else:
                lighten_amount = -0.35 + (case_idx / max(1, len(cases) - 1)) * 0.85 if len(cases) > 1 else 0.0
                color_by_axis = {g: self._lighten_color(base_colors[g], lighten_amount) for g in ['x', 'y', 'z']}

            for fname in sorted(os.listdir(folder_path)):
                if not fname.endswith(".mat") or fname.startswith("FID"):
                    continue

                file_path = os.path.join(folder_path, fname)
                try:
                    Be, _, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(file_path)
                except Exception:
                    continue

                g = str(g_axis).strip().lower()
                if g not in grad_list:
                    continue

                Be = np.asarray(Be, dtype=float)
                tiempo = np.asarray(tiempo, dtype=float)
                if Be.ndim != 2 or np.size(tiempo) == 0:
                    continue

                nDelays = int(nDelays)
                if ndelay_selected == "all" or (isinstance(ndelay_selected, int) and ndelay_selected >= nDelays):
                    delay_indices = list(range(nDelays))
                else:
                    delay_indices = [ndelay_selected]

                x_parts = []
                y_parts = []
                for n in delay_indices:
                    delay_offset = float(n) * float(deadTime + acqTime)
                    x_seg = np.asarray(tiempo + delay_offset, dtype=float)
                    y_seg = np.asarray(Be[n, :], dtype=float)
                    finite = np.isfinite(x_seg) & np.isfinite(y_seg)
                    if np.any(finite):
                        x_parts.append(x_seg[finite])
                        y_parts.append(y_seg[finite])

                if not x_parts:
                    continue

                x = np.concatenate(x_parts)
                y = np.concatenate(y_parts)
                order_idx = np.argsort(x)
                x = x[order_idx]
                y = y[order_idx]
                x = x - float(x[0])

                if x.size < 3:
                    continue

                if options["mode"] == "fixed":
                    fit_out = mm.fit_exponentials_orders(x, y, [int(options["order"])])
                    fit_ok = [f for f in fit_out.get("fits", []) if f.get("success", False)]
                    if not fit_ok:
                        continue
                    chosen = fit_ok[0]
                else:
                    mm.TARGET_RMSE_PERCENT = float(options["target"])
                    fit_out = mm.fit_exponentials_orders(x, y, list(range(1, int(options["max_order"]) + 1)))
                    fit_ok = [f for f in fit_out.get("fits", []) if f.get("success", False)]
                    if not fit_ok:
                        continue
                    target_order = fit_out.get("target_order", None)
                    if target_order is None:
                        chosen = min(fit_ok, key=lambda d: float(d.get("rmse_percent", np.inf)))
                    else:
                        chosen = next((f for f in fit_ok if int(f.get("order", -1)) == int(target_order)), fit_ok[0])

                if axes is not None:
                    ax = axes[grad_to_axis[g]]
                else:
                    ax = plt.gca()

                plotted_any = True
                case_label = f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}_{os.path.splitext(fname)[0]}"

                ax.plot(
                    x,
                    y,
                    'o',
                    markersize=3.5,
                    color=color_by_axis[g],
                    alpha=0.7,
                    label=case_label,
                )

                coeffs = chosen.get("coefficients", {})
                param_parts = []
                for k in sorted(coeffs.keys()):
                    v = coeffs[k]
                    if isinstance(v, (int, float, np.integer, np.floating)) and np.isfinite(v):
                        param_parts.append(f"{k}={float(v):.4g}")
                param_text = ", ".join(param_parts)
                exp_label = f"{case_label}_exp_fit"
                if param_text:
                    exp_label = f"{exp_label} ({param_text})"

                ax.plot(
                    np.asarray(chosen["x"], dtype=float),
                    np.asarray(chosen["y_fit"], dtype=float),
                    '-',
                    linewidth=2.0,
                    color=color_by_axis[g],
                    alpha=0.95,
                    label=exp_label,
                )

        if not plotted_any:
            plt.close(fig)
            raise ValueError("No valid .mat data found for the selected setup/phantom/gradient selection.")

        if axes is not None:
            grad_names = {'x': 'GX', 'y': 'GY', 'z': 'GZ'}
            for g in ['x', 'y', 'z']:
                ax = axes[grad_to_axis[g]]
                ax.legend(fontsize=8, loc='best')
                ax.set_title(f"Beddy Exponential fit - {grad_names[g]}", fontsize=13)
                ax.set_xlabel("Time (ms)", fontsize=11)
                ax.set_ylabel("Beddy (uT)", fontsize=11)
                ax.grid(True, alpha=0.35)
            fig.tight_layout()
        else:
            plt.legend(fontsize=8, loc='best')
            plt.title(f"Beddy Exponential fit - {gradient}", fontsize=13)
            plt.xlabel("Time (ms)", fontsize=11)
            plt.ylabel("Beddy (uT)", fontsize=11)
            plt.grid(True, alpha=0.35)
            plt.tight_layout()

        setups_joined = "_".join([c['setup'] for c in cases])
        subplot_tag = "_subplots" if axes is not None else ""
        filename = f"Beddy_expfit{subplot_tag}_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}.png"

        if save_plot and save_dir and os.path.isdir(save_dir):
            output_path = os.path.join(save_dir, filename)
        else:
            output_path = os.path.join(tempfile.gettempdir(), filename)

        self._maybe_compact_dimensions(fig)
        self._maybe_customize_legends(fig)
        self._maybe_customize_fonts(fig)
        fig.savefig(output_path, dpi=250, bbox_inches='tight')
        if return_figure:
            return output_path, filename.replace(".png", ""), fig
        plt.close(fig)
        return output_path, filename.replace(".png", "")

    def _run_beddy_exponential_fit_plot_all_phantoms(
        self,
        cases,
        gradient,
        ndelay,
        options,
        colormap="Single-color gradient",
        save_dir=None,
        save_plot=False,
        return_figure=False,
    ):
        import matplotlib.pyplot as plt
        import tempfile

        mm = self._load_mat_curve_metrics_module()
        positions = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        base_colors = {'x': 'midnightblue', 'y': 'darkred', 'z': 'darkgreen'}

        palette_colors = None
        if colormap in ("Viridis", "Inferno") and len(cases) > 0:
            import matplotlib.cm as cm
            cmap = cm.get_cmap(colormap.lower())
            upper = 0.70 if colormap == "Inferno" else 0.85
            sample_range = np.linspace(0.0, upper, len(cases))
            palette_colors = [cmap(pos) for pos in sample_range]

        if gradient == "All":
            grad_list = ['x', 'y', 'z']
            fig, axes = plt.subplots(len(positions), 3, figsize=(18, 3 * len(positions)), squeeze=False)
            grad_to_col = {'x': 0, 'y': 1, 'z': 2}
        else:
            grad_list = [gradient[-1].lower()]
            fig, axes = plt.subplots(len(positions), 1, figsize=(10, 3 * len(positions)), squeeze=False)
            grad_to_col = {'x': 0, 'y': 0, 'z': 0}

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

        plotted_any = False

        for pos_idx, position in enumerate(positions):
            per_grad_plotted = {'x': False, 'y': False, 'z': False}

            for case_idx, case in enumerate(cases):
                case_path = case['base_path']
                case_setup = case['setup']
                case_path_tail = os.path.basename(os.path.normpath(case_path))
                folder_path = self._resolve_case_folder_path(case_path, case_setup, position)
                if not os.path.isdir(folder_path):
                    continue

                color_by_axis = {}
                if palette_colors is not None:
                    for g in ['x', 'y', 'z']:
                        color_by_axis[g] = palette_colors[case_idx]
                else:
                    lighten_amount = -0.35 + (case_idx / max(1, len(cases) - 1)) * 0.85 if len(cases) > 1 else 0.0
                    for g in ['x', 'y', 'z']:
                        color_by_axis[g] = self._lighten_color(base_colors[g], lighten_amount)

                for fname in sorted(os.listdir(folder_path)):
                    if not fname.endswith('.mat') or fname.startswith('FID'):
                        continue

                    file_path = os.path.join(folder_path, fname)
                    try:
                        Be, _, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(file_path)
                    except Exception:
                        continue

                    g = str(g_axis).strip().lower()
                    if g not in grad_list:
                        continue

                    Be = np.asarray(Be, dtype=float)
                    tiempo = np.asarray(tiempo, dtype=float)
                    if Be.ndim != 2 or np.size(tiempo) == 0:
                        continue

                    nDelays = int(nDelays)
                    if ndelay_selected == "all" or (isinstance(ndelay_selected, int) and ndelay_selected >= nDelays):
                        delay_indices = list(range(nDelays))
                    else:
                        delay_indices = [ndelay_selected]

                    x_parts = []
                    y_parts = []
                    for n in delay_indices:
                        delay_offset = float(n) * float(deadTime + acqTime)
                        x_seg = np.asarray(tiempo + delay_offset, dtype=float)
                        y_seg = np.asarray(Be[n, :], dtype=float)
                        finite = np.isfinite(x_seg) & np.isfinite(y_seg)
                        if np.any(finite):
                            x_parts.append(x_seg[finite])
                            y_parts.append(y_seg[finite])

                    if not x_parts:
                        continue

                    x = np.concatenate(x_parts)
                    y = np.concatenate(y_parts)
                    idx = np.argsort(x)
                    x = x[idx]
                    y = y[idx]
                    x = x - float(x[0])
                    if x.size < 3:
                        continue

                    if options['mode'] == 'fixed':
                        fit_out = mm.fit_exponentials_orders(x, y, [int(options['order'])])
                        fit_ok = [f for f in fit_out.get('fits', []) if f.get('success', False)]
                        if not fit_ok:
                            continue
                        chosen = fit_ok[0]
                    else:
                        mm.TARGET_RMSE_PERCENT = float(options['target'])
                        fit_out = mm.fit_exponentials_orders(x, y, list(range(1, int(options['max_order']) + 1)))
                        fit_ok = [f for f in fit_out.get('fits', []) if f.get('success', False)]
                        if not fit_ok:
                            continue
                        target_order = fit_out.get('target_order', None)
                        if target_order is None:
                            chosen = min(fit_ok, key=lambda d: float(d.get('rmse_percent', np.inf)))
                        else:
                            chosen = next((f for f in fit_ok if int(f.get('order', -1)) == int(target_order)), fit_ok[0])

                    ax = axes[pos_idx, grad_to_col[g]]
                    per_grad_plotted[g] = True
                    plotted_any = True

                    case_label = f"G{g.upper()}_{case_setup}_{position}_{case_path_tail}_{os.path.splitext(fname)[0]}"

                    ax.plot(
                        x,
                        y,
                        'o',
                        markersize=3.5,
                        color=color_by_axis[g],
                        alpha=0.7,
                        label=case_label,
                    )

                    coeffs = chosen.get('coefficients', {})
                    param_parts = []
                    for k in sorted(coeffs.keys()):
                        v = coeffs[k]
                        if isinstance(v, (int, float, np.integer, np.floating)) and np.isfinite(v):
                            param_parts.append(f"{k}={float(v):.4g}")
                    param_text = ", ".join(param_parts)
                    exp_label = f"{case_label}_exp_fit"
                    if param_text:
                        exp_label = f"{exp_label} ({param_text})"

                    ax.plot(
                        np.asarray(chosen['x'], dtype=float),
                        np.asarray(chosen['y_fit'], dtype=float),
                        '-',
                        linewidth=2.0,
                        color=color_by_axis[g],
                        alpha=0.95,
                        label=exp_label,
                    )

            if gradient == 'All':
                for g in ['x', 'y', 'z']:
                    axg = axes[pos_idx, grad_to_col[g]]
                    axg.set_title(f"{position} - G{g.upper()}", fontsize=10)
                    axg.set_xlabel('Time (ms)', fontsize=9)
                    axg.set_ylabel('Beddy (uT)', fontsize=9)
                    axg.grid(True, alpha=0.35)
                    if per_grad_plotted[g]:
                        axg.legend(fontsize=7, loc='best')
            else:
                ax = axes[pos_idx, 0]
                ax.set_title(f"{position}", fontsize=11)
                ax.set_xlabel('Time (ms)', fontsize=10)
                ax.set_ylabel('Beddy (uT)', fontsize=10)
                ax.grid(True, alpha=0.35)
                if any(per_grad_plotted.values()):
                    ax.legend(fontsize=8, loc='best')

        if not plotted_any:
            plt.close(fig)
            raise ValueError('No valid .mat data found for exponential fit in the selected All-phantoms view.')

        fig.tight_layout()
        setups_joined = "_".join([c['setup'] for c in cases])
        filename = f"Beddy_expfit_AllPhantoms_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}.png"

        if save_plot and save_dir and os.path.isdir(save_dir):
            output_path = os.path.join(save_dir, filename)
        else:
            output_path = os.path.join(tempfile.gettempdir(), filename)

        self._maybe_compact_dimensions(fig)
        self._maybe_customize_legends(fig)
        self._maybe_customize_fonts(fig)
        fig.savefig(output_path, dpi=250, bbox_inches='tight')
        if return_figure:
            return output_path, filename.replace('.png', ''), fig
        plt.close(fig)
        return output_path, filename.replace('.png', '')

    def run_analysis(self):

        print(">>> ANALYZE BUTTON CLICKED")

        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        plot_type = self.plot_combo.currentText()
        base_path = self.base_path
        setup = self.setup_combo.currentText()
        self.refresh_plot_phantom_dropdown()
        plot_phantom = self.plot_phantom_combo.currentText().strip()
        if not plot_phantom:
            plot_phantom = self._canonical_phantom_position(self.phantom_combo.currentText())
        forced_all_phantoms = (plot_phantom == "All")
        forced_single_phantom = (plot_phantom not in ("", "All", "Different"))
        forced_phantom_value = self._canonical_phantom_position(plot_phantom) if forced_single_phantom else None
        main_case_phantom = self._canonical_phantom_position(self.phantom_combo.currentText())
        gradient = self.gradient_combo.currentText()
        ndelay = self.ndelay_combo.currentText()
        apply_filter = self.filter_checkbox.isChecked()
        use_exp_fit_plot = bool(getattr(self, "exp_fit_checkbox", None) and self.exp_fit_checkbox.isChecked())
        cutoff_text = self.beprefilter_cutoff_combo.currentText()
        order_text = self.beprefilter_order_combo.currentText()
        try:
            beprefilter_cutoff = float(cutoff_text.split()[0])
        except Exception:
            beprefilter_cutoff = 0.08
        try:
            beprefilter_order = int(order_text)
        except Exception:
            beprefilter_order = 4

        print(f"Plot type: {plot_type}, Gradient: {gradient}, nDelay: {ndelay}, Filter: {apply_filter}, BePrefilter cutoff Wn: {beprefilter_cutoff}, order: {beprefilter_order}")

        try:
            if plot_type == "Beddy":
                active_extra_cases = []
                for case in self.additional_cases:
                    if not case.get('visible', False):
                        continue
                    case_base = case.get('base_path') or case['path_edit'].text().strip()
                    case_setup = case['setup_combo'].currentText()
                    if case_base and case_setup:
                        case_phantom = self._canonical_phantom_position(case['phantom_combo'].currentText())
                        if forced_single_phantom:
                            case_phantom = forced_phantom_value
                        active_extra_cases.append({
                            'base_path': case_base,
                            'setup': case_setup,
                            'phantom': case_phantom
                        })

                use_add_case = len(active_extra_cases) > 0

                if self._time_domain_simulation_overlay_requested():
                    if not self._ensure_sim_overlay_colormap_selected():
                        return

                if use_exp_fit_plot:
                    exp_options = self._ask_time_domain_expfit_plot_options()
                    if exp_options is None:
                        return

                    primary_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                    if use_add_case:
                        cases = [{'base_path': base_path, 'setup': setup, 'phantom': primary_phantom}] + active_extra_cases
                        colormap_choice, ok = QInputDialog.getItem(
                            self,
                            "Select colormap",
                            "Colormap:",
                            ["Single-color gradient", "Viridis", "Inferno"],
                            0,
                            False
                        )
                        if not ok:
                            return
                    else:
                        cases = [{'base_path': base_path, 'setup': setup, 'phantom': primary_phantom}]
                        colormap_choice = "Single-color gradient"

                    use_subplots = bool(gradient == "All")
                    if forced_all_phantoms:
                        img_path, out_name, out_fig = self._run_beddy_exponential_fit_plot_all_phantoms(
                            cases=cases,
                            gradient=gradient,
                            ndelay=ndelay,
                            options=exp_options,
                            colormap=colormap_choice,
                            save_dir=self.comparison_save_dir,
                            save_plot=False,
                            return_figure=True,
                        )
                    else:
                        img_path, out_name, out_fig = self._run_beddy_exponential_fit_plot(
                            cases=cases,
                            gradient=gradient,
                            ndelay=ndelay,
                            options=exp_options,
                            colormap=colormap_choice,
                            use_subplots=use_subplots,
                            save_dir=self.comparison_save_dir,
                            save_plot=False,
                            return_figure=True,
                        )

                    if img_path and os.path.exists(img_path):
                        pix = QPixmap(img_path)
                        self.image_label.setPixmap(pix)
                        self._show_analysis_figure(out_fig)
                        self.current_analysis_figure = out_fig
                        self.current_analysis_image_path = img_path
                        self.current_analysis_filename = out_name
                        self._refresh_compare_measured_columns()
                    return

                # -------------------------------------------------------
                # SESSION-BASED PLOT LOGIC
                # On first Plot (empty session): ask for colormap, create session.
                # On subsequent Plots (session exists): reuse colormap, reuse cases.
                # Add button only appends to session; Plot always uses the full session.
                # -------------------------------------------------------
                primary_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                current_case = {'base_path': base_path, 'setup': setup, 'phantom': primary_phantom}

                use_subplots = (gradient == "All")

                if not self._sim_overlay_session_cases and not use_add_case:
                    # Completely fresh plot with no extra cases — just run single-case
                    # path (existing behavior preserved).
                    if forced_all_phantoms:
                        colormap_choice, ok = QInputDialog.getItem(
                            self, "Select colormap", "Colormap:",
                            ["Single-color gradient", "Viridis", "Inferno"], 0, False)
                        if not ok:
                            return
                        cases = [current_case]
                        img_path, out_fig = self._run_beddy_multi_case_all_phantoms(
                            cases=cases, gradient=gradient, ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            save_dir=self.comparison_save_dir, save_plot=False,
                            return_figure=True)
                    else:
                        single_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                        img_path, out_fig = run_measured_analysis(
                            base_path=base_path, setup=setup,
                            phantom_position=single_phantom,
                            gradient_selected=gradient, nDelay_selected=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order, save_plot=False,
                            return_figure=True)
                else:
                    # Multi-case path (either extra measured cases or sim-overlay session).
                    if use_add_case:
                        cases = [current_case] + active_extra_cases
                    else:
                        cases = [current_case]

                    # Ask measured multi-case colormap only when measured Add case is active.
                    if use_add_case:
                        if not hasattr(self, '_multi_case_colormap') or self._multi_case_colormap is None:
                            colormap_choice, ok = QInputDialog.getItem(
                                self, "Select colormap", "Colormap:",
                                ["Single-color gradient", "Viridis", "Inferno"], 0, False)
                            if not ok:
                                return
                            self._multi_case_colormap = colormap_choice
                            self._plot_session_color_index = 0
                        else:
                            colormap_choice = self._multi_case_colormap
                    else:
                        colormap_choice = self._multi_case_colormap or "Single-color gradient"

                    if forced_all_phantoms:
                        img_path, out_fig = self._run_beddy_multi_case_all_phantoms(
                            cases=cases, gradient=gradient, ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            save_dir=self.comparison_save_dir, save_plot=False,
                            return_figure=True)
                    else:
                        img_path, out_fig = self._run_beddy_multi_case(
                            cases=cases, gradient=gradient, ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            use_subplots=use_subplots,
                            save_dir=self.comparison_save_dir, save_plot=False,
                            return_figure=True)
                
                if img_path and os.path.exists(img_path):
                    pix = QPixmap(img_path)
                    self.image_label.setPixmap(pix)
                    self._show_analysis_figure(out_fig)
                    self.current_analysis_figure = out_fig
                    self.current_analysis_image_path = img_path
                    
                    # Store for later saving
                    if apply_filter:
                        cutoff_tag = f"bw_o{beprefilter_order}_w{int(round(beprefilter_cutoff * 100)):02d}"
                        if use_add_case:
                            setups_joined = "_".join([c['setup'] for c in cases])
                            self.current_analysis_filename = f"Beddy_measured_filtered_{cutoff_tag}_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}"
                        else:
                            self.current_analysis_filename = f"Beddy_measured_filtered_{cutoff_tag}_Grad_{gradient}_nDelay_{ndelay}"
                    else:
                        if use_add_case:
                            setups_joined = "_".join([c['setup'] for c in cases])
                            self.current_analysis_filename = f"Beddy_measured_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}"
                        else:
                            self.current_analysis_filename = f"Beddy_measured_Grad_{gradient}_nDelay_{ndelay}"

                    # Table may have been updated; refresh available measured columns.
                    self._refresh_compare_measured_columns()
                    self._show_time_domain_simulation_warnings()
                
            elif plot_type == "FID":
                if forced_all_phantoms:
                    QMessageBox.warning(self, "Plot", "Phantom position 'All' is only available for Beddy plots.")
                    return
                selected_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                fig = run_fid_analysis(
                    base_path=base_path,
                    setup=setup,
                    phantom_position=selected_phantom,
                    gradient_selected=gradient,
                    nDelay_selected=ndelay,
                    apply_filter=apply_filter
                )
                
                if fig is not None:
                    import tempfile
                    tmp_file = os.path.join(tempfile.gettempdir(), "fid_plot.png")
                    self._maybe_compact_dimensions(fig)
                    self._maybe_customize_legends(fig)
                    self._maybe_customize_fonts(fig)
                    fig.savefig(tmp_file, dpi=200, bbox_inches='tight')
                    pix = QPixmap(tmp_file)
                    self.image_label.setPixmap(pix)
                    self._show_analysis_figure(fig)
                    
                    # Store figure for saving
                    self.current_analysis_figure = fig
                    self.current_analysis_image_path = None
                    if apply_filter:
                        self.current_analysis_filename = f"FID_filtered_Grad_{gradient}_nDelay_{ndelay}"
                    else:
                        self.current_analysis_filename = f"FID_Grad_{gradient}_nDelay_{ndelay}"
                else:
                    QMessageBox.information(self, "Analysis Result", "No FID data found for the selected gradient.")

            elif plot_type == "Phase":
                if forced_all_phantoms:
                    QMessageBox.warning(self, "Plot", "Phantom position 'All' is only available for Beddy plots.")
                    return
                selected_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                fig = run_phase_analysis(
                    base_path=base_path,
                    setup=setup,
                    phantom_position=selected_phantom,
                    gradient_selected=gradient,
                    nDelay_selected=ndelay,
                    apply_filter=apply_filter
                )
                
                if fig is not None:
                    import tempfile
                    tmp_file = os.path.join(tempfile.gettempdir(), "phase_plot.png")
                    self._maybe_compact_dimensions(fig)
                    self._maybe_customize_legends(fig)
                    self._maybe_customize_fonts(fig)
                    fig.savefig(tmp_file, dpi=200, bbox_inches='tight')
                    pix = QPixmap(tmp_file)
                    self.image_label.setPixmap(pix)
                    self._show_analysis_figure(fig)
                    
                    # Store figure for saving
                    self.current_analysis_figure = fig
                    self.current_analysis_image_path = None
                    if apply_filter:
                        self.current_analysis_filename = f"Phase_filtered_Grad_{gradient}_nDelay_{ndelay}"
                    else:
                        self.current_analysis_filename = f"Phase_Grad_{gradient}_nDelay_{ndelay}"
                else:
                    QMessageBox.information(self, "Analysis Result", "No phase data found for the selected gradient.")            
        except Exception as e:
            QMessageBox.critical(self, "Analysis Error", f"An error occurred:\n{e}")
            import traceback
            traceback.print_exc()
        finally:
            self._refresh_compare_measured_columns()

    def run_analysis_all_positions(self):
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        setup = self.setup_combo.currentText()
        if not setup:
            QMessageBox.warning(self, "Warning", "Select Setup first.")
            return

        setup_path = os.path.join(self.base_path, setup)
        if not os.path.isdir(setup_path):
            QMessageBox.warning(self, "Warning", "Setup folder not found.")
            return

        # collect phantom position folders from setup directory
        phantom_positions = [
            name for name in os.listdir(setup_path)
            if os.path.isdir(os.path.join(setup_path, name)) and name != "Experimental_data"
        ]

        if not phantom_positions:
            QMessageBox.information(self, "Analyze all positions", "No phantom position folders found in this setup.")
            return

        # stable ordering with common positions first if present
        preferred = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        ordered = [p for p in preferred if p in phantom_positions] + [p for p in sorted(phantom_positions) if p not in preferred]

        apply_filter = self.filter_checkbox.isChecked()
        cutoff_text = self.beprefilter_cutoff_combo.currentText()
        order_text = self.beprefilter_order_combo.currentText()
        try:
            beprefilter_cutoff = float(cutoff_text.split()[0])
        except Exception:
            beprefilter_cutoff = 0.08
        try:
            beprefilter_order = int(order_text)
        except Exception:
            beprefilter_order = 4

        success = 0
        failed = []

        for phantom in ordered:
            try:
                run_measured_analysis(
                    base_path=self.base_path,
                    setup=setup,
                    phantom_position=phantom,
                    gradient_selected="All",
                    nDelay_selected="All",
                    apply_filter=apply_filter,
                    beprefilter_cutoff=beprefilter_cutoff,
                    beprefilter_order=beprefilter_order
                )
                success += 1
            except Exception as e:
                failed.append(f"{phantom}: {e}")

        if failed:
            msg = (
                f"Full analysis finished with issues.\n"
                f"Processed: {success}/{len(ordered)}\n"
                f"Saved in: {setup_path}\n\n"
                f"Errors:\n" + "\n".join(failed)
            )
            QMessageBox.warning(self, "Analyze all positions", msg)
        else:
            QMessageBox.information(
                self,
                "Analyze all positions",
                f"Full analysis done and saved in:\n{setup_path}"
            )

        self._refresh_compare_measured_columns()



    def open_add_new_files_flow(self):
        choice, ok = QInputDialog.getItem(
            self, "Add new files", "Select method:",
            ["Add manually", "Extract from Experimental_data"],
            0, False
        )
        if not ok:
            return
        if choice == "Add manually":
            dlg = _AddManuallyDialog(self, self)
            dlg.exec_()
        else:
            # User selects the Setup folder that contains Experimental_data
            setup_path = QFileDialog.getExistingDirectory(
                self, "Select Setup folder (the one that contains Experimental_data)"
            )
            if not setup_path:
                return

            base_path = os.path.dirname(setup_path)
            setup = os.path.basename(setup_path)

            # Set GUI state so extract_experimental_files works correctly
            self.base_path = base_path
            self.path_edit.setText(base_path)
            self.settings.setValue("last_base_path", base_path)
            self.update_setup_dropdown()
            self.setup_combo.setCurrentText(setup)

            self.extract_experimental_files()
            reply = QMessageBox.question(
                self, "Analyze files?",
                "Do you want to analyze the newly extracted files?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.run_analysis_all_positions()

    def open_analyze_files_flow(self):
        dlg = _PostprocessAnalyzeDialog(self, self)
        dlg.exec_()


# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EddyCurrentGUI()
    window.show()
    sys.exit(app.exec_())
