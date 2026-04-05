#!/usr/bin/env python3
import os

import matplotlib.pyplot as plt
import numpy as np

F, us, d = 15000, 30, 2
Ns = np.array([10, 100, 1000], dtype=float)


def D_cs(n):
    return np.maximum(n * F / us, F / d)


def D_p2p(n, u):
    return np.maximum(np.maximum(F / us, F / d), n * F / (us + n * u))


plt.figure(figsize=(7, 4.2))
plt.loglog(Ns, D_cs(Ns), "k-s", lw=1.5, markersize=7, label="client–server")
for u, lab in [(0.3, "300 Kbit/s"), (0.7, "700 Kbit/s"), (2.0, "2 Mbit/s")]:
    plt.loglog(Ns, D_p2p(Ns, u), "-o", markersize=6, label=f"P2P, u={lab}")

plt.xlabel("N")
plt.ylabel("Min time (s)")
plt.xticks(Ns, ["10", "100", "1000"])
plt.legend(fontsize=8)
plt.grid(True, which="both", ls="-", alpha=0.35)
plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), "images", "task2_plot.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=140)
print(out)
