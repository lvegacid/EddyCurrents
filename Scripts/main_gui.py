# -*- coding: utf-8 -*-

import sys
import os

# --- Make script self-contained (fix import path) ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# -----------------------------------------

import shutil
import re

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QMessageBox, QListWidget, QInputDialog,
    QScrollArea
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QSettings

from analysis.measured_analysis import run_measured_analysis
from analysis.compare_with_simulation import compare_with_simulation


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
        config_row.addWidget(self.setup_combo)
        # now that combo exists we can populate it with the last path
        if self.base_path:
            self.update_setup_dropdown()

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

        analyze_row.addWidget(QLabel("Gradient"))

        self.gradient_combo = QComboBox()
        self.gradient_combo.addItems(["GX", "GY", "GZ", "All"])
        analyze_row.addWidget(self.gradient_combo)

        analyze_row.addSpacing(20)

        analyze_row.addWidget(QLabel("nDelay"))

        self.ndelay_combo = QComboBox()
        self.ndelay_combo.addItems(["All"] + [str(i) for i in range(10)])
        analyze_row.addWidget(self.ndelay_combo)

        analyze_row.addStretch()

        analyze_btn = QPushButton("Analyze")
        analyze_btn.clicked.connect(self.run_analysis)
        analyze_row.addWidget(analyze_btn)

        reset_zoom_btn = QPushButton("Reset Zoom")
        reset_zoom_btn.clicked.connect(self.reset_zoom)
        analyze_row.addWidget(reset_zoom_btn)

        # space for image preview (zoomable + pannable)
        self.image_label = ZoomLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(300)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.image_label)
        main_layout.addWidget(scroll)

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

    # =========================================================

    def select_base_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Base Directory")
        if folder:
            self.base_path = folder
            self.path_edit.setText(folder)
            self.update_setup_dropdown()
            # save for next time
            self.settings.setValue("last_base_path", folder)

    def update_setup_dropdown(self):
        self.setup_combo.clear()
        if not self.base_path or not os.path.isdir(self.base_path):
            return
        folders = [
            f for f in os.listdir(self.base_path)
            if os.path.isdir(os.path.join(self.base_path, f))
        ]
        self.setup_combo.addItems(folders)

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
        
        try:
            fig = compare_with_simulation(
                base_path=self.base_path,
                setup=setup,
                gradient=self.compare_grad_combo.currentText(),
                measured_column=self.compare_meas_combo.currentText(),
                plot_type=self.compare_plot_combo.currentText(),
                save_figure=False  # don't save twice
            )

            # Save to temporary image and display in your ZoomLabel
            temp_path = os.path.join(self.base_path, setup, "temp_compare.png")
            fig.savefig(temp_path, dpi=200)
            import matplotlib.pyplot as plt
            plt.close(fig)  # close the figure to avoid memory issues

            pix = QPixmap(temp_path)
            self.image_label.setPixmap(pix)
            
            QMessageBox.information(self, "Success", "Comparison plot generated.")
            
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

    def run_analysis(self):

        print(">>> ANALYZE BUTTON CLICKED")

        if not self.base_path:
            QMessageBox.warning(self, "Warning", "Select base path first.")
            return

        print("Base path:", self.base_path)
        print("Setup:", self.setup_combo.currentText())
        print("Phantom:", self.phantom_combo.currentText())
        print("Gradient:", self.gradient_combo.currentText())
        print("nDelay:", self.ndelay_combo.currentText())

        # perform analysis and get image path
        img_path = run_measured_analysis(
            base_path=self.base_path,
            setup=self.setup_combo.currentText(),
            phantom_position=self.phantom_combo.currentText(),
            gradient_selected=self.gradient_combo.currentText(),
            nDelay_selected=self.ndelay_combo.currentText()
        )

        # display image if available
        if img_path and os.path.exists(img_path):
            pix = QPixmap(img_path)
            self.image_label.setPixmap(pix)


    

# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EddyCurrentGUI()
    window.show()
    sys.exit(app.exec_())