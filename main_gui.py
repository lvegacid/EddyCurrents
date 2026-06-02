# -*- coding: utf-8 -*-

import sys
import os

# --- utility to ensure required libraries are installed ---
import subprocess

# force matplotlib to use a non-interactive backend before any pyplot import
# this prevents Qt5Agg from trying to create a second QApplication and
# crashing the GUI when the user requests a plot.  The original problem
# manifested as the entire window closing whenever "Analyze" or other
# plotting actions were triggered.
import matplotlib
matplotlib.use("Agg")

def _ensure_package(pkg_name: str):
    """Import a package, installing it via pip if missing."""
    try:
        __import__(pkg_name)
    except ImportError:
        print(f"Package '{pkg_name}' not found; installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
        try:
            __import__(pkg_name)
        except ImportError as e:
            print(f"Failed to import '{pkg_name}' after installation: {e}")
            raise

# list dependencies used throughout the application
for _pkg in [
    "numpy", "scipy", "matplotlib", "pandas", "PyQt5", "scipy.io"
]:
    _ensure_package(_pkg)

# --- Make script self-contained (fix import path) ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# -----------------------------------------

import shutil
import re
import numpy as np
import pandas as pd

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QMessageBox, QListWidget, QListWidgetItem, QInputDialog,
    QScrollArea, QCheckBox, QRubberBand, QDialog, QGroupBox,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem
)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt, QSettings, QPoint, QRect

from analysis.measured_analysis import (
    run_measured_analysis,
    run_fid_analysis,
    run_phase_analysis,
    extract_filter_metrics_sweep
)
from analysis.compare_with_simulation import compare_with_simulation, load_measured_table
from analysis.sequence_analysis import sequenceAnalysis


# =========================================================
# DRAG & DROP FILE LIST
# =========================================================

class FileList(QListWidget):
    def __init__(self):
        super().__init__()

        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setMinimumHeight(40)
        self.setMaximumHeight(60)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

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
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    self.addItem(file_path)
        else:
            event.ignore()


# subclass used specifically for comparison list so that the
# parent GUI instance can handle the drop event and prompt for a name
class CompareFileList(FileList):
    def __init__(self, gui=None):
        super().__init__()
        # keep a reference to the main GUI so we can call its handler
        self._gui = gui

    def dropEvent(self, event):
        print(f"[CompareFileList] dropEvent triggered")
        # delegate to the GUI method if available; otherwise fallback
        if self._gui is not None:
            print(f"[CompareFileList] Delegating to GUI handler")
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                self._gui.compare_drop_event(event)
            else:
                event.ignore()
        else:
            print(f"[CompareFileList] No GUI - using parent handler")
            super().dropEvent(event)


# =========================================================
# CUSTOM WIDGET FOR COMPARE FILE ITEMS
# =========================================================

