# Sketch Repair — Autodesk Fusion Add-In

> Diagnose common sketch quality problems directly inside Autodesk Fusion — find small gaps, detect overlapping geometry, and locate tiny curves from a persistent repair palette while editing a sketch.

---

## ✨ Features

* **Gap Finder** — detects open curve endpoints that fall within a user-defined tolerance
* **Visual gap markers** — highlights detected gaps directly in the canvas and zooms to the selected issue
* **Coincident repair** — close a gap by adding a coincident constraint between its endpoints
* **Bridge with Line** — repair a gap by inserting a line between the two endpoints and constraining it
* **Fix All** — repair all detected gaps at once using either coincident constraints or bridging lines
* **Overlap detection** — identifies fully duplicated sketch curves, including lines, arcs, circles, ellipses, elliptical arcs, conics, fitted splines, and control-point splines
* **Spline-aware comparison** — fitted spline checks include fit points, degree, tangent handles, and curvature handles; control-point splines also validate degree and control points
* **Small Curve Finder** — finds non-construction curves shorter than a configurable maximum length and sorts them from shortest to longest
* **Click-to-locate** — select an issue from the results list to highlight it and move the Fusion view to the affected geometry
* **Flexible units** — tolerance values support `mm`, `cm`, `m`, `in`, `ft`, and `mil`
* **Document-unit defaults** — tolerance controls automatically use the active document's length unit where supported
* **Persistent palette** — the repair window stays available while you work and docks alongside Fusion's sketch tools
* **Sketch-aware refresh** — results are cleared automatically when you enter, exit, or switch to another sketch
* **Non-construction geometry focus** — construction curves are ignored by the diagnostic scans

---

## 🧰 Tools

### Gap Finder

Finds pairs of open endpoints that are separated by less than the specified tolerance.

For each detected gap you can:

* Select it to highlight the associated curves
* Show or hide canvas markers
* Zoom directly to the gap
* Add a **Coincident Constraint**
* **Bridge with Line**
* Repair all detected gaps using either method

The default gap tolerance is `0.1 mm`.

### Overlaps

Scans the active sketch for fully duplicated curves.

Supported curve types include:

* Lines
* Arcs
* Circles
* Ellipses
* Elliptical arcs
* Conic curves
* Fitted splines
* Control-point splines

Duplicate curves are grouped together in the results. Selecting a result highlights the matching geometry in Fusion.

### Small Curves

Finds curves whose length is below a user-defined threshold.

Results are:

* Sorted from shortest to longest
* Displayed with curve type and measured length
* Selectable so the curve can be highlighted and zoomed to in the canvas

The default maximum length is `0.01 mm`.

---

## 🖥️ Palette Overview

| Tab              | Controls                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------- |
| **Gap Finder**   | Tolerance, units, Find Gaps, Show Markers, Coincident Constraint, Bridge with Line, Fix All |
| **Overlaps**     | Find Overlaps and selectable duplicate-curve groups                                         |
| **Small Curves** | Maximum length, units, Find Small Curves, selectable results                                |

---

## 🚀 Installation

1. Download or clone this repository
2. Place the folder containing `SketchRepair.py`, `SketchRepair.html`, and `SketchRepair.manifest` in your Fusion add-ins directory:

   * **Mac:** `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
   * **Windows:** `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
3. In Fusion, open **Utilities → Scripts and Add-Ins** (or press `Shift+S`)
4. Switch to the **Add-Ins** tab
5. Find **SketchRepair** and click **Run**

The included manifest is configured to run the add-in automatically on startup.

---

## 🎯 How to Use

1. Open a Fusion design
2. Create or edit a sketch
3. In the **Sketch → Modify** panel, click **Sketch Repair**
4. The Sketch Repair palette opens on the right side of Fusion
5. Choose one of the available tools:

   * **Gap Finder**
   * **Overlaps**
   * **Small Curves**
6. Configure the tolerance where applicable and run the scan
7. Select an item from the results to locate it in the sketch
8. For detected gaps, choose a repair method or use one of the **Fix All** options

The palette can remain open while you move between sketches. Results are automatically reset when the active sketch changes.

---

## ⚠️ Notes

* A sketch must be actively open in **Edit Sketch** mode before running a scan.
* Construction geometry is excluded from the diagnostic scans.
* Gap repairs modify the sketch by adding either geometric constraints or new line geometry.
* **Overlaps** and **Small Curves** are diagnostic tools — they identify and select geometry but do not automatically remove it.
* Gap tolerance and small-curve thresholds can be entered using `mm`, `cm`, `m`, `in`, `ft`, or `mil`.
* Very large tolerances may identify endpoints or curves that are intentionally separate, so review results before applying bulk repairs.
* The add-in supports Windows and macOS.

---

## 📄 License

MIT License — free to use, modify, and distribute.
