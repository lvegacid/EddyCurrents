# -*- coding: utf-8 -*-
"""
Created on Mon Mar  2 18:02:56 2026

@author: cidve
"""

# analysis/sequence_analysis.py

import numpy as np
import scipy.io


def sequenceAnalysis(mat_file):

    mat_file = scipy.io.loadmat(mat_file)

    fidsmap = mat_file['data']
    nDelays = mat_file['nDelays'][0][0]
    nReadouts = mat_file['nReadouts'][0][0]
    spectrums = mat_file['spectrums']
    g_axis = mat_file['gAxis'][0]
    deadTime = mat_file['deadTime'][0][0] * 1e-3
    acqTime = mat_file['acqTime'][0][0]

    gradZero = np.squeeze(spectrums[:, 0, :])
    gradPositive = np.squeeze(spectrums[:, 1, :])
    gradNegative = np.squeeze(spectrums[:, 2, :])

    max_spec = np.zeros((3, nDelays))
    max_spec[0, :] = np.max(np.abs(gradZero), axis=1)
    max_spec[1, :] = np.max(np.abs(gradPositive), axis=1)
    max_spec[2, :] = np.max(np.abs(gradNegative), axis=1)

    timeFID = np.linspace(deadTime, acqTime + deadTime, nReadouts)

    BeddyFitted = np.zeros((nDelays, nReadouts))
    Be = np.zeros((nDelays, nReadouts))

    gammaB = 42.577e6

    for n in range(nDelays):

        fid_n = np.squeeze(fidsmap[n, :, :])
        phase_plus = np.unwrap(np.angle(fid_n[1, :]))
        phase_minus = np.unwrap(np.angle(fid_n[2, :]))

        phase_diff = (phase_plus - phase_minus) * (1 / (4 * np.pi * gammaB))

        Be[n, :] = (1 / (4 * np.pi * gammaB)) * \
            np.gradient(phase_plus - phase_minus, timeFID * 1e-3) * 1e6

        BeddyFitted[n, :] = np.polyval(
            np.polyder(np.polyfit(timeFID, phase_diff, 5)),
            timeFID
        ) * 1e6 * 1e3

    return Be, BeddyFitted, timeFID, nDelays, g_axis, deadTime, acqTime