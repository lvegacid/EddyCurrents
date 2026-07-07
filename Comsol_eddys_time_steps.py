import numpy as np
import matplotlib.pyplot as plt

# Parámetros COMSOL
J_max = 11.8

t_ramp_start = 0.100
t_ramp_stop  = 0.1004
t_interval_1 = 0.010
t_interval_2 = 0.010
t_interval_3 = 0.030

# Equivalente a range(start,step,stop) de COMSOL
def comsol_range(start, step, stop):
    n = int(np.floor((stop - start) / step + 1e-12))
    return start + np.arange(n + 1) * step

# Time stepping de COMSOL
t1 = comsol_range(
    0,
    t_ramp_start/3,
    t_ramp_start
)

t2 = comsol_range(
    t_ramp_start,
    (t_ramp_stop - t_ramp_start)/10,
    t_ramp_stop
)

t3 = comsol_range(
    t_ramp_stop,
    t_interval_1/20,
    t_ramp_stop + t_interval_1
)

t4 = comsol_range(
    t_ramp_stop + t_interval_1,
    t_interval_2/2,
    t_ramp_stop + t_interval_1 + t_interval_2
)

t5 = comsol_range(
    t_ramp_stop + t_interval_1 + t_interval_2,
    t_interval_3/2,
    t_ramp_stop + t_interval_1 + t_interval_2 + t_interval_3
)

# Unir todos los tiempos
t = np.unique(np.concatenate([t1, t2, t3, t4, t5]))

# Corriente exactamente igual que en COMSOL
J = (
    (t < t_ramp_start) * J_max
    +
    ((t >= t_ramp_start) & (t < t_ramp_stop))
    * (
        J_max
        - (J_max / (t_ramp_stop - t_ramp_start))
        * (t - t_ramp_start)
    )
)

# Plotimport numpy as np
import matplotlib.pyplot as plt

# Parámetros COMSOL
J_max = 11.8

t_ramp_start = 0.100
t_ramp_stop  = 0.1004
t_interval_1 = 0.010
t_interval_2 = 0.010
t_interval_3 = 0.030

# Equivalente a range(start,step,stop) de COMSOL
def comsol_range(start, step, stop):
    n = int(np.floor((stop - start) / step + 1e-12))
    return start + np.arange(n + 1) * step

# Time stepping de COMSOL
t1 = comsol_range(
    0,
    t_ramp_start/3,
    t_ramp_start
)

t2 = comsol_range(
    t_ramp_start,
    (t_ramp_stop - t_ramp_start)/10,
    t_ramp_stop
)

t3 = comsol_range(
    t_ramp_stop,
    t_interval_1/20,
    t_ramp_stop + t_interval_1
)

t4 = comsol_range(
    t_ramp_stop + t_interval_1,
    t_interval_2/2,
    t_ramp_stop + t_interval_1 + t_interval_2
)

t5 = comsol_range(
    t_ramp_stop + t_interval_1 + t_interval_2,
    t_interval_3/2,
    t_ramp_stop + t_interval_1 + t_interval_2 + t_interval_3
)

# Unir todos los tiempos
t = np.unique(np.concatenate([t1, t2, t3, t4, t5]))

# Corriente exactamente igual que en COMSOL
J = (
    (t < t_ramp_start) * J_max
    +
    ((t >= t_ramp_start) & (t < t_ramp_stop))
    * (
        J_max
        - (J_max / (t_ramp_stop - t_ramp_start))
        * (t - t_ramp_start)
    )
)

# Plot
plt.figure(figsize=(12,5))

# Línea de corriente
plt.plot(t, J, '-', linewidth=2, label='Current')

# Marcadores en los puntos calculados por COMSOL
plt.plot(t, J, 'o', markersize=6, label='COMSOL time points')

plt.xlabel('Time (s)')
plt.ylabel('Current')
#plt.title('Excitation pulse and COMSOL time steps')
plt.grid(True)
plt.legend()
plt.tight_layout()

plt.show()
plt.figure(figsize=(12,5))

# Línea de corriente
plt.plot(t, J, '-', linewidth=2, label='Edge current (A)')

# Marcadores en los puntos calculados por COMSOL
plt.plot(t, J, 'o', markersize=6, label='COMSOL output times')
fontsize=20
plt.xlabel('Time (s)', fontsize=fontsize)
plt.ylabel('I (A)', fontsize=fontsize)
plt.title('Excitation waveform and COMSOL time steps', fontsize=fontsize)
plt.xlim(0.099, 0.1180)
plt.grid(True)

plt.xticks(fontsize=fontsize)
plt.yticks(fontsize=fontsize)

plt.legend(fontsize=fontsize)
plt.tight_layout()

plt.show()