class CompareFileItemWidget(QWidget):
    """Custom widget for each item in the compare files list.
    Contains file path, label input field, and control buttons."""

    def __init__(self, file_path, label="", parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.label_input = None
        self.label = label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(8)

        # File name label
        file_name = os.path.basename(file_path)
        file_label = QLabel(file_name)
        file_label.setMaximumWidth(200)
        layout.addWidget(file_label)

        # Label input
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Enter label (gradient name)")
        self.label_input.setText(label)
        self.label_input.setMinimumWidth(150)
        layout.addWidget(self.label_input)

        # Remove button
        remove_btn = QPushButton("Remove")
        remove_btn.setMaximumWidth(80)
        remove_btn.clicked.connect(self.on_remove)
        layout.addWidget(remove_btn)

        layout.addStretch()

        self.remove_callback = None

    def get_label(self):
        """Get the current label from the input field."""
        if self.label_input:
            return self.label_input.text().strip()
        return self.label

    def set_label(self, label):
        """Set the label in the input field."""
        if self.label_input:
            self.label_input.setText(label)
        self.label = label

    def on_remove(self):
        """Trigger removal callback when Remove button is clicked."""
        if self.remove_callback:
            self.remove_callback(self.file_path)

    def sizeHint(self):
        """Return preferred size for this widget."""
        from PyQt5.QtCore import QSize
        return QSize(600, 40)


# =========================================================
# CUSTOM LIST WIDGET FOR COMPARE FILES
# =========================================================

class CompareFileListWidget(QListWidget):
    """Custom QListWidget that accepts drag & drop and notifies GUI."""

    def __init__(self, gui_ref=None, parent=None):
        super().__init__(parent)
        self._gui_ref = gui_ref
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setMaximumHeight(160)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

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


class CopyableTableWidget(QTableWidget):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            selected = self.selectedRanges()
            if not selected:
                return

            pieces = []
            for selection in selected:
                rows = []
                for row in range(selection.topRow(), selection.bottomRow() + 1):
                    values = []
                    for col in range(selection.leftColumn(), selection.rightColumn() + 1):
                        item = self.item(row, col)
                        values.append(item.text() if item is not None else "")
                    rows.append("\t".join(values))
                pieces.append("\n".join(rows))

            QApplication.clipboard().setText("\n".join(pieces))
            return

        super().keyPressEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self._gui_ref and hasattr(self._gui_ref, 'compare_drop_event'):
                self._gui_ref.compare_drop_event(event)
        else:
            event.ignore()


# =========================================================
# WIDGETS
# =========================================================


# =========================================================
# POSTPROCESS DIALOGS
# =========================================================

class _AddManuallyDialog(QDialog):
    """Step-by-step dialog for manually adding files to a position folder."""

    def __init__(self, gui_ref, parent=None):
        super().__init__(parent)
        self._gui = gui_ref
        self.setWindowTitle("Add files manually")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)

        grp1 = QGroupBox("Step 1 – Select parent directory")
        grp1_lay = QHBoxLayout(grp1)
        self._path_edit = QLineEdit()
        self._path_edit.setMinimumWidth(320)
        if gui_ref.base_path:
            self._path_edit.setText(gui_ref.base_path)
        grp1_lay.addWidget(self._path_edit)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_path)
        grp1_lay.addWidget(btn_browse)
        layout.addWidget(grp1)

        grp_setup = QGroupBox("Setup")
        grp_setup_lay = QHBoxLayout(grp_setup)
        self._setup_combo = QComboBox()
        self._setup_combo.setMinimumWidth(200)
        grp_setup_lay.addWidget(self._setup_combo)
        grp_setup_lay.addStretch()
        layout.addWidget(grp_setup)
        self._path_edit.textChanged.connect(self._refresh_setups)
        self._refresh_setups()
        if gui_ref.setup_combo.currentText():
            idx = self._setup_combo.findText(gui_ref.setup_combo.currentText())
            if idx >= 0:
                self._setup_combo.setCurrentIndex(idx)

        grp2 = QGroupBox("Step 2 – Select position")
        grp2_lay = QHBoxLayout(grp2)
        self._pos_combo = QComboBox()
        self._pos_combo.addItems(["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"])
        grp2_lay.addWidget(self._pos_combo)
        grp2_lay.addStretch()
        layout.addWidget(grp2)

        grp3 = QGroupBox("Step 3 – Select files  (Browse or Drag & Drop)")
        grp3_lay = QVBoxLayout(grp3)
        file_btn_row = QHBoxLayout()
        btn_browse_files = QPushButton("Browse files")
        btn_browse_files.clicked.connect(self._browse_files)
        file_btn_row.addWidget(btn_browse_files)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(lambda: self._file_list.clear())
        file_btn_row.addWidget(btn_clear)
        file_btn_row.addStretch()
        grp3_lay.addLayout(file_btn_row)
        self._file_list = FileList()
        self._file_list.setMinimumHeight(80)
        self._file_list.setMaximumHeight(140)
        grp3_lay.addWidget(self._file_list)
        layout.addWidget(grp3)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_confirm = QPushButton("Confirm")
        btn_confirm.setDefault(True)
        btn_confirm.clicked.connect(self._confirm)
        btn_row.addWidget(btn_confirm)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _browse_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select parent directory")
        if folder:
            self._path_edit.setText(folder)

    def _refresh_setups(self):
        self._setup_combo.blockSignals(True)
        prev = self._setup_combo.currentText()
        self._setup_combo.clear()
        path = self._path_edit.text().strip()
        if path and os.path.isdir(path):
            for f in sorted(os.listdir(path)):
                if os.path.isdir(os.path.join(path, f)):
                    self._setup_combo.addItem(f)
        if prev:
            idx = self._setup_combo.findText(prev)
            if idx >= 0:
                self._setup_combo.setCurrentIndex(idx)
        self._setup_combo.blockSignals(False)

    def _browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        for f in files:
            self._file_list.addItem(f)

    def _confirm(self):
        path = self._path_edit.text().strip()
        setup = self._setup_combo.currentText()
        position = self._gui._canonical_phantom_position(self._pos_combo.currentText())
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, "Warning", "Select a valid parent directory.")
            return
        if not setup:
            QMessageBox.warning(self, "Warning", "Select a Setup.")
            return
        if self._file_list.count() == 0:
            QMessageBox.warning(self, "Warning", "No files selected.")
            return
        target_dir = os.path.join(path, setup, position)
        os.makedirs(target_dir, exist_ok=True)
        files_to_copy = [self._file_list.item(i).text() for i in range(self._file_list.count())]
        already_exist = [
            f for f in files_to_copy
            if os.path.exists(os.path.join(target_dir, os.path.basename(f)))
        ]
        if already_exist:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Files already exist")
            msg_box.setText(f"{len(already_exist)} file(s) already exist in:\n{target_dir}")
            msg_box.setInformativeText("Overwrite or Cancel?")
            btn_overwrite = msg_box.addButton("Overwrite", QMessageBox.AcceptRole)
            msg_box.addButton("Cancel", QMessageBox.RejectRole)
            msg_box.exec_()
            if msg_box.clickedButton() is not btn_overwrite:
                return
        try:
            import shutil as _sh
            for f in files_to_copy:
                _sh.copy2(f, os.path.join(target_dir, os.path.basename(f)))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Copy failed:\n{e}")
            return
        self._file_list.clear()
        reply = QMessageBox.question(
            self, "Files added",
            f"{len(files_to_copy)} file(s) copied to:\n{target_dir}\n\nAnalyze files now?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._gui.base_path = path
            self._gui.path_edit.setText(path)
            self._gui.update_setup_dropdown()
            self._gui.setup_combo.setCurrentText(setup)
            self._gui.phantom_combo.setCurrentText(self._pos_combo.currentText())
            self._gui.run_analysis_all_positions()
        self.accept()


class _PostprocessAnalyzeDialog(QDialog):
    """Dialog for the Analyze files postprocess workflow."""

    PREFERRED = ["Center", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]

    def __init__(self, gui_ref, parent=None):
        super().__init__(parent)
        self._gui = gui_ref
        self.setWindowTitle("Analyze files")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)

        # Step 1 — parent folder (base path)
        grp1 = QGroupBox("Step 1 – Select parent folder")
        grp1_lay = QHBoxLayout(grp1)
        self._path_edit = QLineEdit()
        self._path_edit.setMinimumWidth(380)
        self._path_edit.setPlaceholderText("Folder that contains setup subfolders")
        if getattr(self._gui, "base_path", None):
            self._path_edit.setText(self._gui.base_path)
        grp1_lay.addWidget(self._path_edit)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_path)
        grp1_lay.addWidget(btn_browse)
        layout.addWidget(grp1)

        # Step 2 — setup subfolder
        grp2 = QGroupBox("Step 2 – Select subfolder")
        grp2_lay = QHBoxLayout(grp2)
        self._setup_combo = QComboBox()
        self._setup_combo.setMinimumWidth(220)
        grp2_lay.addWidget(self._setup_combo)
        grp2_lay.addStretch()
        layout.addWidget(grp2)

        # Step 3 — position
        grp3 = QGroupBox("Step 3 – Select position")
        grp3_lay = QHBoxLayout(grp3)
        self._pos_combo = QComboBox()
        self._pos_combo.setMinimumWidth(120)
        self._pos_combo.addItems(self.PREFERRED + ["All"])
        grp3_lay.addWidget(self._pos_combo)
        grp3_lay.addStretch()
        layout.addWidget(grp3)

        self._path_edit.textChanged.connect(self._refresh_setups)
        self._setup_combo.currentIndexChanged.connect(self._refresh_positions)
        self._refresh_setups()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        run_btn = QPushButton("Analyze")
        run_btn.setDefault(True)
        run_btn.clicked.connect(self._run)
        btn_row.addWidget(run_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

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
                if os.path.isdir(os.path.join(setup_path, f))
                and f != "Experimental_data"
            ]
            ordered = [p for p in self.PREFERRED if p in existing] + \
                      [p for p in sorted(existing) if p not in self.PREFERRED]
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

        # update main GUI state silently (block signals to avoid crashes)
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
            beprefilter_cutoff = float(
                self._gui.beprefilter_cutoff_combo.currentText().split()[0])
        except Exception:
            beprefilter_cutoff = 0.08
        try:
            beprefilter_order = int(self._gui.beprefilter_order_combo.currentText())
        except Exception:
            beprefilter_order = 4

        self.accept()   # close dialog before running (avoids event-loop nesting)

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
                        beprefilter_order=beprefilter_order
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
                f"Analysis complete. Processed positions: {success}\nParent folder:\n{parent_path}"
            )


