# -*- coding: utf-8 -*-
"""
Created on Mon Mar  2 18:04:34 2026

@author: cidve
"""

# analysis/measured_analysis.py

import os
import matplotlib.pyplot as plt
from .sequence_analysis import sequenceAnalysis
from .table_manager import update_t0_table


COLORS = {
    'x': 'royalblue',
    'y': 'firebrick',
    'z': 'green'
}


def run_measured_analysis(
    base_path,
    setup,
    phantom_position,
    gradient_selected,
    nDelay_selected
):

    data_by_axis = {'x': [], 'y': [], 'z': []}

    folder_path = os.path.join(base_path, setup, phantom_position)

    for fname in os.listdir(folder_path):

        if not fname.endswith(".mat") or fname.startswith("FID"):
            continue

        file_path = os.path.join(folder_path, fname)

        try:
            Be, BeddyFitted, tiempo, nDelays, g_axis, deadTime, acqTime = \
                sequenceAnalysis(file_path)

            g = g_axis.lower()

            if g in data_by_axis:
                data_by_axis[g].append({
                    'tiempo': tiempo,
                    'Beddy': Be,
                    'BeddyFitted': BeddyFitted,
                    'deadTime': deadTime,
                    'acqTime': acqTime
                })

        except Exception as e:
            print(f"Error in {fname}: {e}")

    if gradient_selected == "All":
        grad_list = ['x', 'y', 'z']
    else:
        grad_list = [gradient_selected[-1].lower()]

    if nDelay_selected == "All":
        nDelay_selected = "all"
    else:
        nDelay_selected = int(nDelay_selected)

    plt.figure(figsize=(10, 6))

    any_legend = False
    for G in grad_list:

        if not data_by_axis[G]:
            continue

        color = COLORS[G]
        B0_all = []
        B0_fitted_all = []
        # ensure legend entry is added only once per gradient
        legend_added = False

        for data in data_by_axis[G]:

            tiempo = data['tiempo']
            Beddy = data['Beddy']
            BeddyFitted = data['BeddyFitted']
            deadTime = data['deadTime']
            acqTime = data['acqTime']

            nDelays = Beddy.shape[0]

            B0_all.extend(Beddy[:, 0])
            B0_fitted_all.extend(BeddyFitted[:, 0])

            if nDelay_selected == "all" or \
               (isinstance(nDelay_selected, int) and
                nDelay_selected >= nDelays):

                for n in range(nDelays):

                    delay_offset = n * (deadTime + acqTime)
                    tiempo_corr = tiempo + delay_offset

                    # plot measured data points
                    if not legend_added:
                        plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=3, color=color, alpha=0.4, label=G.upper())
                        legend_added = True
                        any_legend = True
                    else:
                        plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=3, color=color, alpha=0.4)

                    # plot fitted curve
                    plt.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color, alpha=0.8)
                    
                    # annotate only first point of first nDelay (n=0)
                    if n == 0:
                        y0_measured = Beddy[n, 0]
                        y0_fitted = BeddyFitted[n, 0]
                        x0 = tiempo_corr[0]

                        # measured value in gradient color
                        plt.annotate(f"{y0_measured:.2f}",
                                   (x0, y0_measured),
                                   textcoords="offset points", xytext=(0, 12),
                                   ha='center', fontsize=11, color=color, fontweight='bold')

                        # fitted descriptor inline in gray (slash separates)
                        plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                                   (x0, y0_measured),
                                   textcoords="offset points", xytext=(30, 12),
                                   ha='left', fontsize=11, color='gray', fontweight='bold')

            else:

                n = nDelay_selected

                delay_offset = n * (deadTime + acqTime)
                tiempo_corr = tiempo + delay_offset

                # plot measured data points
                if not legend_added:
                    plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=4, color=color, label=G.upper())
                    legend_added = True
                    any_legend = True
                else:
                    plt.plot(tiempo_corr, Beddy[n, :], 'o', markersize=4, color=color)

                # plot fitted curve
                plt.plot(tiempo_corr, BeddyFitted[n, :], '-', color=color)
                
                # annotate first point
                y0_measured = Beddy[n, 0]
                y0_fitted = BeddyFitted[n, 0]
                x0 = tiempo_corr[0]

                # measured value
                plt.annotate(f"{y0_measured:.2f}",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(0, 12),
                           ha='center', fontsize=11, color=color, fontweight='bold')

                # fitted value in gray right of measured (slash separates)
                plt.annotate(f"/ {y0_fitted:.2f} (fitted)",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(30, 12),
                           ha='left', fontsize=11, color='gray', fontweight='bold')

                # fitted label
                plt.annotate("(fitted)",
                           (x0, y0_measured),
                           textcoords="offset points", xytext=(0, -3),
                           ha='center', fontsize=9, color='gray', fontweight='bold')

        update_t0_table(
            base_path,
            setup,
            G.upper(),
            phantom_position,
            B0_all,
            B0_fitted_all
        )

    if any_legend:
        plt.legend(fontsize=11)
    plt.title(f"Beddy Measured - {gradient_selected}", fontsize=13)
    plt.xlabel("Time (ms)", fontsize=12)
    plt.ylabel("Beddy (µT)", fontsize=12)
    plt.grid(True)
    plt.tight_layout()

    save_dir = os.path.join(base_path, setup, phantom_position)

    filename = f"B_measured_Grad_{gradient_selected}_nDelay_{nDelay_selected}.png"

    output_path = os.path.join(save_dir, filename)
    plt.savefig(output_path, dpi=300)
    plt.close()

    return output_path