# Project plan

Durations are indicative for a small team (one GIS/data analyst, one modeller, part-time
scientific lead). Phases 2 and 3 overlap.

## Phase 0: Setup (week 1) - DONE

- Concept agreed (`docs/concept.md`)
- Repository, configuration and model engine in place
- Engine tested on synthetic data

## Phase 1: Grid and data acquisition (weeks 2 to 6)

- Create the thematic data folders on shared storage (`rscia init-data`, see `docs/data_management.md`)
- Download EEZ boundary, build the 1 km grid (`rscia build-grid`)
- Request national data early: desalination plants and capacities, ports, planned
  developments, protected areas, fisheries landing sites
- Download open data (see `docs/data_sources.md`)
- Fill in `config/data_catalogue.csv` as each layer arrives
- Load the 100 coral survey sites into `data/interim/reference/surveys/coral_surveys.csv`

**Milestone M1:** all available raw layers catalogued, gaps listed.

## Phase 2: Layer processing (weeks 4 to 10)

- Ecosystem components: reproject, rasterize, normalize; habitat models for data-poor
  components using Bio-ORACLE predictors
- Pressures: distance decay for point sources, density surfaces for AIS and fishing
- Climate: Bio-ORACLE present and future layers, deltas for 3 SSPs x 2 horizons; NOAA CRW
  heatwave frequency
- Ground-truth the coral layer against survey sites

**Milestone M2:** `rscia check` passes for all 21 components and 19 pressures.

## Phase 3: Sensitivity matrix (weeks 6 to 12)

- Literature review to seed scores
- Expert workshop (KAUST, KAU, NCW and other national experts)
- Record confidence for every score

**Milestone M3:** reviewed sensitivity matrix and confidence matrix.

## Phase 4: Baseline run and validation (weeks 12 to 14)

- Run S0 baseline
- Validate against coral survey sites (`rscia validate`)
- Revisit layers and scores where results and surveys disagree
- Sensitivity analysis: vary scores within their confidence range

**Milestone M4:** validated baseline impact map.

## Phase 5: Scenarios (weeks 14 to 17)

- Encode planned developments in `data/scenarios/development/`
- Run all 14 scenario runs (`rscia run-all`)
- Difference maps and summary tables

**Milestone M5:** scenario results for all runs.

## Phase 6: Reporting and interface (weeks 17 to 22)

- Technical report and atlas of maps
- QGIS project with all outputs
- Optional: web map viewer for scenario comparison

**Milestone M6:** report and tools delivered to stakeholders.

## Risks

| Risk | Mitigation |
|---|---|
| National data (desalination, developments) slow to obtain | Request in week 2; use satellite-derived proxies meanwhile |
| Sparse species data | Habitat suitability models; flag low confidence |
| Expert availability for the workshop | Schedule early; allow remote scoring |
| Planned projects confidential | Run development scenarios in a restricted copy of the repository |