class _ChangeFontDialog(QDialog):
    """Dialog for customizing font sizes and label positions in plots."""

    def __init__(self, fig=None, parent=None):
        super().__init__(parent)
        self.fig = fig
        self.setWindowTitle("Change Font")
        self.setMinimumWidth(550)
        
        layout = QVBoxLayout(self)

        # ===== Label Position Adjustment =====
        pos_group = QGroupBox("Label Position Adjustment")
        pos_layout = QVBoxLayout(pos_group)
        
        pos_desc = QLabel("Adjust label position relative to plotted points (in points)")
        pos_layout.addWidget(pos_desc)
        
        # X offset
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X offset:"))
        self.x_offset_spin = QDoubleSpinBox()
        self.x_offset_spin.setRange(-50, 50)
        self.x_offset_spin.setSingleStep(1)
        self.x_offset_spin.setValue(0)
        x_row.addWidget(self.x_offset_spin)
        x_row.addWidget(QLabel("points"))
        x_row.addStretch()
        pos_layout.addLayout(x_row)
        
        # Y offset
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y offset:"))
        self.y_offset_spin = QDoubleSpinBox()
        self.y_offset_spin.setRange(-50, 50)
        self.y_offset_spin.setSingleStep(1)
        self.y_offset_spin.setValue(12)
        y_row.addWidget(self.y_offset_spin)
        y_row.addWidget(QLabel("points"))
        y_row.addStretch()
        pos_layout.addLayout(y_row)
        
        layout.addWidget(pos_group)

        # ===== Font Size Controls =====
        font_group = QGroupBox("Font Size Customization")
        font_layout = QVBoxLayout(font_group)
        
        font_desc = QLabel("Modify font sizes for various plot elements")
        font_layout.addWidget(font_desc)
        
        # Tick labels
        tick_row = QHBoxLayout()
        tick_row.addWidget(QLabel("Tick labels fontsize:"))
        self.tick_fontsize_spin = QSpinBox()
        self.tick_fontsize_spin.setRange(1, 50)
        self.tick_fontsize_spin.setValue(10)
        tick_row.addWidget(self.tick_fontsize_spin)
        tick_row.addStretch()
        font_layout.addLayout(tick_row)
        
        # Axis labels
        axis_row = QHBoxLayout()
        axis_row.addWidget(QLabel("Axis labels fontsize:"))
        self.axis_fontsize_spin = QSpinBox()
        self.axis_fontsize_spin.setRange(1, 50)
        self.axis_fontsize_spin.setValue(12)
        axis_row.addWidget(self.axis_fontsize_spin)
        axis_row.addStretch()
        font_layout.addLayout(axis_row)
        
        # Title
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title fontsize:"))
        self.title_fontsize_spin = QSpinBox()
        self.title_fontsize_spin.setRange(1, 50)
        self.title_fontsize_spin.setValue(13)
        title_row.addWidget(self.title_fontsize_spin)
        title_row.addStretch()
        font_layout.addLayout(title_row)
        
        # Legend
        legend_row = QHBoxLayout()
        legend_row.addWidget(QLabel("Legend fontsize:"))
        self.legend_fontsize_spin = QSpinBox()
        self.legend_fontsize_spin.setRange(1, 50)
        self.legend_fontsize_spin.setValue(11)
        legend_row.addWidget(self.legend_fontsize_spin)
        legend_row.addStretch()
        font_layout.addLayout(legend_row)
        
        # Point labels/annotations
        annot_row = QHBoxLayout()
        annot_row.addWidget(QLabel("Point labels/annotations fontsize:"))
        self.annot_fontsize_spin = QSpinBox()
        self.annot_fontsize_spin.setRange(1, 50)
        self.annot_fontsize_spin.setValue(11)
        annot_row.addWidget(self.annot_fontsize_spin)
        annot_row.addStretch()
        font_layout.addLayout(annot_row)
        
        layout.addWidget(font_group)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.apply_changes)
        btn_row.addWidget(apply_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        
        layout.addLayout(btn_row)

    def apply_changes(self):
        """Apply the font customizations to the figure."""
        if self.fig is None:
            self.accept()
            return

        try:
            # Get values from spinboxes
            x_offset = self.x_offset_spin.value()
            y_offset = self.y_offset_spin.value()
            tick_size = self.tick_fontsize_spin.value()
            axis_size = self.axis_fontsize_spin.value()
            title_size = self.title_fontsize_spin.value()
            legend_size = self.legend_fontsize_spin.value()
            annot_size = self.annot_fontsize_spin.value()

            # Apply font sizes to all axes
            for ax in self.fig.axes:
                # Set tick label font size
                ax.tick_params(axis='both', which='major', labelsize=tick_size)
                for label in ax.get_xticklabels():
                    label.set_fontsize(tick_size)
                for label in ax.get_yticklabels():
                    label.set_fontsize(tick_size)

                # Set axis label font size
                ax.xaxis.label.set_fontsize(axis_size)
                ax.yaxis.label.set_fontsize(axis_size)

                # Set title font size
                ax.title.set_fontsize(title_size)

                # Set legend font size
                legend = ax.get_legend()
                if legend:
                    for text in legend.get_texts():
                        text.set_fontsize(legend_size)

                # Update all text annotations (point labels)
                for text_obj in ax.texts:
                    current_fontsize = text_obj.get_fontsize()
                    # If it's an annotation, update it
                    if current_fontsize is not None:
                        text_obj.set_fontsize(annot_size)
                    
                    # Apply label position offset
                    if hasattr(text_obj, 'get_position'):
                        # For annotations, try to update xytext if available
                        try:
                            # This is a bit tricky - we need to update the annotation's offset
                            if hasattr(text_obj, 'xytext'):
                                # Relative to original, apply offset
                                text_obj.xytext = (x_offset, y_offset)
                        except:
                            pass

            self.fig.canvas.draw_idle()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply changes:\n{e}")


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
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

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
        else:
            self._view_rect = QRect()
        self._rubber_band.hide()
        self._update_scaled()

    def reset_zoom(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return
        self._view_rect = QRect(0, 0, self._orig_pixmap.width(), self._orig_pixmap.height())
        self._rubber_band.hide()
        self._update_scaled()

    def wheelEvent(self, event):
        if self._orig_pixmap is None or self._orig_pixmap.isNull() or self._view_rect.isNull():
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        zoom_factor = 1 / 1.15 if delta > 0 else 1.15
        focus_x, focus_y = self._map_label_point_to_image(event.pos())
        self._zoom_around_point(focus_x, focus_y, zoom_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
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

        view_w = max(1, self._view_rect.width())
        view_h = max(1, self._view_rect.height())
        label_w = max(1, self.width())
        label_h = max(1, self.height())

        scale = min(label_w / view_w, label_h / view_h)
        disp_w = max(1, int(round(view_w * scale)))
        disp_h = max(1, int(round(view_h * scale)))
        left = int(round((label_w - disp_w) / 2))
        top = int(round((label_h - disp_h) / 2))
        return QRect(left, top, disp_w, disp_h)

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
        scaled = cropped.scaled(
            max(1, self.width()),
            max(1, self.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        super().setPixmap(scaled)


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
        self.analyze_change_font_checkbox = QCheckBox("Change font")
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

        compare_row.addWidget(QLabel("Measured column"))
        self.compare_meas_combo = QComboBox()
        self.compare_meas_combo.addItems([
            "B_measured_at_t0_FirstPoint",
            "B_measured_at_t0_Fitted",
            "B_measured_at_t0_PreFiltered",
            "B_integrated",
            "B_integrated_1ms",
            "B_integrated_5ms",
            "B_integrated_10ms",
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
        self.change_font_checkbox = QCheckBox("Change font")
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
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(300)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
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

    def _refresh_compare_measured_columns(self):
        if not hasattr(self, "compare_meas_combo"):
            return

        previous = self.compare_meas_combo.currentText().strip()
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
                "B_integrated_5ms",
                "B_integrated_10ms",
            ]

        self.compare_meas_combo.blockSignals(True)
        self.compare_meas_combo.clear()
        self.compare_meas_combo.addItems(columns)
        if previous and previous in columns:
            self.compare_meas_combo.setCurrentText(previous)
        self.compare_meas_combo.blockSignals(False)

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
        n_cols = 3
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
            figsize=(18, max(4.5, 3.8 * n_rows)),
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

        colors_palette = [
            'royalblue', 'firebrick', 'green', 
            'orange', 'purple', 'brown', 'pink', 'gray'
        ]

        fig = plt.figure(figsize=(10, 6))
        any_legend = False

        for file_idx, (path, label) in enumerate(self.compare_items):
            try:
                Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(path)
                color = colors_palette[file_idx % len(colors_palette)]
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

                    plt.plot(tiempo_corr, BeddyFitted[n, :], '-',
                             color=color, alpha=0.8)

                    if n == 0:
                        y0_measured = Be[n, 0]
                        y0_fitted = BeddyFitted[n, 0]
                        x0 = tiempo_corr[0]

                        plt.annotate(f"{y0_measured:.2f}",
                                     (x0, y0_measured),
                                     textcoords="offset points", xytext=(0, 12),
                                     ha='center', fontsize=11, color=color, fontweight='bold')

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
            
            # Define distinct colors for each file
            colors_palette = [
                'royalblue', 'firebrick', 'green', 
                'orange', 'purple', 'brown', 'pink', 'gray'
            ]
            
            plt.figure(figsize=(10, 6))
            
            any_legend = False
            for file_idx, (path, label) in enumerate(self.compare_items):
                try:
                    print(f"[DEBUG] Plotting: {label} from {path}")
                    Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime, _, _ = sequenceAnalysis(path)
                    
                    # Pick a color for this file
                    color = colors_palette[file_idx % len(colors_palette)]
                    
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
                        plt.plot(tiempo_corr, BeddyFitted[n, :], '-', 
                               color=color, alpha=0.8)
                        
                        # Annotate only first point of first delay (n=0)
                        if n == 0:
                            y0_measured = Be[n, 0]
                            y0_fitted = BeddyFitted[n, 0]
                            x0 = tiempo_corr[0]
                            
                            # Measured value in file color (bold)
                            plt.annotate(f"{y0_measured:.2f}",
                                       (x0, y0_measured),
                                       textcoords="offset points", xytext=(0, 12),
                                       ha='center', fontsize=11, color=color, fontweight='bold')
                            
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
        # restore zoom on the image label
        if isinstance(self.image_label, ZoomLabel):
            self.image_label.reset_zoom()

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

        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is None:
                continue

            text_items = legend.get_texts()
            if not text_items:
                continue

            if len(labels) == 1:
                for txt_obj in text_items:
                    txt_obj.set_text(labels[0])
                continue

            mapping = {}
            next_idx = 0
            for txt_obj in text_items:
                current = txt_obj.get_text().strip()
                if current not in mapping:
                    if next_idx < len(labels):
                        mapping[current] = labels[next_idx]
                        next_idx += 1
                    else:
                        mapping[current] = current
                txt_obj.set_text(mapping[current])

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

    def _maybe_customize_fonts(self, fig):
        """Optionally apply one global font size to all plot text elements."""
        if fig is None:
            return

        compare_checkbox = getattr(self, "change_font_checkbox", None)
        analyze_checkbox = getattr(self, "analyze_change_font_checkbox", None)

        compare_checked = bool(compare_checkbox and compare_checkbox.isChecked())
        analyze_checked = bool(analyze_checkbox and analyze_checkbox.isChecked())
        if not (compare_checked or analyze_checked):
            return

        try:
            font_size, ok = QInputDialog.getInt(
                self,
                "Change Font",
                "Global font size:",
                value=12,
                min=1,
                max=72,
                step=1,
            )
            if not ok:
                return

            # Apply the same size everywhere (titles, labels, ticks, legends, annotations).
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

                for txt in ax.texts:
                    txt.set_fontsize(font_size)

            if getattr(fig, "_suptitle", None) is not None:
                fig._suptitle.set_fontsize(font_size)

            for txt in fig.texts:
                txt.set_fontsize(font_size)

            fig.canvas.draw_idle()
        except Exception as e:
            QMessageBox.warning(self, "Font Customization", f"Error: {e}")

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

        # Collect ALL available metric columns (not just the currently selected one)
        all_measured_columns = [
            self.compare_meas_combo.itemText(i)
            for i in range(self.compare_meas_combo.count())
            if self.compare_meas_combo.itemText(i).strip()
        ]
        if not all_measured_columns:
            QMessageBox.warning(self, "Warning", "No measured columns available.")
            return

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

            frames = self._build_single_value_metrics_frames(
                compare_cases=compare_cases,
                gradient=gradient,
                measured_columns=all_measured_columns,
                custom_labels=custom_hist_labels,
            )

            self.current_analysis_figure = None
            self.current_analysis_image_path = None
            self.current_analysis_table_frames = frames
            self.current_analysis_table_filename = (
                f"Measurements_{'vs_simulations_' if compare_with_sim else ''}"
                f"G{gradient}_AllMetrics_Table"
            )
            self.current_analysis_filename = self.current_analysis_table_filename

            self._show_single_value_metrics_dialog(
                frames,
                title=f"Single-value metrics — G{gradient}",
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
        save_plot=False
    ):
        import matplotlib.pyplot as plt
        from scipy import signal

        base_colors = {
            'x': 'midnightblue',
            'y': 'darkred',
            'z': 'darkgreen'
        }

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
                                current_ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10,
                                         label=f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}_Prefiltered")
                                prefilter_label_added = True
                            else:
                                current_ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10)
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
                                xytext=(0, 12),
                                ha='center',
                                fontsize=10,
                                color=color,
                                fontweight='bold'
                            )
                            firstpoint_label_added = True

                        current_ax.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8)

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
        self._maybe_compact_dimensions(plt.gcf())
        self._maybe_customize_legends(plt.gcf())
        self._maybe_customize_fonts(plt.gcf())
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
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
        save_plot=False
    ):
        import matplotlib.pyplot as plt
        from scipy import signal

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
        else:
            grad_list = [gradient[-1].lower()]

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

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
                                    ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10,
                                            label=f"{case_label}_Prefiltered")
                                    prefilter_label_added = True
                                else:
                                    ax.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10)

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
                                ax.annotate(f"{y0_measured:.2f}", (x0, y0_measured), textcoords="offset points", xytext=(0, 12),
                                            ha='center', fontsize=9, color=color, fontweight='bold')
                                firstpoint_label_added = True

                            ax.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8)

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
        plt.close(fig)
        return output_path

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

                if use_add_case:
                    primary_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
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

                    use_subplots = False
                    if gradient == "All":
                        use_subplots = True

                    if forced_all_phantoms:
                        img_path = self._run_beddy_multi_case_all_phantoms(
                            cases=cases,
                            gradient=gradient,
                            ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            save_dir=self.comparison_save_dir,
                            save_plot=False
                        )
                    else:
                        img_path = self._run_beddy_multi_case(
                            cases=cases,
                            gradient=gradient,
                            ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            use_subplots=use_subplots,
                            save_dir=self.comparison_save_dir,
                            save_plot=False
                        )
                else:
                    # Original single-case Beddy analysis
                    if forced_all_phantoms:
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
                        cases = [{'base_path': base_path, 'setup': setup, 'phantom': main_case_phantom}]
                        img_path = self._run_beddy_multi_case_all_phantoms(
                            cases=cases,
                            gradient=gradient,
                            ndelay=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            colormap=colormap_choice,
                            save_dir=self.comparison_save_dir,
                            save_plot=False
                        )
                    else:
                        single_phantom = forced_phantom_value if forced_single_phantom else main_case_phantom
                        img_path = run_measured_analysis(
                            base_path=base_path,
                            setup=setup,
                            phantom_position=single_phantom,
                            gradient_selected=gradient,
                            nDelay_selected=ndelay,
                            apply_filter=apply_filter,
                            beprefilter_cutoff=beprefilter_cutoff,
                            beprefilter_order=beprefilter_order,
                            save_plot=False
                        )
                
                if img_path and os.path.exists(img_path):
                    # Load the figure for saving
                    pix = QPixmap(img_path)
                    self.image_label.setPixmap(pix)
                    self.current_analysis_figure = None
                    self.current_analysis_image_path = img_path
                    
                    # Store for later saving
                    import matplotlib.pyplot as plt
                    # Create a temporary figure from the saved image
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
