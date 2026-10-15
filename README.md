# Red Sea Cumulative Impact Assessment (RS-CIA)

A cumulative impact assessment tool for the Saudi Arabian Red Sea EEZ, modelled on Symphony
(Swedish marine spatial planning) and WIO Symphony (Nairobi Convention, Western Indian Ocean).
It supports coral reef conservation, turtle conservation and the review of development permits
and EIAs.

Developed by the General Authority for Conservation of Corals and Sea Turtles in the Red Sea.
Lead: James Mbugua. Full method: see the methods document (`docs/methods.md`).

It answers two questions:

1. **Baseline:** Where, and from which human activities, are marine ecosystems under the
   highest combined pressure today?
2. **Scenarios:** How would that picture change under planned developments, under future
   climate (SSP1-2.6, SSP2-4.5, SSP5-8.5), or both?

## How it works

For every 1 km grid cell:

```
Impact = sum over pressures p and ecosystem components c of
         P[p] x E[c] x S[p, c]
```

- `P[p]`: normalized intensity of pressure p (0 to 1)
- `E[c]`: normalized presence or value of ecosystem component c (0 to 1)
- `S[p, c]`: sensitivity of component c to pressure p (0 to 1), from the sensitivity matrix

Scenarios change pressure layers only. The model, components and sensitivity matrix stay
the same, so differences between scenarios come only from the pressures you change.

The 100 coral reef survey sites are used to validate the impact map against observed reef
condition (see `docs/concept.md`, section 8).

## Repository layout

```
config/            All model settings (edit these, not the code)
  project.yaml       Grid, projection, paths, normalization
  ecosystem_components.yaml
  pressures.yaml
  sensitivity_matrix.csv       Scores (pressure rows x component columns)
  sensitivity_confidence.csv   Confidence per score (1 low, 2 medium, 3 high)
  scenarios.yaml
  data_catalogue.csv           One row per input layer: source, status, owner
data/
  raw/             Downloaded data, untouched
  interim/         Reprojected and clipped data
  processed/       Model-ready 1 km rasters (components/, pressures/, scenarios/)
  surveys/         Coral reef survey data
docs/              Concept, project plan, data sources
src/rscia/         Python engine
tests/             Automated tests (run with pytest)
outputs/           Model results (created on first run)
```

## Getting started

```bash
conda env create -f environment.yml
conda activate rscia
pip install -e .

# Check everything works on synthetic data
pytest
rscia demo                  # runs the full pipeline on a small synthetic area

# With real data
rscia build-grid            # builds the 1 km template grid from the EEZ polygon
rscia check                 # reports which configured layers are missing or misaligned
rscia run --scenario S0_baseline
rscia run-all               # every scenario in config/scenarios.yaml
rscia compare --scenario S1_development   # difference map against baseline
rscia validate --scenario S0_baseline     # compare impact with coral survey condition
rscia screen --project config/applications/example_application.yaml   # screen a permit application
```

## Loading data

```bash
python scripts/download_eez.py                         # Saudi Red Sea EEZ from Marine Regions
python scripts/import_bio_oracle.py path/to/bio_oracle  # Bio-ORACLE v3 NetCDF to model GeoTIFFs
python scripts/import_coral_surveys.py surveys.xlsx --map site=Site lat=Lat lon=Lon coral=HC
```

## Screening development applications

Each permit application gets a project file (copy `config/applications/example_application.yaml`)
listing the pressures it adds. `rscia screen` runs it on top of the baseline and writes
`outputs/screening/<id>/screening_report.md`: zone of influence, added impact, existing load,
coral, seagrass, mangrove, turtle and dugong areas affected, and survey sites in the zone.
Screen alternative designs as separate project files and compare the reports.

## Adding a planned project to the development scenario

1. Add the feature to the matching file in `data/raw/scenarios/development/`, for example a
   new desalination plant as a point in `desalination_planned.gpkg` with `capacity_m3_day`.
   Use the same attribute names as the baseline source file.
2. If the project creates a pressure not yet listed, add a line under `planned_development`
   in `config/scenarios.yaml`.
3. Run `rscia run-all` (or `rscia run --scenario S1_development`).

## Outputs per run (`outputs/<run>/`)

| File | Content |
|---|---|
| impact_total.tif | Cumulative impact |
| impact_by_pressure.tif | One band per pressure (band names set) |
| impact_by_component.tif | One band per component |
| confidence.tif | Impact-weighted confidence, 1 low to 3 high |
| hotspots.tif | Top 10 percent of cells |
| component_count.tif | Number of components present |
| summary_by_*.csv | Totals and shares by pressure, component, group, planning unit |
| run_info.json | Run settings and any missing inputs |

Comparisons against the baseline are in `outputs/comparisons/`, quick-look maps in
`outputs/maps/`. `docs/images/demo_maps.png` shows what the synthetic demo produces.

## Status

Phase 0 (setup) complete. See `docs/project_plan.md` for the phases and milestones.
