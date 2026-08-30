import io
import json
import math
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SETTINGS_PATH = "/home/nitrogen/spectrometer_web/settings.json"
REFERENCE_PATH = "/home/nitrogen/spectrometer_web/reference.json"

DEFAULT_SETTINGS = {
    "wavelength_factor": 0.6,
    "spectrum_angle_deg": 0.0,
    "led_brightness": 100,
    "csv_german": True,
    "image_rotation_deg": 0,
    "image_flip": False,
}


def apply_rotation(frame, settings):
    """Bringt das Rohbild in die vom Auswertungs-Algorithmus erwartete Ausrichtung
    (heller Referenzpunkt/0. Ordnung rechts, Spektrum laeuft nach links). Ersetzt die
    feste camera.rotation/vflip-Konfiguration des Lambda-Originals durch Drehung +
    optionale Spiegelung per Einstellung, da Kamera/Spiegel-Aufbau je nach Einbaulage
    unterschiedlich orientiert sein koennen (eine reine Drehung kann eine Spiegelung
    im Strahlengang, z.B. durch ein Umlenkprisma, nicht ausgleichen)."""
    k = {0: 0, 90: 1, 180: 2, 270: 3}.get(int(settings.get("image_rotation_deg", 0)), 0)
    rotated = np.rot90(frame, k) if k else frame
    return np.fliplr(rotated) if settings.get("image_flip") else rotated


def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            data = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def load_reference():
    if os.path.exists(REFERENCE_PATH):
        with open(REFERENCE_PATH) as f:
            data = json.load(f)
        return np.array(data["wavelengths"]), np.array(data["intensities"])
    return None


def save_reference(wavelengths, intensities):
    with open(REFERENCE_PATH, "w") as f:
        json.dump({
            "wavelengths": [float(v) for v in wavelengths],
            "intensities": [float(v) for v in intensities],
        }, f)


def find_aperture(frame):
    h, w, _ = frame.shape
    mid_y = h // 2
    mid_x = w // 2
    row = frame[mid_y, mid_x:, :].astype(np.int32)
    brightness = row.sum(axis=1)
    aperture_x = mid_x + int(np.argmax(brightness))

    threshold = brightness.max() * 0.9
    col = frame[:, aperture_x, :].astype(np.int32).sum(axis=1)
    above = np.where(col > threshold)[0]
    if len(above) == 0:
        top, bottom = mid_y - 5, mid_y + 5
    else:
        top, bottom = int(above.min()), int(above.max())
    return aperture_x, (top + bottom) / 2.0, max(bottom - top, 4)


def grating_efficiency(wavelength):
    eff = (800 - (wavelength - 250)) / 800
    return max(eff, 0.3)


def extract_spectrum(frame, wavelength_factor, spectrum_angle_deg):
    aperture_x, aperture_y, aperture_h = find_aperture(frame)
    half_h = aperture_h / 2.0
    angle = math.radians(spectrum_angle_deg)

    xs = np.arange(0, max(int(aperture_x * 7 / 8), 1))
    wavelengths = (aperture_x - xs) * wavelength_factor
    mask = (wavelengths >= 380) & (wavelengths <= 1000)
    xs = xs[mask]
    wavelengths = wavelengths[mask]

    h, w, _ = frame.shape
    intensities = np.zeros(len(xs))
    for i, x in enumerate(xs):
        y0 = math.tan(angle) * (aperture_x - x) + aperture_y
        y_start = int(max(y0 - half_h, 0))
        y_end = int(min(y0 + half_h, h))
        if y_end <= y_start:
            y_end = y_start + 1
        band = frame[y_start:y_end, x, :].astype(np.float64)
        raw = (band[:, 0] + band[:, 2] + 2 * band[:, 1]).mean()
        intensities[i] = raw / grating_efficiency(wavelengths[i])

    order = np.argsort(wavelengths)
    return wavelengths[order], intensities[order], aperture_x, aperture_y, aperture_h


def compute_extinction(wavelengths, intensities, ref_wavelengths, ref_intensities):
    ref_interp = np.interp(wavelengths, ref_wavelengths, ref_intensities)
    ref_interp = np.clip(ref_interp, 1e-6, None)
    intensities_safe = np.clip(intensities, 1e-6, None)
    return -np.log10(intensities_safe / ref_interp)


