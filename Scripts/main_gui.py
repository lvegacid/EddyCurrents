# -*- coding: utf-8 -*-

import sys
import os

# --- utility to ensure required libraries are installed ---
import subprocess

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

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QMessageBox, QListWidget, QInputDialog,
    QScrollArea, QCheckBox
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QSettings

from analysis.measured_analysis import (
    run_measured_analysis,
    run_fid_analysis,
    run_phase_analysis,
    extract_filter_metrics_sweep
)
from analysis.compare_with_simulation import compare_with_simulation
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
# WIDGETS
# =========================================================


class ZoomLabel(QLabel):
    """QLabel that supports mouse-wheel zooming of its pixmap.

    The image is initially scaled to fit the label; subsequent wheel
    events zoom relative to that fit size.  Resizing the label will
    recompute the fit size only when the user has not zoomed manually.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._orig_pixmap = None
        self.scale_factor = 1.0
        self.fit_factor = 1.0

    def setPixmap(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        # compute fit factor based on current label dimensions
        if pixmap and self.width() > 0 and self.height() > 0:
            w_ratio = self.width() / pixmap.width()
            h_ratio = self.height() / pixmap.height()
            self.fit_factor = min(w_ratio, h_ratio)
        else:
            self.fit_factor = 1.0
        self.scale_factor = self.fit_factor
        self._update_scaled()

    def wheelEvent(self, event):
        if self._orig_pixmap is None:
            return
        delta = event.angleDelta().y()
        if delta > 0:
            self.scale_factor *= 1.1
        else:
            self.scale_factor *= 0.9
        self._update_scaled()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.pos()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_pos'):
            dx = event.x() - self._drag_pos.x()
            dy = event.y() - self._drag_pos.y()
            parent = self.parent()
            # if contained in a scroll area, adjust its scroll bars
            from PyQt5.QtWidgets import QScrollArea
            if isinstance(parent, QScrollArea):
                hbar = parent.horizontalScrollBar()
                vbar = parent.verticalScrollBar()
                hbar.setValue(hbar.value() - dx)
                vbar.setValue(vbar.value() - dy)
            self._drag_pos = event.pos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # only recompute fit if we're currently at the fit scale
        if abs(self.scale_factor - self.fit_factor) < 1e-6:
            self.setPixmap(self._orig_pixmap)

    def _update_scaled(self):
        if self._orig_pixmap is None:
            return
        size = self._orig_pixmap.size()
        new_size = size * self.scale_factor
        scaled = self._orig_pixmap.scaled(
            new_size,
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
        # track files and labels for plot comparison
        self.compare_items = []  # list of (path, label) tuples
        # track current analysis figure for saving
        self.current_analysis_figure = None
        self.current_analysis_filename = None
        self.current_analysis_image_path = None

        # create layouts first; widgets will follow
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # ======================================================
        # ================== SELECT FILES ======================
        # ======================================================

        select_label = QLabel("SELECT FILES")
        select_label.setStyleSheet("font-weight: bold; color: red;")
        main_layout.addWidget(select_label)

        config_row = QHBoxLayout()
        main_layout.addLayout(config_row)

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
        config_row.addWidget(self.phantom_combo)

        config_row.addStretch()

        add_case_row = QHBoxLayout()
        main_layout.addLayout(add_case_row)
        self.add_case_btn = QPushButton("Add case")
        self.add_case_btn.clicked.connect(self.add_case)
        add_case_row.addWidget(self.add_case_btn)

        add_case_row.addWidget(QLabel("Path to save comparison"))

        self.browse_save_comparison_btn = QPushButton("Browse")
        self.browse_save_comparison_btn.clicked.connect(self.select_comparison_save_dir)
        add_case_row.addWidget(self.browse_save_comparison_btn)

        self.save_comparison_path_edit = QLineEdit()
        self.save_comparison_path_edit.setReadOnly(True)
        self.save_comparison_path_edit.setMinimumWidth(260)
        self.save_comparison_path_edit.setPlaceholderText("Path to save comparison")
        add_case_row.addWidget(self.save_comparison_path_edit)

        add_case_row.addStretch()

        self.add_cases_container = QVBoxLayout()
        main_layout.addLayout(self.add_cases_container)

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
        self.case2_row.addWidget(self.setup2_combo)
        self.case2_widgets.append(self.setup2_combo)

        self.case2_row.addSpacing(20)

        lbl_phantom2 = QLabel("Phantom position2")
        self.case2_row.addWidget(lbl_phantom2)
        self.case2_widgets.append(lbl_phantom2)

        self.phantom2_combo = QComboBox()
        self.case2_row.addWidget(self.phantom2_combo)
        self.case2_widgets.append(self.phantom2_combo)

        delete_case2_btn = QPushButton("Delete")
        self.case2_row.addWidget(delete_case2_btn)
        self.case2_widgets.append(delete_case2_btn)

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
            'delete_btn': delete_case2_btn,
            'widgets': self.case2_widgets,
            'visible': False
        })

        delete_case2_btn.clicked.connect(lambda _=False: self.delete_case(2))

        # ======================================================
        # ================== ADD FILES =========================
        # ======================================================

        add_label = QLabel("ADD FILES")
        add_label.setStyleSheet("font-weight: bold; color: red;")
        main_layout.addWidget(add_label)

        files_layout = QVBoxLayout()
        main_layout.addLayout(files_layout)

        button_row = QHBoxLayout()
        files_layout.addLayout(button_row)

        browse_files_btn = QPushButton("Browse")
        browse_files_btn.clicked.connect(self.browse_files)
        button_row.addWidget(browse_files_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.file_list_clear_safe)
        button_row.addWidget(clear_btn)

        button_row.addStretch()

        confirm_btn = QPushButton("Confirm")
        confirm_btn.clicked.connect(self.confirm_upload)
        button_row.addWidget(confirm_btn)

        extract_btn = QPushButton("Extract from Experimental_data")
        extract_btn.clicked.connect(self.extract_experimental_files)
        button_row.addWidget(extract_btn)

        self.file_list = FileList()
        files_layout.addWidget(self.file_list)

        # ======================================================
        # ================== ANALYZE DATA ======================
        # ======================================================

        analyze_label = QLabel("ANALYZE DATA")
        analyze_label.setStyleSheet("font-weight: bold; color: red;")
        main_layout.addWidget(analyze_label)

        analyze_row = QHBoxLayout()
        main_layout.addLayout(analyze_row)

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

        analyze_row.addStretch()

        analyze_btn = QPushButton("Analyze")
        analyze_btn.clicked.connect(self.run_analysis)
        analyze_row.addWidget(analyze_btn)

        analyze_all_btn = QPushButton("Analyze all positions")
        analyze_all_btn.clicked.connect(self.run_analysis_all_positions)
        analyze_row.addWidget(analyze_all_btn)

        save_plot_btn = QPushButton("Save plot")
        save_plot_btn.clicked.connect(self.save_current_analysis_plot)
        analyze_row.addWidget(save_plot_btn)

        extract_metrics_btn = QPushButton("Extract filter metrics")
        extract_metrics_btn.clicked.connect(self.extract_filter_metrics)
        analyze_row.addWidget(extract_metrics_btn)

        reset_zoom_btn = QPushButton("Reset Zoom")
        reset_zoom_btn.clicked.connect(self.reset_zoom)
        analyze_row.addWidget(reset_zoom_btn)

        # ======================================================
        # ================== COMPARE WITH SIM ==================
        # ======================================================

        compare_label = QLabel("COMPARE WITH SIMULATION")
        compare_label.setStyleSheet("font-weight: bold; color: blue;")
        main_layout.addWidget(compare_label)

        compare_row = QHBoxLayout()
        main_layout.addLayout(compare_row)

        compare_row.addWidget(QLabel("Gradient"))
        self.compare_grad_combo = QComboBox()
        self.compare_grad_combo.addItems(["X", "Y", "Z"])
        compare_row.addWidget(self.compare_grad_combo)

        compare_row.addSpacing(20)

        compare_row.addWidget(QLabel("Measured column"))
        self.compare_meas_combo = QComboBox()
        self.compare_meas_combo.addItems([
            "B_measured_at_t0_FirstPoint",
            "B_measured_at_t0_Fitted"
        ])
        compare_row.addWidget(self.compare_meas_combo)

        compare_row.addSpacing(20)

        compare_row.addWidget(QLabel("Plot type"))
        self.compare_plot_combo = QComboBox()
        self.compare_plot_combo.addItems(["Points", "Histograms"])
        compare_row.addWidget(self.compare_plot_combo)

        compare_row.addStretch()

        compare_btn = QPushButton("Compare")
        compare_btn.clicked.connect(self.run_comparison)
        compare_row.addWidget(compare_btn)

        # space for image preview (zoomable + pannable)
        self.image_label = ZoomLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(300)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.image_label)
        main_layout.addWidget(scroll)

        # ======================================================
        # ================== COMPARE PLOTS =====================
        # ======================================================

        compare_plots_label = QLabel("COMPARE PLOTS")
        compare_plots_label.setStyleSheet("font-weight: bold; color: purple;")
        main_layout.addWidget(compare_plots_label)

        cp_layout = QVBoxLayout()
        main_layout.addLayout(cp_layout)

        cp_button_row = QHBoxLayout()
        cp_layout.addLayout(cp_button_row)

        cp_clear_btn = QPushButton("Clear")
        cp_clear_btn.clicked.connect(self.clear_compare_files)
        cp_button_row.addWidget(cp_clear_btn)

        save_btn = QPushButton("Save plot")
        save_btn.clicked.connect(self.save_compare_plot)
        cp_button_row.addWidget(save_btn)

        cp_button_row.addStretch()

        # file list for dragged comparison files
        # specialized list that hands drops back to the GUI for labeling
        self.compare_file_list = CompareFileList(self)
        cp_layout.addWidget(self.compare_file_list)

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

    def add_case(self):
        self.add_case_enabled = True

        hidden_cases = [c for c in self.additional_cases if not c['visible']]
        if hidden_cases:
            case = hidden_cases[0]
            for widget in case['widgets']:
                widget.setVisible(True)
            case['visible'] = True
            if case['index'] == 2:
                self.update_setup_dropdown_case2()
                self.update_phantom_dropdown_case2()
            return

        self._create_dynamic_case_row()

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
        row.addWidget(phantom_combo)
        widgets.append(phantom_combo)

        delete_btn = QPushButton("Delete")
        row.addWidget(delete_btn)
        widgets.append(delete_btn)

        row.addStretch()

        case = {
            'index': case_index,
            'base_path': None,
            'row': row,
            'path_edit': path_edit,
            'setup_combo': setup_combo,
            'phantom_combo': phantom_combo,
            'delete_btn': delete_btn,
            'widgets': widgets,
            'visible': True
        }

        browse_btn.clicked.connect(lambda _=False, c=case: self.select_base_path_case(c))
        setup_combo.currentIndexChanged.connect(lambda _=0, c=case: self.update_phantom_dropdown_case(c))
        delete_btn.clicked.connect(lambda _=False, idx=case_index: self.delete_case(idx))

        self.additional_cases.append(case)
        self.update_setup_dropdown_case(case)
        self.update_phantom_dropdown_case(case)

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

    def select_comparison_save_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder to save comparison plots")
        if folder:
            self.comparison_save_dir = folder
            self.save_comparison_path_edit.setText(folder)

    def delete_case(self, case_index):
        case = next((c for c in self.additional_cases if c['index'] == case_index), None)
        if case is None:
            return

        case['base_path'] = None
        case['path_edit'].clear()
        case['setup_combo'].clear()
        case['phantom_combo'].clear()
        case['visible'] = False

        for widget in case['widgets']:
            widget.setVisible(False)

        if case_index == 2:
            self.base_path2 = None

        if not any(c.get('visible', False) for c in self.additional_cases):
            self.add_case_enabled = False

    def update_setup_dropdown(self):
        self.setup_combo.clear()
        if not self.base_path or not os.path.isdir(self.base_path):
            return
        folders = [
            f for f in os.listdir(self.base_path)
            if os.path.isdir(os.path.join(self.base_path, f))
        ]
        self.setup_combo.addItems(folders)

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
            self.phantom_combo.addItems(sorted(candidates))
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
            combo.addItems(sorted(candidates))
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

        phantom_position = self.phantom_combo.currentText()

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
            # ensure case conventions: 'center' capitalized, others uppercased
            if p.lower() == 'center':
                return 'Center'
            return p.upper()

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

        setup = self.setup_combo.currentText()
        gradient = self.compare_grad_combo.currentText()
        measured_column = self.compare_meas_combo.currentText()
        selected_plot_type = self.compare_plot_combo.currentText()
        gradient_token = f"G{gradient}"

        save_dir = (self.save_comparison_path_edit.text() or "").strip()
        if not save_dir:
            QMessageBox.warning(self, "Warning", "Fill 'Path to save comparison' first.")
            return
        if not os.path.isdir(save_dir):
            QMessageBox.warning(self, "Warning", "'Path to save comparison' is not a valid folder.")
            return

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
                case_phantom = case['phantom_combo'].currentText()
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

            fig = compare_with_simulation(
                base_path=self.base_path,
                setup=setup,
                gradient=gradient,
                measured_column=measured_column,
                plot_type=selected_plot_type,
                save_figure=False,  # don't save twice
                cases=compare_cases
            )

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

            # Auto-save with requested naming convention
            auto_filename = (
                f"Measurements_vs_simulations_{gradient_token}_"
                f"{plot_type_token}_{measured_column}_{case_tag}.png"
            )
            auto_save_path = os.path.join(save_dir, auto_filename)
            fig.savefig(auto_save_path, dpi=300)

            # Save to temporary image and display in your ZoomLabel
            temp_path = os.path.join(self.base_path, setup, "temp_compare.png")
            fig.savefig(temp_path, dpi=200)
            import matplotlib.pyplot as plt
            plt.close(fig)  # close the figure to avoid memory issues

            pix = QPixmap(temp_path)
            self.image_label.setPixmap(pix)
            
            QMessageBox.information(
                self,
                "Success",
                f"Comparison plot generated and saved to:\n{auto_save_path}"
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

    # ---------------------------------------------------------
    # compare plots support methods
    # ---------------------------------------------------------

    def compare_drop_event(self, event):
        """Handle files dropped into the compare-files list."""
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
                
                if not file_path.lower().endswith(('.mat', '.m')):
                    print(f"[DEBUG]   - Not .mat or .m")
                    continue
                
                print(f"[DEBUG]   - Asking for name...")
                name, ok = QInputDialog.getText(
                    self,
                    "Name for plot",
                    f"Enter a name/legend for '{os.path.basename(file_path)}':"
                )
                
                if ok and name.strip():
                    label = name.strip()
                    self.compare_items.append((file_path, label))
                    self.compare_file_list.addItem(f"{label} : {file_path}")
                    added_count += 1
                    print(f"[DEBUG]   - Added as '{label}'")
            
            if added_count > 0:
                print(f"[DEBUG] Updating plot...")
                self.update_compare_plot()
                
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()

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
                        plt.plot(tiempo_corr, Be[n, :], 'o', markersize=3,
                                 color=color, alpha=0.4, label=label)
                        legend_added = True
                        any_legend = True
                    else:
                        plt.plot(tiempo_corr, Be[n, :], 'o', markersize=3,
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
                fig.savefig(fname, dpi=300)
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
                            plt.plot(tiempo_corr, Be[n, :], 'o', markersize=3, 
                                   color=color, alpha=0.4, label=label)
                            legend_added = True
                            any_legend = True
                        else:
                            plt.plot(tiempo_corr, Be[n, :], 'o', markersize=3, 
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
            
            # Save to temporary file and display
            import tempfile, os
            tmp_file = os.path.join(tempfile.gettempdir(), "compare_plot.png")
            plt.savefig(tmp_file, dpi=300)
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
        if isinstance(self.image_label, ZoomLabel) and self.image_label._orig_pixmap:
            self.image_label.setPixmap(self.image_label._orig_pixmap)

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
        has_figure = self.current_analysis_figure is not None
        has_image = self.current_analysis_image_path is not None and os.path.exists(self.current_analysis_image_path)

        if not has_figure and not has_image:
            pix = self.image_label.pixmap() if hasattr(self.image_label, 'pixmap') else None
            has_image = pix is not None and not pix.isNull()

        if not has_figure and not has_image:
            QMessageBox.warning(self, "Save Plot", "No plot to save. Run Analyze first.")
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
                self.current_analysis_figure.savefig(fname, dpi=300)
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

    def extract_filter_metrics(self):
        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        setup = self.setup_combo.currentText()
        phantom = self.phantom_combo.currentText()
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

    def _lighten_color(self, color, amount):
        import matplotlib.colors as mcolors
        rgb = np.array(mcolors.to_rgb(color), dtype=float)
        amount = float(np.clip(amount, 0.0, 1.0))
        new_rgb = rgb + (1.0 - rgb) * amount
        return tuple(new_rgb)

    def _run_beddy_multi_case(
        self,
        cases,
        gradient,
        ndelay,
        apply_filter,
        beprefilter_cutoff,
        beprefilter_order,
        save_dir=None
    ):
        import matplotlib.pyplot as plt
        from scipy import signal

        base_colors = {
            'x': 'midnightblue',
            'y': 'darkred',
            'z': 'darkgreen'
        }

        if gradient == "All":
            grad_list = ['x', 'y', 'z']
        else:
            grad_list = [gradient[-1].lower()]

        if ndelay == "All":
            ndelay_selected = "all"
        else:
            ndelay_selected = int(ndelay)

        plt.figure(figsize=(10, 6))
        any_legend = False

        for case_idx, case in enumerate(cases):
            case_path = case['base_path']
            case_setup = case['setup']
            case_phantom = case['phantom']
            case_path_tail = os.path.basename(os.path.normpath(case_path))
            lighten_amount = 0.0 if case_idx == 0 else min(0.85, 0.40 * case_idx)

            folder_path = os.path.join(case_path, case_setup, case_phantom)
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

                color = self._lighten_color(base_colors[g], lighten_amount)
                legend_added = False
                prefilter_label_added = False
                firstpoint_label_added = False

                for data in data_by_axis[g]:
                    tiempo = data['tiempo']
                    Beddy = data['Beddy']
                    BeddyFitted = data['BeddyFitted']
                    BePrefilter = data['BePrefilter']
                    deadTime = data['deadTime']
                    acqTime = data['acqTime']
                    nDelays = Beddy.shape[0]

                    if ndelay_selected == "all" or (isinstance(ndelay_selected, int) and ndelay_selected >= nDelays):
                        delay_indices = list(range(nDelays))
                    else:
                        delay_indices = [ndelay_selected]

                    for n in delay_indices:
                        delay_offset = n * (deadTime + acqTime)
                        tiempo_corr = tiempo + delay_offset

                        if apply_filter and BePrefilter is not None:
                            if not prefilter_label_added:
                                plt.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10,
                                         label=f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}_Prefiltered")
                                prefilter_label_added = True
                                any_legend = True
                            else:
                                plt.plot(tiempo_corr, BePrefilter[n, :], '--', color=color, alpha=0.9, linewidth=1.0, zorder=10)

                        case_label = f"G{g.upper()}_{case_setup}_{case_phantom}_{case_path_tail}"
                        if not legend_added:
                            plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=3, color=color, alpha=0.4, label=case_label)
                            legend_added = True
                            any_legend = True
                        else:
                            plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=3, color=color, alpha=0.4)

                        if not firstpoint_label_added:
                            y0_measured = Beddy[n, 0]
                            x0 = tiempo_corr[0]
                            plt.annotate(
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

                        plt.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8)

        if any_legend:
            plt.legend(fontsize=9)
        plt.title(f"Beddy Measured - {gradient}", fontsize=13)
        plt.xlabel("Time (ms)", fontsize=12)
        plt.ylabel("Beddy (µT)", fontsize=12)
        plt.grid(True)
        plt.tight_layout()

        setups_joined = "_".join([c['setup'] for c in cases])
        filtered_tag = "_filtered" if apply_filter else ""
        filename = f"Beddy_measured{filtered_tag}_Grad_{gradient}_nDelay_{ndelay}_{setups_joined}.png"
        if save_dir and os.path.isdir(save_dir):
            output_path = os.path.join(save_dir, filename)
        else:
            output_path = os.path.join(cases[0]['base_path'], cases[0]['setup'], filename)
        plt.savefig(output_path, dpi=300)
        plt.close()
        return output_path

    def run_analysis(self):

        print(">>> ANALYZE BUTTON CLICKED")

        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        plot_type = self.plot_combo.currentText()
        base_path = self.base_path
        setup = self.setup_combo.currentText()
        phantom = self.phantom_combo.currentText()
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
                    case_phantom = case['phantom_combo'].currentText()
                    if case_base and case_setup and case_phantom:
                        active_extra_cases.append({
                            'base_path': case_base,
                            'setup': case_setup,
                            'phantom': case_phantom
                        })

                use_add_case = len(active_extra_cases) > 0

                if use_add_case:
                    cases = [{'base_path': base_path, 'setup': setup, 'phantom': phantom}] + active_extra_cases

                    img_path = self._run_beddy_multi_case(
                        cases=cases,
                        gradient=gradient,
                        ndelay=ndelay,
                        apply_filter=apply_filter,
                        beprefilter_cutoff=beprefilter_cutoff,
                        beprefilter_order=beprefilter_order,
                        save_dir=self.comparison_save_dir
                    )
                else:
                    # Original single-case Beddy analysis
                    img_path = run_measured_analysis(
                        base_path=base_path,
                        setup=setup,
                        phantom_position=phantom,
                        gradient_selected=gradient,
                        nDelay_selected=ndelay,
                        apply_filter=apply_filter,
                        beprefilter_cutoff=beprefilter_cutoff,
                        beprefilter_order=beprefilter_order
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

                    QMessageBox.information(self, "Analysis", f"Plot saved automatically to:\n{img_path}")
                
            elif plot_type == "FID":
                fig = run_fid_analysis(
                    base_path=base_path,
                    setup=setup,
                    phantom_position=phantom,
                    gradient_selected=gradient,
                    nDelay_selected=ndelay,
                    apply_filter=apply_filter
                )
                
                if fig is not None:
                    import tempfile
                    tmp_file = os.path.join(tempfile.gettempdir(), "fid_plot.png")
                    fig.savefig(tmp_file, dpi=200)
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
                fig = run_phase_analysis(
                    base_path=base_path,
                    setup=setup,
                    phantom_position=phantom,
                    gradient_selected=gradient,
                    nDelay_selected=ndelay,
                    apply_filter=apply_filter
                )
                
                if fig is not None:
                    import tempfile
                    tmp_file = os.path.join(tempfile.gettempdir(), "phase_plot.png")
                    fig.savefig(tmp_file, dpi=200)
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
            elif plot_type == "Phase":
                fig = run_phase_analysis(
                    base_path=base_path,
                    setup=setup,
                    phantom_position=phantom,
                    gradient_selected=gradient,
                    nDelay_selected=ndelay,
                    apply_filter=apply_filter
                )
                
                if fig is not None:
                    import tempfile
                    tmp_file = os.path.join(tempfile.gettempdir(), "phase_plot.png")
                    fig.savefig(tmp_file, dpi=200)
                    pix = QPixmap(tmp_file)
                    self.image_label.setPixmap(pix)
                    
                    # Store figure for saving
                    self.current_analysis_figure = fig
                    self.current_analysis_image_path = None
                    if apply_filter:
                        self.current_analysis_filename = f"Phase_filtered_Grad_{gradient}_nDelay_{ndelay}"
                    else:
                        self.current_analysis_filename = f"Phase_Grad_{gradient}_nDelay_{ndelay}"
                        
        except Exception as e:
            QMessageBox.critical(self, "Analysis Error", f"An error occurred:\n{e}")
            import traceback
            traceback.print_exc()

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



    

# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EddyCurrentGUI()
    window.show()
    sys.exit(app.exec_())