# Sichtbare Wellenlaenge -> RGB (0..1), fuer die Regenbogen-Einfaerbung der Diagramme.
# Portiert aus LambdaSpektrometer/Python_scripts/spectrometer.py::wavelength_to_color
# (Maurice Kahre, 2021, CC BY 4.0), nur auf 0..1-Floats statt 0..255-Ints umgestellt.
def wavelength_to_color(wavelength):
    thresholds = [380, 400, 440, 460, 490, 580, 780]
    color = [0.0, 0.0, 0.0]
    factor = 0.0
    for i in range(len(thresholds) - 1):
        t1, t2 = thresholds[i], thresholds[i + 1]
        if wavelength < t1 or wavelength >= t2:
            continue
        if i % 2 != 0:
            t1, t2 = t2, t1
        if i < 5:
            color[i % 3] = (wavelength - t2) / (t1 - t2)
        color[2 - i // 2] = 1.0
        factor = 1.0
        break
    if 380 <= wavelength < 420:
        factor = 0.2 + 0.8 * (wavelength - 380) / (420 - 380)
    elif 600 <= wavelength < 780:
        factor = 0.2 + 0.8 * (780 - wavelength) / (780 - 600)
    return color[0] * factor, color[1] * factor, color[2] * factor


def resample(wavelengths, values, grid):
    return np.interp(grid, wavelengths, values, left=np.nan, right=np.nan)


def build_csv(wavelengths, values, value_label, german=True):
    lines = []
    if german:
        lines.append(f"Wellenlaenge [nm];{value_label}")
        for wl, v in zip(wavelengths, values):
            lines.append(f"{wl:.1f};{v:.4f}".replace(".", ","))
    else:
        lines.append(f"Wellenlaenge [nm],{value_label}")
        for wl, v in zip(wavelengths, values):
            lines.append(f"{wl:.1f},{v:.4f}")
    return "\n".join(lines)


def build_csv_series(grid, entries, german=True):
    """entries: Liste von {"label": str, "values": array (auf 'grid' resampled)}."""
    sep = ";" if german else ","

    def fmt(v):
        if np.isnan(v):
            return ""
        text = f"{v:.4f}"
        return text.replace(".", ",") if german else text

    header = ["Wellenlaenge [nm]"] + [e["label"] for e in entries]
    lines = [sep.join(header)]
    for row_i, wl in enumerate(grid):
        wl_text = f"{wl:.1f}".replace(".", ",") if german else f"{wl:.1f}"
        row = [wl_text] + [fmt(e["values"][row_i]) for e in entries]
        lines.append(sep.join(row))
    return "\n".join(lines)


PLOT_XLIM = (350.0, 700.0)


def render_plot(wavelengths, values, ylabel, title, svg=True, extra_series=None):
    """xlim ist bewusst fest (PLOT_XLIM), nicht auto-skaliert: Bei jedem Live-Refresh
    variiert der von extract_spectrum gefundene Wellenlaengenbereich leicht, dazu kommen
    bei der Extinktionsberechnung nahe Null geteilte Ausreisser (-log10 explodiert) --
    ohne feste Achsen springt das Bild dadurch bei jedem Refresh sichtbar herum."""
    fig, ax = plt.subplots(figsize=(8, 4))

    band_lo, band_hi = max(PLOT_XLIM[0], 380.0), min(PLOT_XLIM[1], 780.0)
    if band_hi > band_lo:
        for wl in np.arange(band_lo, band_hi, 4.0):
            ax.axvspan(wl, wl + 4.0, color=wavelength_to_color(wl + 2.0), alpha=0.25, linewidth=0, zorder=0)

    if extra_series:
        for entry in extra_series:
            ax.plot(wavelengths, entry["values"], linewidth=1, label=entry["label"], zorder=2)
        ax.legend(fontsize=8)
    else:
        ax.plot(wavelengths, values, color="black", linewidth=1, zorder=2)

    ax.set_xlim(*PLOT_XLIM)
    if "Extinktion" in ylabel:
        ax.set_ylim(0, 3)
    ax.set_xlabel("Wellenlaenge [nm]")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.3, zorder=1)
    fig.tight_layout()
    if svg:
        buf = io.StringIO()
        fig.savefig(buf, format="svg")
        data = buf.getvalue()
    else:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        data = buf.getvalue()
    plt.close(fig)
    return data
